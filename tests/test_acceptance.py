import os
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import continuity_runtime as runtime


class AcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_root = os.environ.get("AI_CONTINUITY_RUNTIME_DIR")
        os.environ["AI_CONTINUITY_RUNTIME_DIR"] = self.temp_dir.name

    def tearDown(self):
        if self.old_root is None:
            os.environ.pop("AI_CONTINUITY_RUNTIME_DIR", None)
        else:
            os.environ["AI_CONTINUITY_RUNTIME_DIR"] = self.old_root
        self.temp_dir.cleanup()

    def test_ac01_claude_to_codex_handoff(self):
        runtime.init_conversation("handoff")
        user_turn = runtime.append_event("handoff", "user", "claude-code", "message", "下一步怎么验证？", "project-a")
        runtime.append_event("handoff", "agent", "claude-code", "message", "先写验收测试。", "project-a")
        runtime.update_handoff("handoff", 0, {
            "active_project": "project-a",
            "current_topic": "验收测试",
            "open_questions": ["如何验证 Claude 到 Codex 的交接？"],
            "next_response_contract": "直接给出可执行测试，不要求用户复述。",
        }, "claude-code", [user_turn["turn_id"]])
        bundle = runtime.context_bundle("handoff", 8)
        self.assertEqual(bundle["handoff"]["current_topic"], "验收测试")
        self.assertIn("不要求用户复述", bundle["handoff"]["next_response_contract"])

    def test_ac02_project_isolation(self):
        runtime.init_conversation("isolation")
        runtime.append_event("isolation", "user", "codex", "message", "A 的机密", "project-a")
        runtime.append_event("isolation", "user", "codex", "message", "全局偏好", None)
        runtime.append_event("isolation", "user", "codex", "message", "B 的内容", "project-b")
        runtime.update_handoff("isolation", 0, {"active_project": "project-a"}, "codex")
        bundle = runtime.context_bundle("isolation", 8)
        self.assertEqual([event["content"] for event in bundle["recent_events"]], ["A 的机密", "全局偏好"])

    def test_ac03_explicit_project_switch(self):
        runtime.init_conversation("switch")
        runtime.append_event("switch", "user", "codex", "message", "A work", "project-a")
        runtime.append_event("switch", "user", "codex", "message", "B work", "project-b")
        runtime.update_handoff("switch", 0, {"active_project": "project-a"}, "codex")
        switched = runtime.update_handoff("switch", 1, {"active_project": "project-b"}, "claude-code")
        bundle = runtime.context_bundle("switch", 8)
        self.assertEqual(switched["active_project"], "project-b")
        self.assertEqual([event["content"] for event in bundle["recent_events"]], ["B work"])

    def test_ac04_correction_is_traceable(self):
        runtime.init_conversation("correction")
        old = runtime.append_event("correction", "agent", "codex", "message", "deadline Friday", "project-a")
        correction = runtime.append_event("correction", "user", "claude-code", "correction", "deadline Monday", "project-a", [old["event_id"]])
        self.assertEqual(correction["provenance"]["source_event_ids"], [old["event_id"]])
        self.assertEqual(len(runtime.load_events("correction")), 2)

    def test_ac05_obsidian_link_is_exposed_once(self):
        runtime.init_conversation("links")
        path = "AI Continuity/AI Continuity｜项目主页.md"
        runtime.update_handoff("links", 0, {"obsidian_links": [path]}, "codex")
        bundle = runtime.context_bundle("links", 8)
        self.assertEqual(bundle["handoff"]["obsidian_links"], [path])

    def test_ac06_concurrent_write_is_not_silent(self):
        runtime.init_conversation("conflict")
        runtime.update_handoff("conflict", 0, {"current_topic": "first"}, "codex")
        with self.assertRaisesRegex(runtime.ContinuityError, "revision conflict"):
            runtime.update_handoff("conflict", 0, {"current_topic": "lost"}, "claude-code")


if __name__ == "__main__":
    unittest.main()
