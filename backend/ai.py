from .language import tr
import json
import os
from openai import OpenAI, APIError
from fastapi import HTTPException
from typing import Literal
from pydantic import BaseModel, ValidationError
from . import providers
from .prompt_files import prompt
from .models import Motion
from .physics import calculate, motion

MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")


def client(settings):
    key = providers.api_key(settings)
    if not key:
        raise HTTPException(503, tr("Mở Cài đặt để nhập API key, chọn Codex CLI hoặc cấu hình OPENAI_API_KEY.", "Open Settings to enter an API key or select Codex CLI. You can also set OPENAI_API_KEY."))
    return OpenAI(api_key=key, timeout=90, max_retries=1)


def structured(schema, instructions, context, *, settings):
    if settings.get("provider") == "codex":
        return providers.codex_result(schema,instructions,context,model=settings.get("codex_model"))
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


def codex_chat(context, history, question, search, model):
    data = dict(lesson=context,history=history,question=question,tools=tool_definitions(),results=[])
    instruction = prompt("tutor/instructions", "tutor/codex-tools")
    traces, sources = [], {}
    searched = False
    for _ in range(6):
        data["search_enabled"] = search and not searched
        step = providers.codex_result(TutorStep,instruction,data,search=data["search_enabled"],model=model)
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
        try:
            args = json.loads(step["arguments_json"])
            output = TOOLS[action][1](args)
            traces.append(dict(tool=action,inputs=args,output=output))
        except (KeyError, TypeError, ValueError, ArithmeticError, SyntaxError) as exc:
            output = {"error":str(exc)}
        data["results"].append(dict(action=action,output=output,sources=list(sources.values())))
    raise HTTPException(502,tr("Đã đạt giới hạn lượt gọi công cụ. Hãy thu hẹp câu hỏi.", "The tool call limit was reached. Try a more specific question."))


def chat(context, history, question, search, *, settings):
    if settings.get("provider") == "codex":
        return codex_chat(context,history,question,search,settings.get("codex_model"))
    instruction = prompt("tutor/instructions")
    api = client(settings)
    messages = [{"role":"developer", "content":prompt("providers/openai-context") + " " + json.dumps(context, ensure_ascii=False)}]
    messages.extend({"role":m["role"], "content":m["text"]} for m in history)
    messages.append({"role":"user","content":question})
    traces, sources = [], {}
    tools = tool_definitions() + [{"type":"web_search"}]
    try:
        for step in range(6):
            result = api.responses.create(model=MODEL, instructions=instruction, input=messages, tools=tools, store=False,
                                          tool_choice={"type":"web_search"} if search and step == 0 else "auto")
            messages.extend(result.output)
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
                try:
                    args = json.loads(call.arguments)
                    output = TOOLS[call.name][1](args)
                    traces.append(dict(tool=call.name, inputs=args, output=output))
                except (KeyError, ValueError, ArithmeticError, SyntaxError) as exc:
                    output = {"error":str(exc)}
                messages.append(dict(type="function_call_output",call_id=call.call_id,output=json.dumps(output)))
    except APIError as exc:
        raise HTTPException(502, tr("Không kết nối được OpenAI hoặc model chưa hỗ trợ công cụ. Hãy thử lại.", "Could not connect to OpenAI or use tools with this model. Please try again.")) from exc
    raise HTTPException(502, tr("Đã đạt giới hạn lượt gọi công cụ. Hãy thu hẹp câu hỏi.", "The tool call limit was reached. Try a more specific question."))

