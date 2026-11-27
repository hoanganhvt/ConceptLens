"""Measure the local lesson and scene pipeline with scripted provider replies."""

import argparse
from collections import Counter
from copy import deepcopy
import json
import logging
import os
from pathlib import Path
from statistics import median
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from fastapi import HTTPException


def elapsed(operation, *args):
    started = perf_counter()
    result = operation(*args)
    return result, round((perf_counter() - started) * 1000, 3)


def measure(samples, data):
    os.environ["STUDY_DATA"] = data
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from backend import main
    from backend.demo import ROAD, SAMPLE
    from backend.models import Illustration, IllustrationBatch, LessonDraft, Roadmap

    text = deepcopy(SAMPLE)
    opening = text.pop("illustrations")[0]
    later = {**opening, "section": min(1, len(text["sections"]) - 1), "title": "Second scene"}
    text["illustration_plan"] = [
        {"section": scene["section"], "brief": brief}
        for scene, brief in ((opening, "Opening scene"), (later, "Second scene"))
    ]
    rows = []
    settings = {"provider": "codex", "codex_model": "scripted-prose",
                "visual_provider": "agy", "agy_visual_model": "scripted-illustration"}
    main.put("ai-settings", settings)

    for scenario in ("both-ready", "timeout-then-retry"):
        for sample in range(samples + 3):
            calls = Counter()

            def structured(schema, instructions, context, *, settings):
                if schema is LessonDraft:
                    calls["prose"] += 1
                    return deepcopy(text)
                if schema is Illustration:
                    calls["repair"] += 1
                    return deepcopy(opening)
                assert schema is IllustrationBatch
                brief = context["illustration_plan"][0]["brief"]
                calls[brief] += 1
                if brief == "Second scene" and scenario == "timeout-then-retry" and calls[brief] == 1:
                    raise HTTPException(504)
                return {"illustrations": [deepcopy(opening if brief == "Opening scene" else later)]}

            road = main.commit(Roadmap.model_validate(ROAD))
            rid, tid = road["id"], road["chapters"][0]["topics"][0]["id"]
            with patch.object(main.ai, "structured", side_effect=structured):
                lesson, generation_ms = elapsed(main.generate, rid, tid)
                retry_ms = None
                if scenario == "timeout-then-retry":
                    failed = lesson["illustration_status"][1]
                    assert failed["state"] == "failed" and failed["error"] == 504
                    retry = main.RetryIllustration(version=lesson["version"], attempts=failed["attempts"])
                    lesson, retry_ms = elapsed(main.retry_illustration, rid, tid, 1, retry)
                _, repair_ms = elapsed(main.repair, rid, tid, 0, main.Repair(error="Synthetic", manual=True))
            assert all(slot["state"] == "ready" for slot in lesson["illustration_status"])
            assert calls == {"prose": 1, "Opening scene": 1, "Second scene": 1 + (retry_ms is not None), "repair": 1}
            if sample >= 3:
                rows.append({"scenario": scenario, "sample": sample - 2, "generation_ms": generation_ms,
                             "retry_ms": retry_ms, "repair_ms": repair_ms, "calls": dict(calls)})
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    logging.disable(logging.WARNING)
    with TemporaryDirectory(prefix="study-phase4c-benchmark-") as data:
        rows = measure(args.samples, data)
    args.output.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    for scenario in dict.fromkeys(row["scenario"] for row in rows):
        selected = [row for row in rows if row["scenario"] == scenario]
        outputs = {}
        for field in ("generation_ms", "retry_ms", "repair_ms"):
            values = [row[field] for row in selected if row[field] is not None]
            if values:
                outputs[field] = round(median(values), 3)
        print(f"{scenario} ({len(selected)} measured samples), median milliseconds: {outputs}")
