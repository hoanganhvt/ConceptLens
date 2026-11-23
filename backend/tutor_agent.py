"""Shared dispatch policy for the OpenAI and Codex tutor adapters."""

from copy import deepcopy
from dataclasses import dataclass
import json
import logging
import math
import os
from time import monotonic
from urllib.parse import urlsplit

from fastapi import HTTPException
from openai import APIError, APITimeoutError
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from . import ai, providers
from .language import tr
from .models import Motion
from .physics import motion_point
from .prompt_files import prompt
from .tutor_context import MOTION_UNITS, Summary, TOOL_BYTES, complete_turns, json_bytes, observations, words


LIMIT = 6
log = logging.getLogger("uvicorn.error").getChild("tutor_agent")


class Turn:
    def __init__(self):
        self.started = monotonic()
        try:
            timeout = float(os.getenv("STUDY_TUTOR_DEADLINE_SECONDS", "240"))
        except ValueError:
            timeout = 0
        self.deadline = self.started + timeout if math.isfinite(timeout) and timeout > 0 else self.started
        self.steps = self.actions = 0
        self.reason = self.last_failure = None

    def __enter__(self):
        return self

    def __exit__(self, _, error, traceback):
        status = "error" if error else "ok"
        fallback = {409: "interrupted", 422: "input_limit", 503: "unavailable", 504: "deadline"}
        reason = self.reason
        if error and reason in (None, "answer", "clarify", "replay"):
            reason = fallback.get(getattr(error, "status_code", None), "failed")
        log.info("tutor_turn status=%s reason=%s steps=%d actions=%d elapsed_ms=%.1f",
                 status, reason or "complete", self.steps, self.actions, (monotonic() - self.started) * 1000)

    def remaining(self):
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            self.timeout()
        return remaining

    def timeout(self):
        self.reason = "deadline"
        raise HTTPException(504, tr("Gia sư trả lời quá chậm. Hãy thử lại.",
                                    "The tutor timed out. Please try again."))

    def charge(self, count):
        self.remaining()
        if self.actions + count > LIMIT:
            self.limit()
        self.actions += count

    def limit(self):
        self.reason = "limit"
        raise HTTPException(502, tr("Đã đạt giới hạn gọi công cụ. Hãy thu hẹp câu hỏi.",
                                    "The tool call limit was reached. Try a more specific question."))


class AgentStep(BaseModel):
    action: str = Field(min_length=1, max_length=80)
    arguments_json: str
    text: str
    sources: list[ai.Citation]


class EmptyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CalculatorArguments(EmptyArguments):
    expression: str = Field(min_length=1, max_length=240)


class MotionArguments(Motion, EmptyArguments):
    acceleration: float = Field(ge=-100, le=100)
    velocity: float = Field(ge=-100, le=100)
    duration: float = Field(ge=0, le=60)
    use_snapshot: bool = False


class Recommendation(EmptyArguments):
    text: str = Field(min_length=1, max_length=800)


class CalculatorResult(EmptyArguments):
    result: FiniteFloat


class MotionResult(EmptyArguments):
    t: FiniteFloat
    s: FiniteFloat
    v: FiniteFloat


@dataclass(frozen=True)
class Route:
    arguments: type[BaseModel]
    result: type[BaseModel]
    reason: str


@dataclass
class Action:
    target: str
    arguments: str
    call_id: str | None = None


@dataclass
class Decision:
    text: str
    actions: list[Action]
    sources: list[dict]
    searched: int = 0


CALLOUTS = {
    "calculator": Route(CalculatorArguments, CalculatorResult, "calculation"),
    "simulate_motion": Route(MotionArguments, MotionResult, "motion"),
    "physics_explanation": Route(EmptyArguments, Recommendation, "worked_explanation"),
    "clarify": Route(Recommendation, Recommendation, "missing_information"),
}


def definitions():
    calculator, simulation = deepcopy(ai.tool_definitions())
    simulation["parameters"]["properties"]["use_snapshot"] = {"type": "boolean"}
    simulation["parameters"]["required"].append("use_snapshot")
    simulation["description"] += " Set use_snapshot to true for motion at the saved selection."
    return [calculator, simulation,
            dict(ai.function("physics_explanation", {}), description="Request a worked explanation using a verified result."),
            dict(ai.function("clarify", {"text": {"type": "string"}}), description="Ask one focused question when information is missing.")]


def valid_source(source):
    try:
        url = source["url"]
        parsed = urlsplit(url)
        port = parsed.port
        return (len(url) <= 2048 and (port is None or port > 0)
                and parsed.scheme in ("http", "https") and bool(parsed.hostname)
                and parsed.username is None and not any(c.isspace() or ord(c) < 32 for c in url))
    except (KeyError, TypeError, ValueError):
        return False


def specialist_payload(context, question, traces):
    prior = context.get("verified_results", [])
    if not traces and not prior:
        return None
    highlight = context.get("highlight") or {}
    terms = words(question)
    section = max(context.get("sections", []),
                  key=lambda item: len(terms & words(item["title"] + " " + item["text"])), default={})
    return {"question": question, "lesson_excerpt": (highlight.get("quote") or section.get("text", ""))[:1200],
            "verified_result": traces[-1] if traces else prior[0]}


def local_tool(target, args, context):
    if target == "calculator":
        inputs = args.model_dump()
        output = ai.TOOLS[target][1](inputs)
        units = {}
        source = "calculation"
    else:
        inputs = args.model_dump(exclude={"use_snapshot"})
        source = "tool_arguments"
        if args.use_snapshot:
            values = (context.get("simulation") or {}).get("values", {})
            if (context.get("simulation") or {}).get("source") != "highlight":
                raise ValueError("No saved motion selection")
            inputs = {"acceleration": values["acceleration"], "velocity": values["velocity"], "duration": values["t"]}
            args = MotionArguments.model_validate(inputs)
            source = "highlight"
        if args.duration < 0.1:
            config = Motion(acceleration=args.acceleration, velocity=args.velocity, duration=0.1)
            output = motion_point(config, args.duration)
        else:
            output = ai.TOOLS[target][1](inputs)
        units = MOTION_UNITS
    try:
        CALLOUTS[target].result.model_validate(output)
    except ValueError:
        return None
    trace = dict(tool=target, inputs=inputs, output=output, units=units, source=source)
    return trace if json_bytes(trace) <= TOOL_BYTES else None


class Adapter:
    def __init__(self, settings, question, working, renew, turn):
        self.codex = settings.get("provider") == "codex"
        self.model = settings.get("codex_model") if self.codex else ai.MODEL
        self.api = None if self.codex else ai.client(settings)
        self.question, self.working, self.renew, self.turn = question, working, renew, turn
        self.budget = working.budget if working else None
        self.tools, self.continuation = definitions(), []
        self.wrapper = prompt("providers/openai-context") + " " if not self.codex else ""
        self.instructions = prompt("tutor/instructions", "tutor/agent")
        if self.codex:
            self.instructions += "\n\n" + prompt("tutor/agent-codex")
        if working:
            self.instructions += "\n\n" + prompt("tutor/working-context")
        self.memory_instruction = self.instructions
        if working and working.memories:
            self.memory_instruction += "\n\n" + prompt("tutor/learner-memory")

    def request(self, context, history, search):
        instructions = self.memory_instruction if context.get("learner_memories") else self.instructions
        if self.codex:
            return instructions, dict(lesson=context, history=history, question=self.question,
                                      tools=self.tools, results=self.continuation, search_enabled=search)
        messages = [{"role": "developer", "content": self.wrapper + json.dumps(context, ensure_ascii=False)}]
        messages.extend({"role": item["role"], "content": item["text"]} for item in history)
        messages.append({"role": "user", "content": self.question})
        return self.openai_request(instructions, messages + self.continuation,
                                   tools=self.tools + ([{"type": "web_search"}] if search else []),
                                   tool_choice={"type": "web_search"} if search else "auto",
                                   **({"max_tool_calls": 1} if search else {}))

    def openai_request(self, instructions, data, **options):
        return dict(model=self.model, instructions=instructions, input=data, store=False,
                    max_output_tokens=4096, **options)

    def size(self, request, schema):
        if self.codex:
            return sum(len(part.encode()) for part in providers.codex_request(schema, *request))
        return json_bytes(request)

    def guard(self):
        return self.working.verify_current if self.working and self.working.sent else None

    def send(self, request, schema, *, kind="tutor", search=False, guard=None, search_events=None):
        self.turn.remaining()
        try:
            if self.codex:
                return providers.codex_result(schema, *request, search=search, model=self.model, budget=self.budget,
                                              renew=self.renew, kind=kind, pre_send=guard,
                                              remaining=self.turn.remaining,
                                              search_events={} if search_events is None else search_events)
            return ai.openai_call(self.api, request, self.budget, self.renew, kind,
                                  pre_send=guard, remaining=self.turn.remaining)
        except APITimeoutError:
            self.turn.timeout()
        except APIError as exc:
            raise HTTPException(502, tr("Không thể kết nối OpenAI. Hãy thử lại.",
                                        "Could not connect to OpenAI. Please try again.")) from exc

    def structured_request(self, schema, instructions, context):
        if self.codex:
            return instructions, context
        fmt = {"type": "json_schema", "name": schema.__name__, "strict": True,
               "schema": providers.to_strict_json_schema(schema)}
        return self.openai_request(instructions, json.dumps(context, ensure_ascii=False), text={"format": fmt})

    def structured(self, request, schema, kind):
        result = self.send(request, schema, kind=kind, guard=self.guard())
        if not self.codex and any(item.type in ("web_search_call", "function_call") for item in result.output):
            raise ValueError("Unexpected tool call in structured response")
        parsed = schema.model_validate(result) if self.codex else schema.model_validate_json(result.output_text)
        return parsed.model_dump()

    def compact(self, search):
        if not self.working:
            return
        instructions = prompt("tutor/summary")

        def summary(prefix):
            return self.structured_request(Summary, instructions, prefix)

        self.working.compact(lambda ctx, recent: self.fits(ctx, recent, search),
                             lambda prefix: self.size(summary(prefix), Summary) <= self.budget.input_limit,
                             lambda prefix: self.structured(summary(prefix), Summary, "summary"))

    def fits(self, context, history, search):
        return self.size(self.request(context, history, search), AgentStep) <= self.budget.input_limit

    def observe(self, action, observation):
        if self.codex:
            self.continuation.append({"action": action.target if action.target in CALLOUTS else "unknown",
                                      "output": observation})
        else:
            self.continuation.append(dict(type="function_call_output", call_id=action.call_id,
                                          output=json.dumps(observation, ensure_ascii=False)))

    def decide(self, context, history, search):
        request = self.request(context, history, search)
        if self.codex:
            search_events = {"completed": 0}
            step = self.send(request, AgentStep, search=search, guard=self.guard(), search_events=search_events)
            action = step["action"]
            actions = []
            if action != "answer":
                args = json.dumps({"text": step["text"]}) if action == "clarify" else step["arguments_json"]
                actions.append(Action(action, args))
            return Decision(step["text"], actions, step["sources"], search_events["completed"])
        result = self.send(request, AgentStep, search=search, guard=self.guard())
        self.continuation.extend(result.output)
        actions, sources = [], []
        searched = 0
        offset = 0
        for item in result.output:
            if item.type == "web_search_call":
                if not search or item.status != "completed":
                    raise search_failed()
                searched += 1
            elif item.type == "function_call":
                actions.append(Action(item.name, item.arguments, item.call_id))
            elif item.type == "message":
                for part in item.content:
                    text = getattr(part, "text", "")
                    for note in getattr(part, "annotations", []):
                        if note.type == "url_citation" and 0 <= note.start_index <= note.end_index <= len(text):
                            sources.append(dict(url=note.url, title=note.title,
                                                start=offset + note.start_index, end=offset + note.end_index))
                    offset += len(text)
        return Decision(result.output_text, actions, sources, searched)


def search_failed():
    return HTTPException(502, tr("Tra cứu web chưa hoàn tất hoặc thiếu nguồn hợp lệ. Hãy thử lại.",
                                "Web search did not finish or usable sources are missing. Please try again."))


def run(context, history, question, search, settings, working, renew, turn):
    turn.remaining()
    adapter = Adapter(settings, question, working, renew, turn)
    adapter.compact(search)
    if not working:
        verified = []
        for sequence, pair in reversed(complete_turns(history)):
            verified.extend(observations(sequence, pair))
            if len(verified) >= 3:
                break
        if verified:
            context = {**context, "verified_results": verified[:3]}
    traces, sources, seen, failures = [], {}, set(), set()
    searched = False
    for index in range(LIMIT):
        search_now = search and index == 0
        if working:
            context, history = working.for_provider(lambda ctx, recent: adapter.fits(ctx, recent, search_now))
        turn.remaining()
        turn.steps += 1
        started = monotonic()
        if search_now:
            try:
                decision = adapter.decide(context, history, True)
                if not decision.searched:
                    raise search_failed()
                turn.charge(decision.searched)
            except HTTPException:
                action_metric("web_search", "requested_source", "error", started)
                raise
            action_metric("web_search", "requested_source", "ok", started)
            searched = True
        else:
            decision = adapter.decide(context, history, False)
        if searched:
            for source in decision.sources:
                if valid_source(source):
                    sources[source["url"]] = {**source, "previous": bool(decision.actions)}
        if not decision.actions:
            return reply(decision.text, sources, traces, search, turn, "answer")
        if len(decision.actions) == 1:
            action = decision.actions[0]
            if action.target == "clarify":
                args = parse_arguments(action)
                if args and args.text.strip():
                    return reply(args.text, sources, traces, search, turn, "clarify")
        turn.charge(len(decision.actions))
        if search_now and adapter.codex:
            links = [{"url": source["url"], "title": source["title"]} for source in sources.values()]
            if links and json_bytes(links) <= TOOL_BYTES:
                adapter.continuation.append({"action": "web_search", "output": {"sources": links}})
        for action in decision.actions:
            turn.remaining()
            target = action.target if action.target in CALLOUTS or action.target == "web_search" else "unknown"
            started = monotonic()
            route = CALLOUTS.get(target)
            reason = route.reason if route else ("requested_source" if target == "web_search" else "invalid_route")
            try:
                observation, trace = execute(action, target, context, traces, adapter, seen, failures)
            except HTTPException:
                action_metric(target, reason, "error", started)
                raise
            if trace:
                traces.append(trace)
            status = observation.get("error", "ok")
            if status in ("invalid_tool_output", "specialist_unavailable"):
                turn.last_failure = status
            action_metric(target, reason, status, started)
            adapter.observe(action, observation)
    turn.limit()


def parse_arguments(action):
    try:
        if len(action.arguments.encode()) <= TOOL_BYTES:
            return CALLOUTS[action.target].arguments.model_validate_json(action.arguments)
    except ValueError:
        pass
    return None


def execute(action, target, context, traces, adapter, seen, failures):
    if target in ("web_search", "unknown"):
        return {"error": "route_unavailable"}, None
    args = parse_arguments(action)
    if target == "clarify" or args is None:
        if target in failures:
            adapter.turn.limit()
        failures.add(target)
        return {"error": "invalid_arguments"}, None
    if target == "physics_explanation":
        payload = specialist_payload(context, adapter.question, traces)
        if payload is None:
            return {"error": "verified_result_required"}, None
    signature = target, "highlight" if target == "simulate_motion" and args.use_snapshot else args.model_dump_json()
    if signature in seen:
        return {"error": "repeated_action"}, None
    seen.add(signature)
    if target == "physics_explanation":
        schema = CALLOUTS[target].result
        request = adapter.structured_request(schema, prompt("tutor/physics-specialist"), payload)
        try:
            result = adapter.structured(request, schema, "specialist")
            if result["text"].strip() and json_bytes(result) <= TOOL_BYTES:
                return {"recommendation": result}, None
        except HTTPException as exc:
            if exc.status_code not in (422, 502, 503):
                raise
        except ValueError:
            pass
        return {"error": "specialist_unavailable"}, None
    try:
        trace = local_tool(target, args, context)
    except (KeyError, TypeError, ValueError, ArithmeticError, SyntaxError):
        if target in failures:
            adapter.turn.limit()
        failures.add(target)
        return {"error": "invalid_arguments"}, None
    if trace is None:
        return {"error": "invalid_tool_output"}, None
    return {"result": trace}, trace


def action_metric(target, reason, status, started):
    log.info("tutor_action destination=%s reason=%s status=%s elapsed_ms=%.1f",
             target, reason, status, (monotonic() - started) * 1000)


def reply(text, sources, traces, search, turn, reason):
    turn.remaining()
    if search and not sources:
        turn.reason = "missing_sources"
        raise search_failed()
    if not text.strip():
        if turn.last_failure == "specialist_unavailable":
            turn.reason = turn.last_failure
            raise HTTPException(502, tr("Không thể lấy lời giải vật lý lúc này. Hãy thử lại.",
                                        "The physics explanation is unavailable. Please try again."))
        if turn.last_failure == "invalid_tool_output":
            turn.reason = turn.last_failure
            raise HTTPException(502, tr("Không thể xác minh kết quả tính toán. Hãy thử lại.",
                                        "The calculation could not be verified. Please try again."))
        turn.reason = "missing_answer"
        raise HTTPException(502, tr("Gia sư chưa trả lời. Hãy thử lại.", "The tutor returned no answer. Please try again."))
    citations = []
    for url, source in sources.items():
        start, end = source.get("start", len(text)), source.get("end", len(text))
        if source["previous"] or reason == "clarify" or not (0 <= start <= end <= len(text)):
            start = end = len(text)
        citations.append(dict(url=url, title=source["title"], start=start, end=end))
    turn.reason = reason
    action_metric(reason, "missing_information" if reason == "clarify" else "direct_response", "ok", monotonic())
    return dict(role="assistant", text=text, sources=citations, traces=traces)


def chat(context, history, question, search, *, settings, working=None, renew=None, turn=None):
    if turn:
        return run(context, history, question, search, settings, working, renew, turn)
    with Turn() as turn:
        return run(context, history, question, search, settings, working, renew, turn)
