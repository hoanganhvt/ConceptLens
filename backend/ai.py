from .language import tr
import json
import os
from openai import OpenAI, APIError
from fastapi import HTTPException
from typing import Literal
from pydantic import BaseModel, ValidationError
from . import providers
from .prompt_files import prompt
from .models import Lesson, Motion
from .physics import calculate, motion
from .tutor_context import Summary, TOOL_BYTES, json_bytes

MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")


def client(settings):
    key = providers.api_key(settings)
    if not key:
        raise HTTPException(503, tr("Mở Cài đặt để nhập API key, chọn Codex CLI hoặc cấu hình OPENAI_API_KEY.", "Open Settings to enter an API key or select Codex CLI. You can also set OPENAI_API_KEY."))
    return OpenAI(api_key=key, timeout=90, max_retries=1)


def structured(schema, instructions, context, *, settings):
    if settings.get("provider") == "codex":
        model = settings.get("codex_model")
        try:
            return providers.codex_result(schema, instructions, context, model=model)
        except HTTPException as exc:
            error = exc.__cause__
            if schema is not Lesson or not isinstance(error, ValidationError):
                raise
            correction = "\n\nGenerate a complete lesson again. Correct these validation issues: "
            return providers.codex_result(schema, instructions + correction + providers.validation_issues(error),
                                          context, model=model)
    try:
        parsed = client(settings).responses.parse(model=MODEL, instructions=instructions, input=json.dumps(context, ensure_ascii=False),
                                          text_format=schema, store=False).output_parsed
        if parsed is None:
            raise ValueError()
        return parsed.model_dump()
    except (ValueError, ValidationError, APIError) as exc:
        raise HTTPException(502, tr("AI chưa trả về nội dung hợp lệ. Kiểm tra model, API key, hạn mức rồi thử lại.", "The AI returned invalid content. Check your model, API key, and quota, then try again.")) from exc


def function(name, properties):
    return dict(type="function", name=name, strict=True,
                parameters=dict(type="object", properties=properties, required=list(properties), additionalProperties=False))


TOOLS = {
    "calculator": (function("calculator", {"expression":{"type":"string"}}),
                   lambda a: {"result":calculate(a["expression"])}),
    "simulate_motion": (function("simulate_motion", {k:{"type":"number"} for k in Motion.model_fields}),
                        lambda a: motion(Motion(**a))["points"][-1])
}


def tool_definitions():
    return [dict(definition, description=prompt("tools/" + name))
            for name, (definition, _) in TOOLS.items()]


class Citation(BaseModel):
    url: str
    title: str


class TutorStep(BaseModel):
    action: Literal["answer","calculator","simulate_motion","web_search"]
    arguments_json: str
    text: str
    sources: list[Citation]


def tool_output(action, arguments, bounded):
    if bounded and len(arguments.encode()) > TOOL_BYTES:
        return None, {"error": "Tool arguments exceeded the context limit."}
    try:
        args = json.loads(arguments)
        output = TOOLS[action][1](args)
        if bounded and json_bytes(output) > TOOL_BYTES:
            return None, {"error": "Tool result exceeded the context limit."}
        return dict(tool=action, inputs=args, output=output), output
    except (KeyError, TypeError, ValueError, ArithmeticError, SyntaxError) as exc:
        error = str(exc)
        return None, {"error": error[:200] if bounded else error}


def codex_chat(context, history, question, search, model, working=None, renew=None):
    data = dict(lesson=context,history=history,question=question,tools=tool_definitions(),results=[])
    instruction = prompt("tutor/instructions", "tutor/codex-tools")
    budget = working.budget if working else None
    memory_instruction = instruction
    if working:
        instruction += "\n\n" + prompt("tutor/working-context")
        memory_instruction = instruction + ("\n\n" + prompt("tutor/learner-memory") if working.memories else "")
        summary_instruction = prompt("tutor/summary")
        data["search_enabled"] = search
        overhead = providers.codex_overhead(TutorStep, instruction)
        memory_overhead = providers.codex_overhead(TutorStep, memory_instruction) if working.memories else overhead
        summary_overhead = providers.codex_overhead(Summary, summary_instruction)

        def fits(ctx, recent):
            payload = providers.codex_context({**data, "lesson": ctx, "history": recent})
            prefix_size = memory_overhead if "learner_memories" in ctx else overhead
            return prefix_size + len(payload.encode()) <= budget.input_limit

        working.compact(fits,
                        lambda prefix: summary_overhead + len(providers.codex_context(prefix).encode()) <= budget.input_limit,
                        lambda prefix: providers.codex_result(Summary, summary_instruction, prefix, model=model,
                                                             budget=budget, renew=renew, kind="summary"))
    traces, sources = [], {}
    searched = False
    for _ in range(6):
        data["search_enabled"] = search and not searched
        if working:
            data["lesson"], data["history"] = working.for_provider(fits)
        instructions = memory_instruction if "learner_memories" in data["lesson"] else instruction
        guard = {"pre_send": working.verify_current} if working and working.sent else {}
        step = providers.codex_result(TutorStep, instructions, data, search=data["search_enabled"], model=model,
                                      budget=budget, renew=renew, **guard)
        if data["search_enabled"]:
            searched = True
        if searched:
            for source in step["sources"]:
                if source["url"].startswith(("https://","http://")):
                    sources[source["url"]] = source
        action = step["action"]
        if action == "answer":
            if not step["text"].strip() or (search and not sources):
                raise HTTPException(502,tr("Chưa nhận được câu trả lời hoặc nguồn yêu cầu. Hãy thử lại.", "The answer or requested sources are missing. Please try again."))
            end = len(step["text"])
            return dict(role="assistant",text=step["text"],sources=[dict(s,start=end,end=end) for s in sources.values()],traces=traces)
        if action == "web_search":
            search = True
            continue
        trace, output = tool_output(action, step["arguments_json"], working is not None)
        if trace:
            traces.append(trace)
        urls = list(sources.values())
        data["results"].append(dict(action=action, output=output,
                                    sources=[] if working and json_bytes(urls) > TOOL_BYTES else urls))
    raise HTTPException(502,tr("Đã đạt giới hạn lượt gọi công cụ. Hãy thu hẹp câu hỏi.", "The tool call limit was reached. Try a more specific question."))


def openai_call(api, request, budget, renew, kind="tutor", *, pre_send=None):
    if renew:
        renew()
    if budget is None:
        return api.responses.create(**request)
    with budget.measure(json_bytes(request), kind) as usage:
        if pre_send:
            api = api.with_options(max_retries=0)
            pre_send()
        result = api.responses.create(**request)
        if result.usage:
            usage.update(input_tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens)
        return result


def chat(context, history, question, search, *, settings, working=None, renew=None):
    if settings.get("provider") == "codex":
        return codex_chat(context, history, question, search, settings.get("codex_model"), working, renew)
    instruction = prompt("tutor/instructions")
    api = client(settings)
    wrapper = prompt("providers/openai-context") + " "
    traces, sources = [], {}
    tools = tool_definitions() + [{"type":"web_search"}]
    continuation = []
    budget = working.budget if working else None
    if working:
        instruction += "\n\n" + prompt("tutor/working-context")
    memory_instruction = instruction + ("\n\n" + prompt("tutor/learner-memory") if working and working.memories else "")

    def request(ctx, recent, step):
        messages = [{"role": "developer", "content": wrapper + json.dumps(ctx, ensure_ascii=False)}]
        messages.extend({"role": m["role"], "content": m["text"]} for m in recent)
        messages.append({"role": "user", "content": question})
        instructions = memory_instruction if "learner_memories" in ctx else instruction
        result = dict(model=MODEL, instructions=instructions, input=messages + continuation, tools=tools, store=False,
                      tool_choice={"type": "web_search"} if search and step == 0 else "auto")
        if working:
            result["max_output_tokens"] = 4096
        return result

    if working:
        summary_instruction = prompt("tutor/summary")
        summary_format = {"type": "json_schema", "name": "Summary", "strict": True,
                          "schema": providers.to_strict_json_schema(Summary)}

        def summary_request(prefix):
            return dict(model=MODEL, instructions=summary_instruction, input=json.dumps(prefix, ensure_ascii=False),
                        store=False, max_output_tokens=4096, text={"format": summary_format})

        def summarize(prefix):
            try:
                result = openai_call(api, summary_request(prefix), budget, renew, "summary")
                return Summary.model_validate_json(result.output_text).model_dump()
            except APIError as exc:
                raise ValueError("Summary provider unavailable") from exc

        working.compact(lambda ctx, recent: json_bytes(request(ctx, recent, 0)) <= budget.input_limit,
                        lambda prefix: json_bytes(summary_request(prefix)) <= budget.input_limit, summarize)
    try:
        for step in range(6):
            if working:
                context, history = working.for_provider(
                    lambda ctx, recent: json_bytes(request(ctx, recent, step)) <= budget.input_limit)
            guard = working.verify_current if working and working.sent else None
            result = openai_call(api, request(context, history, step), budget, renew, pre_send=guard)
            continuation.extend(result.output)
            calls = []
            for item in result.output:
                if item.type == "web_search_call" and item.status != "completed":
                    raise HTTPException(502, tr("Tra cứu web thất bại. Hãy thử lại.", "Web search failed. Please try again."))
                if item.type == "function_call":
                    calls.append(item)
                if item.type == "message":
                    for part in item.content:
                        for note in getattr(part, "annotations", []):
                            if note.type == "url_citation" and note.url.startswith(("https://","http://")):
                                sources[note.url] = dict(url=note.url,title=note.title,start=note.start_index,end=note.end_index)
            if not calls:
                if not result.output_text or (search and not sources):
                    raise HTTPException(502, tr("Chưa nhận được câu trả lời hoặc nguồn yêu cầu. Hãy thử lại.", "The answer or requested sources are missing. Please try again."))
                return dict(role="assistant", text=result.output_text, sources=list(sources.values()), traces=traces)
            for call in calls:
                trace, output = tool_output(call.name, call.arguments, working is not None)
                if trace:
                    traces.append(trace)
                continuation.append(dict(type="function_call_output", call_id=call.call_id, output=json.dumps(output)))
    except APIError as exc:
        raise HTTPException(502, tr("Không kết nối được OpenAI hoặc model chưa hỗ trợ công cụ. Hãy thử lại.", "Could not connect to OpenAI or use tools with this model. Please try again.")) from exc
    raise HTTPException(502, tr("Đã đạt giới hạn lượt gọi công cụ. Hãy thu hẹp câu hỏi.", "The tool call limit was reached. Try a more specific question."))

