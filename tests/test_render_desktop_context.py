import os, subprocess, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "bin" / "render-desktop-context"

class TestRender(unittest.TestCase):
    def setUp(self):
        self.runtime = tempfile.mkdtemp()
        self.env = {**os.environ, "AI_CONTINUITY_RUNTIME_DIR": self.runtime}

    def _init(self, conv):
        subprocess.run(["/usr/bin/python3", str(REPO / "continuity_runtime.py"),
                        "init", "--conversation", conv],
                       env=self.env, check=True, capture_output=True)

    def test_render_uses_project_marker(self):
        with tempfile.TemporaryDirectory() as d:
            self._init("proj-a-live")
            conf = Path(d) / ".ai-continuity"; conf.mkdir()
            (conf / "continuity.conf").write_text("AI_CONTINUITY_CONVERSATION=proj-a-live\n")
            r = subprocess.run([str(SCRIPT), d], env=self.env,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = Path(d) / ".ai-continuity" / "desktop-context.md"
            self.assertTrue(out.exists())
            self.assertEqual(oct(out.stat().st_mode)[-3:], "600")

    def test_render_without_marker_fails(self):
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([str(SCRIPT), d], env=self.env,
                               capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)

    def test_render_uses_python3_from_path(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            project = root / "project"
            conf = project / ".ai-continuity"
            conf.mkdir(parents=True)
            (conf / "continuity.conf").write_text(
                "AI_CONTINUITY_CONVERSATION=path-python-live\n"
            )
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_python = fake_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n" "$*" > "$PYTHON_LOG"\n'
                'printf "rendered by PATH python\\n"\n'
            )
            fake_python.chmod(0o755)
            python_log = root / "python.log"
            env = {
                **self.env,
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                "PYTHON_LOG": str(python_log),
            }
            result = subprocess.run(
                [str(SCRIPT), str(project)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "context_prompt.py --conversation path-python-live",
                python_log.read_text(),
            )
            self.assertEqual(
                (conf / "desktop-context.md").read_text(),
                "rendered by PATH python\n",
            )

    def test_render_honors_launchd_resolved_python(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            project = root / "project"
            conf = project / ".ai-continuity"
            conf.mkdir(parents=True)
            (conf / "continuity.conf").write_text(
                "AI_CONTINUITY_CONVERSATION=resolved-python-live\n"
            )
            fake_python = root / "resolved-python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n" "$*" > "$PYTHON_LOG"\n'
                'printf "rendered by resolved python\\n"\n'
            )
            fake_python.chmod(0o755)
            python_log = root / "python.log"
            env = {
                **self.env,
                "AI_CONTINUITY_PYTHON": str(fake_python),
                "PYTHON_LOG": str(python_log),
            }
            result = subprocess.run(
                [str(SCRIPT), str(project)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "context_prompt.py --conversation resolved-python-live",
                python_log.read_text(),
            )
            self.assertEqual(
                (conf / "desktop-context.md").read_text(),
                "rendered by resolved python\n",
            )

if __name__ == "__main__":
    unittest.main()
