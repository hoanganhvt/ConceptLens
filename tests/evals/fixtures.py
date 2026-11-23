from copy import deepcopy
import json
from math import isclose


CASES = {
    "direct": None,
    "conversion": "Use the calculator to convert 1962 cm to metres. Include the unit.",
    "simulation": "Use the motion tool to calculate the distance at the selected time.",
    "search-on": "Use web search for a source about acceleration due to gravity.",
    "search-off": "Explain acceleration due to gravity without sources.",
    "provider-switch": "Calculate the distance dropped from rest in two seconds at 9.81 m/s².",
    "long": "Calculate the distance dropped from rest in two seconds at 9.81 m/s².",
    "missing-provider": "What happens when the provider is unavailable?",
}
LIVE_CASES = ("direct", "conversion", "simulation", "search-on", "search-off")
OTHER = {"openai": "codex", "codex": "openai"}
SOURCE = {"url": "https://example.com/free-fall", "title": "Synthetic free-fall source"}
DISTANCE = "The object falls 19.62 m."
CONVERSION = "1962 cm equals 19.62 m."
OFF_TOPIC = "Synthetic herb garden"


def answer(text, sources=()):
    return {"action": "answer", "text": text, "arguments": {}, "sources": list(sources)}


def tool(name, **arguments):
    return {"action": name, "text": "", "arguments": arguments, "sources": []}


def seed(call, generated_lesson):
    path = "physics/free-fall" if call.language == "en" else "vat-ly/roi-tu-do"
    lesson = call("GET", f"lesson/{path}")["doc"]
    for value, expected in (("19.62 s", False), ("1962 cm", True)):
        progress = call("POST", f"quiz/{path}", question=0, answer=value)
        assert progress["0"][-1]["correct"] is expected

    def selection(acceleration, block, quote):
        playback = call(
            "POST", f"motion/{path}/0", index=120,
            params={"acceleration": acceleration, "velocity": 0, "duration": 4},
        )
        return call(
            "POST", f"notes/{path}", block=block, version=lesson["version"],
            start=0, end=len(quote.encode("utf-16-le")) // 2, quote=quote,
            snapshot={**playback["points"][120], **playback["params"]},
        )

    visual = lesson["illustrations"][0]
    primary = selection(9.81, "i0", visual["instruction"])
    sibling = selection(5, "e0", visual["explanation"])
    assert isclose(primary["snapshot"]["s"], 19.62)
    assert isclose(sibling["snapshot"]["s"], 10)
    assert call("GET", f"motion/{path}/0")["points"][120]["s"] == 10

    draft = call("POST", "drafts", subject=OFF_TOPIC, level="Beginner",
                 goal="Water indoor plants", schedule="15 minutes")
    road = call("POST", "roads", **draft)
    unrelated = f'{road["id"]}/{road["chapters"][0]["topics"][0]["id"]}'
    assert call("POST", f"lesson/{unrelated}")["intro"] == generated_lesson["intro"]
    return path, lesson, primary, sibling


def unrelated_content(road_schema, lesson_schema):
    road = {"title": OFF_TOPIC, "goal": "Water indoor plants", "chapters": [
        {"title": "Container gardening", "topics": [{"title": "Basil", "goal": "Check soil moisture"}]},
    ]}
    lesson = {
        "intro": "Check the soil before watering basil.",
        "sections": [{"title": "Soil moisture", "text": "Feel the top layer of soil before watering."}],
        "illustrations": [{
            "section": 0, "title": "Basil pot", "instruction": "Inspect the soil.",
            "explanation": "Dry soil looks lighter.", "mode": "interactive",
            "html": "<div>Soil</div>", "css": "", "js": "function render() {}",
        }],
        "quiz": [{"prompt": "What should you check?", "kind": "choice",
                  "choices": ["Soil", "Clock"], "answer": "Soil", "explanation": "Check soil moisture."}],
    }
    return {road_schema: road_schema.model_validate(road).model_dump(),
            lesson_schema: lesson_schema.model_validate(lesson).model_dump()}


def exercise(call, turn, case, provider, live, path, lesson, primary, sibling):
    main = f"chat/{path}/main"
    focus = f'chat/{path}/{primary["id"]}'
    side = f'chat/{path}/{sibling["id"]}'
    if not live:
        for branch, marker in ((main, "Main thread marker"), (focus, "Primary highlight marker"),
                               (side, "Sibling highlight marker")):
            turn(branch, marker, [answer("Marker saved.")])

    if case == "missing-provider":
        previous = call("GET", main)
        assert previous[0]["text"] == "Main thread marker"
        turn.available = False
        failed = turn(main, CASES[case], [], expected=503)
        assert failed["calls"] == []
        assert call("GET", main) == previous
        return

    if case == "direct":
        actual = turn(main, lesson["quiz"][1]["prompt"], [answer("Nine times as far.")])
    elif case == "conversion":
        actual = turn(main, CASES[case], [tool("calculator", expression="1962/100"), answer(CONVERSION)])
    elif case == "simulation":
        snapshot = primary["snapshot"]
        actual = turn(focus, CASES[case], [
            tool("simulate_motion", acceleration=snapshot["acceleration"],
                 velocity=snapshot["velocity"], duration=snapshot["t"]),
            answer(DISTANCE),
        ])
    elif case in {"search-on", "search-off"}:
        steps = [answer("Near Earth's surface, gravity accelerates objects downward at about 9.81 m/s².", [SOURCE])]
        if case == "search-off":
            steps = [tool("web_search"), *steps] if provider == "codex" else steps
        actual = turn(main, CASES[case], steps, search=case == "search-on")
    else:
        first = turn(focus, CASES[case], [tool("calculator", expression="0.5*9.81*2**2"), answer(DISTANCE)])
        if case == "provider-switch":
            turn.select(OTHER[provider])
        else:
            for index in range(20):
                turn(focus, f"Review question {index + 1}.", [answer("Review complete.")])
        actual = turn(focus, "How far did it fall in the original calculation?", [answer(DISTANCE)])
        assert first["reply"]["traces"][0]["output"] == {"result": 19.62}
        assert actual["reply"]["text"] == DISTANCE
        incoming = actual["calls"][0]["input"]
        assert DISTANCE in str(incoming)
        if case == "provider-switch":
            assert actual["calls"][0]["provider"] == OTHER[provider]
        else:
            history = incoming["context"]["history"] if provider == "codex" else incoming["messages"][1:-1]
            assert len(history) == 44

    if live:
        return
    request = str(actual["calls"][0]["input"])
    assert OFF_TOPIC not in request
    assert "Sibling highlight marker" not in request
    on_highlight = case in {"simulation", "provider-switch", "long"}
    assert ("Primary highlight marker" in request) is on_highlight
    assert ("Main thread marker" in request) is (not on_highlight)
    assert call("GET", side)[0]["text"] == "Sibling highlight marker"
    if on_highlight:
        assert primary["id"] in request and sibling["id"] not in request
        first_call = actual["calls"][0]
        incoming = first_call["input"]
        if first_call["provider"] == "codex":
            context = incoming["context"]["lesson"]
        else:
            developer_message = incoming["messages"][0]["content"]
            context = json.loads("{" + developer_message.split(" {", 1)[1])
        assert context["highlight"]["snapshot"] == primary["snapshot"]
    if case == "direct":
        assert actual["reply"]["text"] == "Nine times as far."
    if case in {"simulation", "conversion"}:
        output = actual["reply"]["traces"][0]["output"]
        assert isclose(output["s" if case == "simulation" else "result"], 19.62)
        assert actual["reply"]["text"] == (DISTANCE if case == "simulation" else CONVERSION)
        assert "19.62" in str(actual["calls"][1]["input"])
    if case.startswith("search-"):
        assert actual["reply"]["sources"][0]["url"] == SOURCE["url"]
        calls = actual["calls"]
        if provider == "codex":
            assert [call["input"]["search"] for call in calls] == (
                ["live"] if case == "search-on" else ["disabled", "live"]
            )
        else:
            assert {"type": "web_search"} in calls[0]["input"]["tools"]
            expected = {"type": "web_search"} if case == "search-on" else "auto"
            assert calls[0]["input"]["tool_choice"] == expected


def exercise_bounded(call, turn, path, lesson, primary, sibling):
    english = call.language == "en"
    focus = f'chat/{path}/{primary["id"]}'
    side = f'chat/{path}/{sibling["id"]}'
    main = f"chat/{path}/main"
    turn(side, "Sibling highlight marker", [answer("Sibling reply")])
    turn(main, "Main thread marker", [answer("Main reply")])
    opening = ("Use downward as positive for the original fall direction. How far did it fall?"
               if english else "Chọn chiều dương hướng xuống cho lần rơi ban đầu. Vật rơi được bao xa?")
    reply = DISTANCE if english else "Vật rơi được 19,62 m."
    initial = turn(focus, opening, [tool("simulate_motion", acceleration=9.81, velocity=0, duration=2),
                                    answer(reply)])
    assert isclose(initial["reply"]["traces"][0]["output"]["s"], 19.62)
    for n in range(20):
        review = "How does velocity change in the free-fall model? " if english else "Vận tốc thay đổi thế nào khi rơi tự do? "
        turn(focus, f"{n + 1}. " + review * 6, [answer("Review complete." if english else "Đã ôn tập.")])

    def followup():
        question = ("How far did it fall in the original calculation?" if english
                    else "Ở phép tính ban đầu, vật rơi được bao xa?")
        result = turn(focus, question, [answer(reply)])
        data = next(entry["input"] for entry in result["calls"] if entry["kind"] == "tutor")
        if turn.provider == "codex":
            context, history = data["context"]["lesson"], data["context"]["history"]
        else:
            context = json.loads(data["messages"][0]["content"].split(": ", 1)[1])
            history = data["messages"][1:-1]
        assert context["highlight"]["id"] == primary["id"]
        assert context["simulation"]["source"] == "highlight"
        assert context["simulation"]["values"] == primary["snapshot"]
        assert context["simulation"]["units"]["s"] == "m"
        assert context.get("older_summary", {}).get("covered_through", 0) >= 2, (
            [entry["kind"] for entry in turn.calls], context.keys(), len(history))
        assert ("downward" if english else "hướng xuống") in context["older_summary"]["text"]
        assert len(history) < 42 and len(history) % 2 == 0
        verified = context["verified_results"][0]
        assert verified["source"] == "prior_tool" and verified["message_sequence"] == 2
        assert verified["inputs"] == {"acceleration": 9.81, "velocity": 0, "duration": 2}
        assert isclose(verified["values"]["s"], 19.62) and verified["units"]["s"] == "m"
        packed = json.dumps(data, ensure_ascii=False)
        assert "Sibling highlight marker" not in packed and "Main thread marker" not in packed
        assert sibling["id"] not in packed and "current_playback" not in packed
        assert lesson["quiz"][1]["answer"] not in packed
        assert result["reply"]["text"] == reply

    followup()
    turn.select(OTHER[turn.provider])
    followup()
    public = call("GET", focus)
    assert len(public) == 46 and public[0]["text"] == opening and public[-1]["text"] == reply
    assert sum(entry["kind"] == "summary" for entry in turn.calls) >= 2
