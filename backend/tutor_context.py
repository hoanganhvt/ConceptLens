"""Build and measure provider input without changing the saved transcript."""

from contextlib import contextmanager
import json
import logging
import math
import os
import re
from time import perf_counter

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .chat_state import OWNER
from .language import language, tr

SUMMARY_FORMAT = 1
TOOL_BYTES = 1024
ESTIMATOR = "utf8-json-v1"
MOTION_UNITS = {"acceleration": "m/s²", "velocity": "m/s", "duration": "s",
                "t": "s", "s": "m", "v": "m/s"}
log = logging.getLogger("uvicorn.error").getChild("tutor_context")


def json_bytes(data):
    return len(json.dumps(data, ensure_ascii=False, separators=(",", ":"),
                          default=lambda item: item.model_dump(mode="json", exclude_unset=True)).encode())


def too_large():
    return HTTPException(422, tr("Ngữ cảnh quá dài. Hãy rút ngắn câu hỏi hoặc đoạn đã chọn.",
                                "This context is too long. Shorten your question or selected passage."))


class Budget:
    def __init__(self, provider, model):
        overrides = json.loads(os.getenv("STUDY_TUTOR_MODEL_WINDOWS", "{}"))
        window = overrides.get(f"{provider}:{model}", os.getenv("STUDY_TUTOR_CONTEXT_WINDOW", "16384"))
        self.input_limit = int(window) - 4096 - 2048

    @contextmanager
    def measure(self, size, kind):
        if size > self.input_limit:
            raise too_large()
        start = perf_counter()
        usage = {}
        status = "error"
        try:
            yield usage
            status = "ok"
        finally:
            log.info("tutor_model_call kind=%s status=%s estimator=%s estimated_input=%d "
                     "input_limit=%d reported_input=%s reported_output=%s elapsed_ms=%.1f",
                     kind, status, ESTIMATOR, size, self.input_limit, usage.get("input_tokens"),
                     usage.get("output_tokens"), (perf_counter() - start) * 1000)


class Summary(BaseModel):
    text: str = Field(min_length=1, max_length=900)


def words(text):
    return set(re.findall(r"[^\W\d_]{3,}", text.casefold()))


def finite_values(values, units):
    return {key: value for key, value in values.items()
            if key in units and type(value) in (float, int) and math.isfinite(value)}


def evidence(doc, topic, highlight, progress, playback, question):
    required = {"topic": topic, "lesson_version": doc["version"], "study_language": language.get()}
    optional = []
    terms = words(question)
    section = None
    motion_index = None
    if highlight:
        required["highlight"] = {key: highlight[key] for key in ("id", "version", "block", "start", "end", "quote")}
        block = highlight["block"]
        if block[0] == "s" and block[1:].isdigit():
            section = int(block[1:])
        elif block[0] in ("i", "e") and block[1:].isdigit() and int(block[1:]) < len(doc["illustrations"]):
            motion_index = int(block[1:])
            section = doc["illustrations"][motion_index]["section"]
        snapshot = highlight.get("snapshot") or {}
        values = finite_values(snapshot, MOTION_UNITS)
        units = {key: MOTION_UNITS[key] for key in values}
        if not values and type(snapshot.get("k")) in (int, float) and math.isfinite(snapshot["k"]):
            values, units = {"k": snapshot["k"]}, {"k": "slider position"}
        if values:
            required["simulation"] = {"source": "highlight", "values": values, "units": units}
        terms |= words(highlight["quote"])

    def relevance(text):
        return len(terms & words(text))

    for index, item in sorted(enumerate(doc["sections"]),
                              key=lambda entry: (entry[0] == section,
                                                 relevance(entry[1]["title"] + " " + entry[1]["text"])),
                              reverse=True):
        optional.append(("sections", {"index": index, **item}))
    if not highlight:
        for index, visual in enumerate(doc["illustrations"]):
            if visual["mode"] == "motion" and relevance(" ".join(visual[key] for key in
                                                                 ("title", "instruction", "explanation"))):
                saved = playback(index)
                if saved:
                    values = finite_values({**saved["params"], **saved["points"][saved["index"]]}, MOTION_UNITS)
                    optional.insert(0, ("simulation", {"source": "current_playback", "illustration": index,
                                                       "values": values, "units": MOTION_UNITS}))
                    break
    if motion_index is not None:
        visual = doc["illustrations"][motion_index]
        optional.insert(0, ("illustrations", {key: visual[key] for key in ("title", "instruction", "explanation")}))
    relevant_quiz = sorted(enumerate(doc["quiz"]), key=lambda entry: relevance(entry[1]["prompt"]), reverse=True)
    attempts = []
    for index, item in relevant_quiz:
        entries = progress.get(str(index), [])
        if entries and relevance(item["prompt"]):
            submitted = {key: entries[-1][key] for key in ("answer", "correct", "explanation")}
            attempts.append(("quiz_feedback", {"question": index, "prompt": item["prompt"], **submitted}))
    return required, attempts[:3] + optional


def complete_turns(history):
    return [(index + 2, history[index:index + 2]) for index in range(len(history) - 1)
            if history[index]["role"] == "user" and history[index + 1]["role"] == "assistant"]


def observations(sequence, pair):
    for index, trace in reversed(list(enumerate(pair[1].get("traces", [])))):
        tool, output = trace.get("tool"), trace.get("output")
        if tool not in ("calculator", "simulate_motion") or not isinstance(output, dict):
            continue
        units = {} if tool == "calculator" else MOTION_UNITS
        values = finite_values(output, {"result": None} if tool == "calculator" else units)
        if values and json_bytes(trace) <= TOOL_BYTES:
            inputs = trace["inputs"]
            keys = set(values) | (inputs.keys() if tool == "simulate_motion" else set())
            yield {"source": "prior_tool", "message_sequence": sequence, "trace_index": index,
                   "tool": tool, "inputs": inputs, "values": values,
                   "units": {key: value for key, value in units.items() if key in keys}}


class WorkingContext:
    def __init__(self, db, rid, tid, branch, required, optional, history, budget):
        self.key = (OWNER, rid, tid, required["lesson_version"], branch, SUMMARY_FORMAT)
        with db() as conn:
            row = conn.execute("""SELECT covered, content FROM tutor_summaries
                WHERE owner=? AND roadmap=? AND topic=? AND lesson_version=? AND branch=? AND format=?""",
                self.key).fetchone()
        self.turns = complete_turns(history)
        self.required = required
        self.optional = optional
        self.verified = []
        for sequence, pair in reversed(self.turns):
            self.verified.extend(observations(sequence, pair))
            if len(self.verified) >= 3:
                self.verified = self.verified[:3]
                break
        self.covered, self.summary = (row[0], json.loads(row[1])) if row and row[0] <= len(history) else (0, None)
        self.budget = budget
        self.pending = None

    def pack(self, fits, *, details=True):
        context, recent = dict(self.required), []
        if not fits(context, recent):
            raise too_large()
        for result in self.verified:
            candidate = {**context, "verified_results": [*context.get("verified_results", []), result]}
            if fits(candidate, recent):
                context = candidate
        # Reserve room for the bounded digest before filling the rest with recent turns.
        if self.summary:
            candidate = {**context, "older_summary": {"covered_through": self.covered, **self.summary}}
            newest = self.turns[-1][1] if self.turns and self.turns[-1][0] > self.covered else []
            if fits(candidate, newest if fits(context, newest) else []):
                context = candidate
        retained_after = self.covered if "older_summary" in context else 0
        for sequence, pair in reversed(self.turns):
            if sequence <= retained_after:
                break
            if not fits(context, pair + recent):
                break
            recent = pair + recent
        if details:
            for key, item in self.optional:
                value = item if key == "simulation" else [*context.get(key, []), item]
                candidate = {**context, key: value}
                if fits(candidate, recent):
                    context = candidate
        return context, recent

    def compact(self, fits, summary_fits, summarize):
        _, recent = self.pack(fits, details=False)
        retained = len(recent) // 2
        omitted = len(self.turns) - retained
        if not omitted or self.turns[omitted - 1][0] <= self.covered:
            return
        # Reclaim room for several sends while keeping the two newest fitting turns.
        omitted += min(4, max(0, retained - 2))
        prefix = {"previous": self.summary, "covered_through": self.covered, "turns": []}
        covered = self.covered
        for sequence, pair in self.turns[:omitted]:
            if sequence <= covered:
                continue
            turn = {"through": sequence, "messages": [{"role": m["role"], "text": m["text"]} for m in pair],
                    "verified_results": list(observations(sequence, pair))[:3]}
            if not prefix["turns"] and not summary_fits({**prefix, "turns": [turn]}):
                # A single oversized turn must not prevent the prefix from advancing.
                for item in turn["messages"]:
                    item["excerpt"] = item.pop("text")[:320]
                while turn["verified_results"] and not summary_fits({**prefix, "turns": [turn]}):
                    turn["verified_results"].pop()
            candidate = {**prefix, "turns": [*prefix["turns"], turn]}
            if not summary_fits(candidate):
                break
            prefix, covered = candidate, sequence
        if not prefix["turns"]:
            return
        try:
            summary = summarize(prefix)
            if not summary["text"].strip() or json_bytes(summary) > 1024:
                raise ValueError("Invalid summary")
        except (HTTPException, ValueError):
            log.info("tutor_summary status=fallback format=%d", SUMMARY_FORMAT)
            return
        self.covered, self.summary = covered, summary
        self.pending = (self.key, covered, summary)
