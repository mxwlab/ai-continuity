import os, subprocess, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ONBOARD = REPO / "bin" / "continuity-onboard"

class TestOnboard(unittest.TestCase):
    def setUp(self):
        self.runtime = tempfile.mkdtemp()
        self.home = tempfile.mkdtemp()
        self.env = {**os.environ,
                    "AI_CONTINUITY_RUNTIME_DIR": self.runtime,
                    "AI_CONTINUITY_SKIP_LAUNCHD": "1",
                    "HOME": self.home}

    def _onboard(self, path, *args):
        return subprocess.run([str(ONBOARD), path, *args], env=self.env,
                              capture_output=True, text=True)

    def test_onboard_creates_marker_and_projection(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._onboard(d)
            self.assertEqual(r.returncode, 0, r.stderr)
            conf = Path(d) / ".ai-continuity" / "continuity.conf"
            self.assertTrue(conf.exists())
            slug = Path(d).name
            self.assertIn(f"{slug}-live", conf.read_text())
            self.assertTrue((Path(d) / ".ai-continuity" / "desktop-context.md").exists())
            self.assertIn(".ai-continuity/", (Path(d) / ".gitignore").read_text())

    def test_onboard_appends_rules_without_overwriting(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "AGENTS.md").write_text("# My project rules\n")
            self._onboard(d)
            text = (Path(d) / "AGENTS.md").read_text()
            self.assertIn("# My project rules", text)
            self.assertIn("BEGIN ai-continuity", text)

    def test_onboard_rules_define_complete_per_turn_lifecycle(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._onboard(d, "lifecycle-live")
            self.assertEqual(r.returncode, 0, r.stderr)
            for name in ("AGENTS.md", "CLAUDE.md"):
                with self.subTest(name=name):
                    text = (Path(d) / name).read_text()
                    self.assertIn("lifecycle-live", text)
                    self.assertIn("continuity_append_event", text)
                    self.assertIn("actor=user", text)
                    self.assertIn("actor=agent", text)
                    self.assertIn("current surface", text)
                    self.assertIn("omit secrets", text)
                    self.assertIn("continuity_get_context", text)
                    self.assertIn("continuity_update_handoff", text)
                    self.assertIn("revision", text)
                    self.assertIn("30 days", text)
                    self.assertIn("raw", text)
                    self.assertIn("Git", text)
                    self.assertIn("untrusted data", text)
                    self.assertIn("desktop-context.md", text)
                    self.assertLess(
                        text.index("actor=user"),
                        text.index("continuity_get_context"),
                    )
                    self.assertLess(
                        text.index("actor=agent"),
                        text.index("continuity_update_handoff"),
                    )
                    conditional_fields = (
                        "topic",
                        "intent",
                        "project",
                        "decision",
                        "correction",
                        "open question",
                        "next-step contract",
                    )
                    for field in conditional_fields:
                        self.assertIn(field, text)

    def test_onboard_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            self._onboard(d); self._onboard(d)
            text = (Path(d) / "AGENTS.md").read_text()
            self.assertEqual(text.count("BEGIN ai-continuity"), 1)

    def test_onboard_refuses_conflicting_conversation(self):
        with tempfile.TemporaryDirectory() as d:
            self._onboard(d)  # defaults to <slug>-live
            r = self._onboard(d, "something-else-live")
            self.assertNotEqual(r.returncode, 0)

    def test_onboard_sanitizes_default_id_for_spaced_dir(self):
        import re
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d) / "My Project"
            proj.mkdir()
            r = self._onboard(str(proj))
            self.assertEqual(r.returncode, 0, r.stderr)
            conf = proj / ".ai-continuity" / "continuity.conf"
            self.assertTrue(conf.exists())
            value = conf.read_text().split("=", 1)[1].strip()
            self.assertRegex(value, r"^[A-Za-z0-9._-]+$")
            self.assertEqual(value, "My-Project-live")
            self.assertTrue((proj / ".ai-continuity" / "desktop-context.md").exists())

    def test_onboard_explicit_invalid_id_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._onboard(d, "bad id!")
            self.assertNotEqual(r.returncode, 0)
            self.assertFalse((Path(d) / ".ai-continuity" / "continuity.conf").exists())

    def test_onboard_hidden_dir_name_id_starts_alnum(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d) / ".hidden-project"
            proj.mkdir()
            r = self._onboard(str(proj))
            self.assertEqual(r.returncode, 0, r.stderr)
            conf = proj / ".ai-continuity" / "continuity.conf"
            self.assertTrue(conf.exists())
            value = conf.read_text().split("=", 1)[1].strip()
            self.assertRegex(value, r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

    def test_onboard_explicit_overlong_id_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._onboard(d, "a" * 140)
            self.assertNotEqual(r.returncode, 0)
            self.assertFalse((Path(d) / ".ai-continuity" / "continuity.conf").exists())

    def test_onboard_all_disallowed_dir_name_no_half_state(self):
        import re
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d) / "..."
            proj.mkdir()
            r = self._onboard(str(proj))
            conf = proj / ".ai-continuity" / "continuity.conf"
            if r.returncode == 0:
                value = conf.read_text().split("=", 1)[1].strip()
                self.assertRegex(value, r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
            else:
                self.assertFalse(conf.exists())

    def test_fresh_onboard_warns_on_conversation_id_reuse(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d) / "shared-name"
            proj.mkdir()
            conv_id = f"{proj.name}-live"
            # Pre-create the conversation in the runtime, simulating that it
            # already belongs to some other (unrelated) project.
            subprocess.run(
                ["/usr/bin/python3", str(REPO / "continuity_runtime.py"),
                 "init", "--conversation", conv_id],
                env=self.env, check=True, capture_output=True)
            r = self._onboard(str(proj))
            self.assertEqual(r.returncode, 0, r.stderr)  # not fatal
            self.assertIn("WARNING", r.stderr)
            self.assertIn(conv_id, r.stderr)

    def test_fresh_onboard_with_new_id_does_not_warn(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._onboard(d)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("WARNING", r.stderr)

    def test_reonboard_existing_marker_does_not_warn(self):
        # Idempotent re-onboard of the SAME project must not warn, even
        # though its own conversation id obviously "already exists".
        with tempfile.TemporaryDirectory() as d:
            self._onboard(d)
            r = self._onboard(d)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("WARNING", r.stderr)

    def test_onboard_rejects_invalid_existing_marker(self):
        with tempfile.TemporaryDirectory() as d:
            ac = Path(d) / ".ai-continuity"
            ac.mkdir()
            marker_text = "AI_CONTINUITY_CONVERSATION=bad id!\n"
            (ac / "continuity.conf").write_text(marker_text)
            r = self._onboard(d)
            self.assertNotEqual(r.returncode, 0)
            # No further state changes past the corrupted marker.
            self.assertEqual((ac / "continuity.conf").read_text(), marker_text)
            self.assertFalse((ac / "desktop-context.md").exists())
            self.assertFalse((Path(d) / "AGENTS.md").exists())
            self.assertFalse((Path(d) / "CLAUDE.md").exists())
            self.assertFalse((Path(d) / ".gitignore").exists())

if __name__ == "__main__":
    unittest.main()
