import os, subprocess, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ONBOARD = REPO / "bin" / "continuity-onboard"
OFFBOARD = REPO / "bin" / "continuity-offboard"

class TestOffboard(unittest.TestCase):
    def setUp(self):
        self.runtime = tempfile.mkdtemp()
        self.home = tempfile.mkdtemp()
        self.env = {**os.environ,
                    "AI_CONTINUITY_RUNTIME_DIR": self.runtime,
                    "AI_CONTINUITY_SKIP_LAUNCHD": "1",
                    "HOME": self.home}

    def test_offboard_removes_marker_and_rules(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "AGENTS.md").write_text("# Keep me\n")
            subprocess.run([str(ONBOARD), d], env=self.env, check=True, capture_output=True)
            r = subprocess.run([str(OFFBOARD), d], env=self.env,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse((Path(d) / ".ai-continuity" / "continuity.conf").exists())
            text = (Path(d) / "AGENTS.md").read_text()
            self.assertIn("# Keep me", text)
            self.assertNotIn("BEGIN ai-continuity", text)

    def test_offboard_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run([str(ONBOARD), d], env=self.env, check=True, capture_output=True)
            subprocess.run([str(OFFBOARD), d], env=self.env, check=True, capture_output=True)
            r = subprocess.run([str(OFFBOARD), d], env=self.env,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_offboard_cycles_are_stable(self):
        with tempfile.TemporaryDirectory() as d:
            agents = Path(d) / "AGENTS.md"
            agents.write_text("# Keep me\n")
            after_cycle1 = None
            for cycle in range(3):
                subprocess.run([str(ONBOARD), d], env=self.env, check=True, capture_output=True)
                subprocess.run([str(OFFBOARD), d], env=self.env, check=True, capture_output=True)
                content = agents.read_text()
                if cycle == 0:
                    after_cycle1 = content
            self.assertIn("# Keep me", content)
            self.assertNotIn("BEGIN ai-continuity", content)
            self.assertEqual(content, after_cycle1,
                             "offboard cycles must be byte-stable (no blank-line growth)")

    def test_offboard_preserves_unrelated_blank_lines(self):
        with tempfile.TemporaryDirectory() as d:
            agents = Path(d) / "AGENTS.md"
            agents.write_text("# A\n\n\n## B\n")
            subprocess.run([str(ONBOARD), d], env=self.env, check=True, capture_output=True)
            subprocess.run([str(OFFBOARD), d], env=self.env, check=True, capture_output=True)
            content = agents.read_text()
            self.assertNotIn("BEGIN ai-continuity", content)
            self.assertIn("# A\n\n\n## B\n", content,
                          "unrelated double blank line must be preserved verbatim")
            self.assertEqual(content, "# A\n\n\n## B\n")

    def _launchd_label(self, project):
        script = (
            f'RUNTIME_PROJECT="{REPO}"; '
            f'. "{REPO / "bin" / "lib" / "continuity-common.sh"}"; '
            f'continuity_launchd_label "{project}"'
        )
        result = subprocess.run(
            ["/bin/sh", "-c", script],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_loaded_launchd_unload_failure_preserves_all_project_state(self):
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            agents = project / "AGENTS.md"
            agents.write_text("# Keep me\n")
            onboard = subprocess.run(
                [str(ONBOARD), str(project)],
                env=self.env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(onboard.returncode, 0, onboard.stderr)
            marker = project / ".ai-continuity" / "continuity.conf"
            projection = project / ".ai-continuity" / "desktop-context.md"
            before_rules = agents.read_bytes()
            before_marker = marker.read_bytes()
            before_projection = projection.read_bytes()

            label = self._launchd_label(project)
            plist = (
                Path(self.home)
                / "Library"
                / "LaunchAgents"
                / f"{label}.plist"
            )
            plist.parent.mkdir(parents=True)
            original_plist = b"existing plist\n"
            plist.write_bytes(original_plist)
            fake_bin = Path(self.home) / "bin"
            fake_bin.mkdir()
            fake_launchctl = fake_bin / "launchctl"
            fake_launchctl.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n" "$*" >> "$LAUNCHCTL_LOG"\n'
                'case "$1" in\n'
                "  list) exit 0 ;;\n"
                "  unload) exit 42 ;;\n"
                "  *) exit 0 ;;\n"
                "esac\n"
            )
            fake_launchctl.chmod(0o755)
            launchctl_log = Path(self.home) / "launchctl.log"
            env = {
                **self.env,
                "AI_CONTINUITY_SKIP_LAUNCHD": "0",
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                "LAUNCHCTL_LOG": str(launchctl_log),
            }
            result = subprocess.run(
                [str(OFFBOARD), str(project)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unload", (result.stdout + result.stderr).lower())
            self.assertEqual(plist.read_bytes(), original_plist)
            self.assertEqual(marker.read_bytes(), before_marker)
            self.assertEqual(projection.read_bytes(), before_projection)
            self.assertEqual(agents.read_bytes(), before_rules)
            self.assertEqual(
                launchctl_log.read_text().splitlines(),
                [f"list {label}", f"unload {plist}"],
            )

    def test_not_loaded_launchd_is_removed_without_unload(self):
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            onboard = subprocess.run(
                [str(ONBOARD), str(project)],
                env=self.env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(onboard.returncode, 0, onboard.stderr)
            label = self._launchd_label(project)
            plist = (
                Path(self.home)
                / "Library"
                / "LaunchAgents"
                / f"{label}.plist"
            )
            plist.parent.mkdir(parents=True)
            plist.write_text("stale plist\n")
            fake_bin = Path(self.home) / "bin"
            fake_bin.mkdir()
            fake_launchctl = fake_bin / "launchctl"
            fake_launchctl.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n" "$*" >> "$LAUNCHCTL_LOG"\n'
                'case "$1" in list) exit 1 ;; *) exit 0 ;; esac\n'
            )
            fake_launchctl.chmod(0o755)
            launchctl_log = Path(self.home) / "launchctl.log"
            env = {
                **self.env,
                "AI_CONTINUITY_SKIP_LAUNCHD": "0",
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                "LAUNCHCTL_LOG": str(launchctl_log),
            }
            result = subprocess.run(
                [str(OFFBOARD), str(project)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(plist.exists())
            self.assertFalse(
                (project / ".ai-continuity" / "continuity.conf").exists()
            )
            self.assertEqual(
                launchctl_log.read_text().splitlines(),
                [f"list {label}"],
            )
            second = subprocess.run(
                [str(OFFBOARD), str(project)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(
                launchctl_log.read_text().splitlines(),
                [f"list {label}"],
            )

    def test_corrupt_rules_fail_before_launchd_or_project_state_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            onboard = subprocess.run(
                [str(ONBOARD), str(project)],
                env=self.env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(onboard.returncode, 0, onboard.stderr)
            agents = project / "AGENTS.md"
            agents.write_text(
                agents.read_text().replace(
                    "<!-- END ai-continuity -->",
                    "",
                )
            )
            marker = project / ".ai-continuity" / "continuity.conf"
            projection = project / ".ai-continuity" / "desktop-context.md"
            before_agents = agents.read_bytes()
            before_claude = (project / "CLAUDE.md").read_bytes()
            before_marker = marker.read_bytes()
            before_projection = projection.read_bytes()

            label = self._launchd_label(project)
            plist = (
                Path(self.home)
                / "Library"
                / "LaunchAgents"
                / f"{label}.plist"
            )
            plist.parent.mkdir(parents=True)
            original_plist = b"existing plist\n"
            plist.write_bytes(original_plist)
            fake_bin = Path(self.home) / "bin"
            fake_bin.mkdir()
            fake_launchctl = fake_bin / "launchctl"
            fake_launchctl.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n" "$*" >> "$LAUNCHCTL_LOG"\n'
                "exit 1\n"
            )
            fake_launchctl.chmod(0o755)
            launchctl_log = Path(self.home) / "launchctl.log"
            env = {
                **self.env,
                "AI_CONTINUITY_SKIP_LAUNCHD": "0",
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                "LAUNCHCTL_LOG": str(launchctl_log),
            }
            result = subprocess.run(
                [str(OFFBOARD), str(project)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("marker", (result.stdout + result.stderr).lower())
            self.assertEqual(agents.read_bytes(), before_agents)
            self.assertEqual(
                (project / "CLAUDE.md").read_bytes(),
                before_claude,
            )
            self.assertEqual(marker.read_bytes(), before_marker)
            self.assertEqual(projection.read_bytes(), before_projection)
            self.assertEqual(plist.read_bytes(), original_plist)
            self.assertFalse(
                launchctl_log.exists(),
                "rules must be preflighted before touching launchd",
            )

if __name__ == "__main__":
    unittest.main()
