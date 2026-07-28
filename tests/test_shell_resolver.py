import os, subprocess, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INIT = REPO / "bin" / "continuity-shell-init.sh"

def run_zsh(script, cwd):
    full = f'source "{INIT}"\n{script}'
    return subprocess.run(["/bin/zsh", "-c", full], cwd=cwd,
                          capture_output=True, text=True)

class TestResolver(unittest.TestCase):
    def test_finds_nearest_marker_walking_up(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "proj"; (root / "sub" / "deep").mkdir(parents=True)
            ac = root / ".ai-continuity"; ac.mkdir()
            (ac / "continuity.conf").write_text("AI_CONTINUITY_CONVERSATION=proj-live\n")
            r = run_zsh("_ai_continuity_conversation", str(root / "sub" / "deep"))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), "proj-live")

    def test_inactive_outside_any_project(self):
        with tempfile.TemporaryDirectory() as d:
            r = run_zsh("_ai_continuity_conversation", d)
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(r.stdout.strip(), "")

    def test_resolver_does_not_execute_marker_content(self):
        # The resolver must parse continuity.conf, never source it: a value
        # containing backticks or command substitution must not execute.
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d) / "proj"
            ac = proj / ".ai-continuity"; ac.mkdir(parents=True)
            sentinel = proj / "pwned"
            (ac / "continuity.conf").write_text(
                f'AI_CONTINUITY_CONVERSATION=`touch {sentinel}`\n')
            r = run_zsh("_ai_continuity_conversation", str(proj))
            self.assertFalse(sentinel.exists(),
                              "marker content must not be executed")

    def test_resolver_does_not_execute_command_substitution(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d) / "proj2"
            ac = proj / ".ai-continuity"; ac.mkdir(parents=True)
            sentinel = proj / "pwned2"
            (ac / "continuity.conf").write_text(
                f'AI_CONTINUITY_CONVERSATION=$(touch {sentinel})\n')
            r = run_zsh("_ai_continuity_conversation", str(proj))
            self.assertFalse(sentinel.exists(),
                              "marker content must not be executed")

if __name__ == "__main__":
    unittest.main()
