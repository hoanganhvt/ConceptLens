"""Measure synthetic memory retrieval with a local encoder or SQLite FTS5."""

import argparse
from array import array
import ctypes
import gzip
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import random
import re
import sqlite3
import subprocess
import sys
from time import perf_counter
import unicodedata

from benchmark_fixtures import corpus


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from backend.embedding_cpu import Encoder

SEED = 349311
MIB = 2 ** 20
DEADLINE = 200


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def memory_bytes():
    if sys.platform == "win32":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("size", wintypes.DWORD), ("faults", wintypes.DWORD),
                *[(field, ctypes.c_size_t) for field in
                  ("peak", "working", "peak_paged", "paged", "peak_nonpaged", "nonpaged",
                   "pagefile", "peak_pagefile")],
            ]

        current_process = ctypes.windll.kernel32.GetCurrentProcess
        current_process.restype = wintypes.HANDLE
        get_counters = ctypes.windll.psapi.GetProcessMemoryInfo
        get_counters.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
        counts = Counters()
        counts.size = ctypes.sizeof(counts)
        if not get_counters(current_process(), ctypes.byref(counts), counts.size):
            raise ctypes.WinError()
        return counts.working, counts.peak
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak *= 1 if sys.platform == "darwin" else 1024
    return None, peak


def host():
    cpu = platform.processor()
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            cpu = winreg.QueryValueEx(key, "ProcessorNameString")[0]
        ram_kib = ctypes.c_ulonglong()
        ctypes.windll.kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(ram_kib))
        ram = ram_kib.value * 1024
    else:
        ram = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    return dict(os=platform.platform(), python=platform.python_version(), sqlite=sqlite3.sqlite_version,
                cpu=cpu, logical_cpus=os.cpu_count(), physical_memory_bytes=ram)


def ready(args):
    if args.kind == "bm25":
        return None, None
    folder = args.models / args.kind
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    return Encoder(folder, manifest), manifest


def cold_loads():
    readings = []
    for _ in range(3):
        start = perf_counter()
        child = subprocess.run([sys.executable, "-B", __file__, *sys.argv[1:], "--cold"],
                               capture_output=True, text=True)
        if child.returncode:
            raise RuntimeError(f"Fresh encoder process failed: {child.stderr.strip() or child.returncode}")
        reading = json.loads(child.stdout)
        readings.append(dict(reading, subprocess_ms=(perf_counter() - start) * 1_000))
    return readings


def query_terms(question):
    terms = re.findall(r"[^\W_]+", unicodedata.normalize("NFC", question.casefold()))
    return " OR ".join(f'"{term}"' for term in dict.fromkeys(terms))


def create_index(encoder, docs, db_path):
    conn = sqlite3.connect(db_path)
    if encoder is None:
        conn.execute("""CREATE VIRTUAL TABLE documents USING fts5(
            id UNINDEXED, text, tokenize='unicode61 remove_diacritics 2')""")
        conn.executemany("INSERT INTO documents VALUES (?, ?)",
                         ((key, doc) for key, doc, active in docs if active))
    else:
        conn.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, active INTEGER NOT NULL, vector BLOB)")
        for start in range(0, len(docs), 32):
            batch = docs[start:start + 32]
            vectors = encoder.encode_many([doc for _, doc, _ in batch], query=False)
            assert all(len(v) == encoder.dimension and abs(math.hypot(*v) - 1) < 0.0001 for v in vectors)
            conn.executemany("INSERT INTO documents VALUES (?, ?, ?)",
                             ((key, active, array("f", vector).tobytes())
                              for (key, _, active), vector in zip(batch, vectors)))
    conn.commit()
    return conn


def scan(conn, encoder, question):
    if encoder is None:
        return [(key, -score) for key, score in conn.execute(
            "SELECT id, rank FROM documents WHERE documents MATCH ? ORDER BY rank, id LIMIT 3",
            (query_terms(question),))]
    query = encoder.encode(question, query=True)
    ranked = [(key, math.sumprod(query, array("f", blob))) for key, blob in
              conn.execute("SELECT id, vector FROM documents WHERE active=1")]
    return sorted(ranked, key=lambda item: (-item[1], item[0]))[:3]


def measure(args, encoder):
    batches = []
    for size in args.sizes:
        docs, queries = corpus(args.split, size)
        db_path = args.scratch / f"{args.kind}-{args.split}-{size}.sqlite"
        db_path.unlink(missing_ok=True)
        start = perf_counter()
        conn = create_index(encoder, docs, db_path)
        index_ms = (perf_counter() - start) * 1_000
        scan(conn, encoder, queries[0]["query"])
        records = []
        for repeat in range(3):
            ordered = list(queries)
            random.Random(SEED + repeat).shuffle(ordered)
            for case in ordered:
                start = perf_counter()
                candidates = scan(conn, encoder, case["query"])
                elapsed = (perf_counter() - start) * 1_000
                records.append({**case, "repeat": repeat, "elapsed_ms": elapsed, "candidates": candidates})
        conn.close()
        batches.append(dict(size=size, index_ms=index_ms, index_bytes=db_path.stat().st_size,
                            runs=records))
        print(f"{args.kind} {args.split}: finished {size:,} memories", flush=True)
    return batches


def filesize(folder):
    return sum(path.stat().st_size for path in folder.rglob("*") if path.is_file())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("bm25", "bekko", "e5", "static"))
    parser.add_argument("--split", choices=("dev", "heldout"), required=True)
    parser.add_argument("--sizes", nargs="+", type=int, default=[100, 1_000, 10_000])
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--runtimes", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cold", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    runtime = args.runtimes / f"runtime-{args.kind}"
    sys.path.insert(0, str(runtime.resolve()))
    if args.cold:
        start = perf_counter()
        encoder, _ = ready(args)
        if encoder:
            assert len(encoder.encode("First synthetic warm-up", query=True)) == encoder.dimension
        else:
            sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE documents USING fts5(text)")
        print(json.dumps(dict(load_first_query_ms=(perf_counter() - start) * 1_000,
                              peak_working_set_bytes=memory_bytes()[1])))
        return

    initial, _ = memory_bytes()
    cold = cold_loads()
    encoder, manifest = ready(args)
    args.scratch.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    batches = measure(args, encoder)
    _, peak = memory_bytes()
    result = dict(candidate=args.kind, split=args.split, seed=SEED, host=host(),
                  command=subprocess.list2cmdline([sys.executable, "-B", *sys.argv]),
                  revision=revision, cpu_threads=2 if encoder else 1, cold=cold,
                  initial_working_set_bytes=initial, peak_working_set_bytes=peak,
                  optional_bytes=filesize(runtime) + filesize(args.models / args.kind) if encoder else 0,
                  manifest=manifest, deadline_ms=DEADLINE,
                  code={path.name: digest(path) for path in
                        (Path(__file__), Path(__file__).with_name("benchmark_fixtures.py"),
                         ROOT / "backend" / "embedding_cpu.py")},
                  packages={dist.metadata["Name"]: dist.version
                            for dist in importlib.metadata.distributions(path=[str(runtime)])},
                  batches=batches)
    args.output.write_bytes(gzip.compress(json.dumps(result, ensure_ascii=False).encode(), mtime=0))


if __name__ == "__main__":
    main()
