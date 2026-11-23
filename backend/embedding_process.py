"""Optional CPU encoder in one spawned process."""

from hashlib import file_digest, sha256
import json
import math
from multiprocessing import get_context
import os
from pathlib import Path
from threading import Lock
from time import monotonic


def checked_manifest(path):
    path = path.resolve()
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    kind = manifest["kind"]
    dimension = manifest["dimension"]
    expected = {"bekko": 384, "e5": 384, "static": 128}
    max_tokens = manifest.get("max_tokens", 128)
    if (manifest.get("qualified") is not True or not isinstance(manifest["id"], str)
            or not 0 < len(manifest["id"]) <= 160 or type(dimension) is not int
            or expected.get(kind) != dimension or type(manifest["threshold"]) not in (float, int)
            or not -1 <= manifest["threshold"] <= 1
            or type(max_tokens) is not int or not 1 <= max_tokens <= 512):
        raise ValueError("Invalid encoder manifest")
    files = manifest["files"]
    required = {manifest["model"], manifest["tokenizer"]}
    if kind == "bekko":
        required.add(str(Path(manifest["model"]).with_suffix(".bin").as_posix()))
    if not required <= files.keys():
        raise ValueError("Incomplete encoder manifest")
    for name, expected_hash in files.items():
        file = (path / name).resolve()
        if not file.is_relative_to(path) or Path(name).is_absolute():
            raise ValueError("Invalid encoder artifact path")
        with file.open("rb") as f:
            if file_digest(f, "sha256").hexdigest() != expected_hash:
                raise ValueError("Invalid encoder artifact checksum")
    return manifest


def serve(pipe, directory):
    try:
        for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            os.environ[key] = "2"
        repo = Path(directory).resolve()
        manifest = checked_manifest(repo)
        from .embedding_cpu import Encoder

        encoder = Encoder(repo, manifest)
        probe = encoder.encode("encoder readiness", query=True)
        if (len(probe) != manifest["dimension"] or not any(probe)
                or any(not math.isfinite(value) for value in probe)):
            raise ValueError("Invalid encoder output")
        vector_contract = {key: manifest[key] for key in ("kind", "dimension", "model", "tokenizer", "files")}
        vector_contract.update(format=1, max_tokens=manifest.get("max_tokens", 128))
        version = sha256(json.dumps(vector_contract, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        pipe.send({"id": f'{manifest["id"]}:{version}', "dimension": manifest["dimension"],
                   "threshold": manifest["threshold"]})
        while True:
            texts, query = pipe.recv()
            pipe.send(encoder.encode_many(texts, query=query))
    except (EOFError, BrokenPipeError):
        pass
    except Exception:
        pipe.send(None)
    finally:
        pipe.close()


class EncoderProcess:
    def __init__(self, directory):
        self.directory = directory
        self.status = "building" if directory else "missing"
        self.metadata = None
        self.lock = Lock()
        self.process = self.pipe = None
        self.sent = None

    def start(self):
        if not self.directory or self.status == "error":
            return
        with self.lock:
            if self.process is None:
                if not (Path(self.directory) / "manifest.json").is_file():
                    self.status = "missing"
                    return
                context = get_context("spawn")
                self.pipe, child = context.Pipe()
                try:
                    self.process = context.Process(target=serve, args=(child, self.directory), daemon=True)
                    self.process.start()
                    self.sent = monotonic()
                    self.status = "building"
                except (OSError, RuntimeError):
                    self.process = None
                    self.fail()
                finally:
                    child.close()
            elif not self.process.is_alive():
                self.fail()
            elif self.sent is not None:
                try:
                    if self.pipe.poll(0):
                        reply = self.pipe.recv()
                        if reply is None:
                            self.fail()
                        elif self.metadata is None:
                            self.metadata = reply
                            self.status = "ready"
                        self.sent = None
                    elif monotonic() - self.sent > 30:
                        self.fail()
                except (EOFError, OSError):
                    self.fail()

    def encode(self, texts, *, query, deadline):
        if not self.lock.acquire(blocking=False):
            return
        try:
            if self.status != "ready" or self.sent is not None or monotonic() >= deadline:
                return
            self.pipe.send((texts, query))
            self.sent = monotonic()
            if self.pipe.poll(max(0, deadline - monotonic())):
                reply = self.pipe.recv()
                self.sent = None
                if reply is None:
                    self.fail()
                return reply
        except (EOFError, OSError):
            self.fail()
        finally:
            self.lock.release()

    def fail(self):
        self.status = "error"
        self.metadata = None
        if self.process and self.process.is_alive():
            self.process.terminate()

    def close(self):
        with self.lock:
            if self.process is not None:
                if self.process.is_alive():
                    self.process.terminate()
                self.process.join(timeout=2)
                if self.process.is_alive():
                    self.process.kill()
                    self.process.join()
                self.process.close()
            if self.pipe is not None:
                self.pipe.close()
            self.process = self.pipe = self.sent = self.metadata = None
            self.status = "building" if self.directory else "missing"
