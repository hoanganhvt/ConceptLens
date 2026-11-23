"""Freeze dev cutoffs and summarize paired synthetic benchmark evidence."""

import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys


MIB = 2 ** 20
KINDS = ("bm25", "static", "e5", "bekko")


def read(folder, kind, split):
    path = folder / f"benchmark-{kind}-{split}.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def anchor_batch(run):
    return next(batch for batch in run["batches"] if batch["size"] == 1000)


def cutoff(batch):
    positive_score = [score for row in batch["runs"] if row["repeat"] == 0 and not row["expected"]
                      for _, score in row["candidates"][:1]]
    # An observed score equal to the strongest negative must abstain as well.
    return math.nextafter(max(positive_score, default=-1), math.inf)


def percentile(values, quantile):
    return sorted(values)[math.ceil(len(values) * quantile) - 1]


def wilson(successes, total):
    rate = successes / total
    z = 1.959963984540054
    center = rate + z * z / (2 * total)
    margin = z * math.sqrt((rate * (1 - rate) + z * z / (4 * total)) / total)
    scale = 1 + z * z / total
    return (max(0, (center - margin) / scale), min(1, (center + margin) / scale))


def metrics(run, batch, cutoff_score):
    latencies = [row["elapsed_ms"] for row in batch["runs"]]
    outcomes, counts = [], Counter()
    for row in batch["runs"]:
        if row["repeat"] != 0:
            continue
        candidates = [key for key, score in row["candidates"] if score >= cutoff_score]
        if row["elapsed_ms"] > run["deadline_ms"]:
            candidates = []
        expected = row["expected"]
        outcome = ("hit" if expected in candidates else "miss") if expected else (
            "false_positive" if candidates else "abstain")
        counts[outcome] += 1
        if expected and candidates and candidates[0] == expected:
            counts["first"] += 1
        outcomes.append(dict(id=row["id"], bucket=row["bucket"], expected=expected, outcome=outcome,
                             expected_rank=next((i for i, key in enumerate(candidates, 1) if key == expected), None),
                             query=row["query"], candidates=row["candidates"],
                             elapsed_ms=row["elapsed_ms"]))
    pos = counts["hit"] + counts["miss"]
    neg = counts["false_positive"] + counts["abstain"]
    return dict(candidate=run["candidate"], split=run["split"], size=batch["size"],
                cutoff=cutoff_score, hits=counts["hit"], positives=pos, top1=counts["first"],
                canonical=next(row["expected_rank"] == 1 for row in outcomes
                               if row["id"] == f"{run['split']}-hit-0"),
                recall95=wilson(counts["hit"], pos), false_positives=counts["false_positive"],
                negatives=neg, fpr95=wilson(counts["false_positive"], neg),
                p50_ms=statistics.median(latencies), p95_ms=percentile(latencies, .95),
                over_deadline=sum(x > run["deadline_ms"] for x in latencies),
                measurements=len(latencies), index_ms=batch["index_ms"],
                index_mib=batch["index_bytes"] / MIB,
                optional_mib=run["optional_bytes"] / MIB,
                added_peak_mib=(run["peak_working_set_bytes"] - (run["initial_working_set_bytes"] or 0)) / MIB,
                cold_median_ms=statistics.median(row["load_first_query_ms"] for row in run["cold"]),
                outcomes=outcomes)


def freeze(folder):
    cutoffs, dev, hashes = {}, [], {}
    for kind in KINDS:
        run = read(folder, kind, "dev")
        batch = anchor_batch(run)
        cutoffs[kind] = cutoff(batch)
        dev.append(metrics(run, batch, cutoffs[kind]))
        evidence = folder / f"benchmark-{kind}-dev.json.gz"
        hashes[kind] = hashlib.sha256(evidence.read_bytes()).hexdigest()
    eligible = [row for row in dev if row["candidate"] != "bm25" and
                row["hits"] / row["positives"] >= .8 and row["canonical"] and not row["false_positives"] and
                row["p95_ms"] <= 150 and row["added_peak_mib"] <= 350 and row["optional_mib"] <= 250]
    best = max((row["hits"] / row["positives"] for row in eligible), default=0)
    ties = [row for row in eligible if best - row["hits"] / row["positives"] <= .02]
    winner = min(ties, key=lambda row: (row["added_peak_mib"], row["p95_ms"]))["candidate"] if ties else None
    frozen = dict(cutoffs=cutoffs, exploratory_winner=winner, dev_evidence_sha256=hashes,
                  qualified=False)
    (folder / "benchmark-frozen.json").write_text(json.dumps(frozen, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(frozen, indent=2))


def plot(folder, dashboard, runtime):
    sys.path.insert(0, str(runtime.resolve()))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = {"bm25": "BM25", "static": "Univo static", "e5": "E5 Small", "bekko": "Bekko a8m"}
    colors = dict(zip(KINDS, ("#366c8c", "#b2563b", "#4c7e68", "#8c518d")))
    fig, (quality, scaling) = plt.subplots(1, 2, figsize=(10.6, 4.6), layout="constrained")
    for kind in KINDS:
        rows = [row for row in dashboard if row["candidate"] == kind and row["split"] == "heldout"]
        if not rows:
            continue
        heldout = next(row for row in rows if row["size"] == 1000)
        med = heldout["hits"] / heldout["positives"]
        low, high = heldout["recall95"]
        quality.errorbar(heldout["p95_ms"], med * 100, yerr=[[100 * (med - low)], [100 * (high - med)]],
                         fmt="o", capsize=3, color=colors[kind], label=labels[kind])
        scaling.plot([row["size"] for row in rows], [row["p95_ms"] for row in rows],
                     "o-", color=colors[kind], label=labels[kind])
    quality.set(xscale="log", xlabel="Warm p95 latency (ms, log scale)", ylim=(0, 105),
                ylabel="Recall@3 (%)", title="Held-out quality at 1,000 memories")
    quality.axhline(80, color="#777777", linestyle="--", linewidth=1)
    scaling.axhline(150, color="#777777", linestyle="--", linewidth=1)
    scaling.set(xscale="log", yscale="log", xlabel="Active memories", ylabel="Warm p95 latency (ms)",
                title="Latency as the library grows")
    scaling.legend(loc="upper left", fontsize=8)
    for axes in (quality, scaling):
        axes.grid(alpha=.2)
    fig.suptitle("Exploratory Windows host • single-query retrieval")
    fig.savefig(folder / "benchmark-figure.png", dpi=165)


def summarize(folder, plot_runtime):
    frozen = json.loads((folder / "benchmark-frozen.json").read_text(encoding="utf-8"))
    dashboard = []
    details = []
    for kind in KINDS:
        evidence = folder / f"benchmark-{kind}-dev.json.gz"
        if hashlib.sha256(evidence.read_bytes()).hexdigest() != frozen["dev_evidence_sha256"][kind]:
            raise ValueError("Dev results changed after the cutoff was frozen")
        for split in ("dev", "heldout"):
            try:
                run = read(folder, kind, split)
            except FileNotFoundError:
                continue
            for batch in run["batches"]:
                row = metrics(run, batch, frozen["cutoffs"][kind])
                outcomes = row.pop("outcomes")
                dashboard.append(row)
                if batch["size"] == 1_000:
                    details.extend(dict(candidate=kind, split=split, **outcome) for outcome in outcomes)
    csv_path = folder / "benchmark-summary.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(dashboard[0]))
        writer.writeheader()
        writer.writerows(dashboard)
    (folder / "benchmark-outcomes.json").write_text(json.dumps(details, ensure_ascii=False, indent=2) + "\n",
                                                    encoding="utf-8")
    for row in dashboard:
        if row["size"] == 1000:
            print(f"{row['split']:<7} {row['candidate']:<7} hits {row['hits']:2}/30 "
                  f"top1 {row['top1']:2}/30 fp {row['false_positives']:2}/30 "
                  f"p50 {row['p50_ms']:6.2f} p95 {row['p95_ms']:6.2f} "
                  f"RAM {row['added_peak_mib']:6.1f} disk {row['optional_mib']:6.1f}")
    if plot_runtime:
        plot(folder, dashboard, plot_runtime)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "summarize"))
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--plot-runtime", type=Path)
    args = parser.parse_args()
    if args.action == "freeze":
        freeze(args.evidence)
    else:
        summarize(args.evidence, args.plot_runtime)
