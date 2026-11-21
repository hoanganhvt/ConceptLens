import os
import tempfile
import unittest
from unittest.mock import patch

TEMP = tempfile.TemporaryDirectory()
os.environ["STUDY_DATA"] = TEMP.name
from backend import main as app
from backend.demo import SAMPLE, ROAD
from backend.physics import calculate, grade
from backend.models import Motion, Roadmap


class Study(unittest.TestCase):
    def test_provider_routing(self):
        settings={"provider":"codex","codex_model":"test-model"}
        with patch.object(app.providers,"codex_result",return_value=ROAD) as cli:
            self.assertEqual(app.ai.structured(Roadmap,"plan",{},settings=settings),ROAD)
            self.assertIs(cli.call_args.args[0],Roadmap)
            self.assertEqual(cli.call_args.kwargs["model"],"test-model")
        steps=[dict(action="calculator",arguments_json='{"expression":"2+3"}',sources=[],text=""),
               dict(action="answer",arguments_json="{}",sources=[],text="5")]
        with patch.object(app.providers,"codex_result",side_effect=steps) as cli:
            result=app.ai.chat({},[],"2+3",False,settings=settings)
            self.assertEqual(result["traces"][0]["output"],{"result":5})
            self.assertTrue(all(call.kwargs["model"]=="test-model" for call in cli.call_args_list))
        with patch.dict(os.environ,{"OPENAI_API_KEY":"env-test-key"}):
            self.assertEqual(app.providers.api_key({}),"env-test-key")
            self.assertNotIn("OPENAI_API_KEY",app.providers.cli_environment())

    def test_tools(self):
        self.assertAlmostEqual(calculate("0.5*9.81*2**2"), 19.62)
        self.assertTrue(grade(SAMPLE["quiz"][0],"1962 cm"))
        self.assertFalse(grade(SAMPLE["quiz"][0],"19.62 s"))
        self.assertRaises(ValueError, calculate, "open('file')")
        self.assertRaises(ValueError, calculate, "4**1000")
        data = app.motion(Motion())
        self.assertAlmostEqual(data["points"][120]["s"],19.62)

    def test_course_and_conversations(self):
        with patch.object(app.ai,"structured",return_value=ROAD):
            draft=app.draft(app.Draft(subject="Vật lý",level="Mới học",goal="Cơ học",schedule="1 giờ"))
        road=app.commit(Roadmap.model_validate(draft))
        rid,tid=road["id"],road["chapters"][0]["topics"][0]["id"]
        frozen=(app.DATA/rid/"roadmap.json").read_bytes()
        with patch.object(app.ai,"structured",return_value=SAMPLE) as generate:
            doc=app.generate(rid,tid)
            self.assertEqual(doc,app.generate(rid,tid))
            generate.assert_called_once()
        note=app.note(rid,tid,app.Anchor(block="intro",start=0,end=3,quote="Nếu",version=doc["version"]))
        with patch.object(app.ai,"chat",return_value=dict(role="assistant",text="Đã hiểu",sources=[])) as chat:
            app.send(rid,tid,note["id"],app.Message(text="Câu hỏi riêng"))
            app.send(rid,tid,"main",app.Message(text="Câu hỏi chính"))
            self.assertEqual(chat.call_args.args[1],[])
            self.assertNotIn("highlight",chat.call_args.args[0])
        self.assertEqual(app.read_chat(rid,tid,note["id"])[0]["text"],"Câu hỏi riêng")
        app.quiz(rid,tid,app.Attempt(question=0,answer="1962 cm"))
        self.assertEqual((app.DATA/rid/"roadmap.json").read_bytes(),frozen)
        self.assertTrue(app.read(rid,tid)["progress"]["0"][0]["correct"])

if __name__=="__main__":
    unittest.main()

