import os, plistlib, subprocess, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INSTALL = REPO / "bin" / "continuity-install"

def run_install(home, extra_env=None):
    env = dict(os.environ)
    env.update({"AI_CONTINUITY_HOME": str(home),
                "AI_CONTINUITY_SKIP_MCP": "1",
                "AI_CONTINUITY_SKIP_LAUNCHD": "1"})
    if extra_env:
        env.update(extra_env)
    return subprocess.run([str(INSTALL)], env=env, capture_output=True, text=True)

class TestInstall(unittest.TestCase):
    def test_adds_shell_block_once_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            pristine = "# user rc\nexport FOO=1\n"
            home = Path(d); (home / ".zshrc").write_text(pristine)
            r1 = run_install(home); self.assertEqual(r1.returncode, 0, r1.stderr)
            rc = (home / ".zshrc").read_text()
            self.assertIn("continuity-shell-init.sh", rc)
            self.assertIn("export FOO=1", rc)  # never clobbers user content
            backup = home / ".zshrc.bak.continuity"
            self.assertTrue(backup.exists())
            # Backup after run 1 must equal the pristine pre-install content.
            self.assertEqual(backup.read_text(), pristine)
            r2 = run_install(home); self.assertEqual(r2.returncode, 0, r2.stderr)
            rc2 = (home / ".zshrc").read_text()
            self.assertEqual(rc2.count("continuity-shell-init.sh"), 1)  # idempotent
            # Backup after run 2 must STILL be the pristine content: a no-op
            # re-run must never clobber the user's true original.
            self.assertEqual(backup.read_text(), pristine)

    def test_creates_zshrc_if_absent(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            r = run_install(home); self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("continuity-shell-init.sh", (home / ".zshrc").read_text())

    def test_inline_marker_reference_does_not_suppress_shell_install(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            original = (
                "# user rc\n"
                "echo 'Docs mention # >>> ai-continuity >>> inline.'\n"
            )
            (home / ".zshrc").write_text(original)
            result = run_install(home)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = (home / ".zshrc").read_text()
            self.assertIn(original, text)
            self.assertIn("continuity-shell-init.sh", text)
            self.assertEqual(
                sum(
                    line == "# >>> ai-continuity >>>"
                    for line in text.splitlines()
                ),
                1,
            )

    def test_rejects_invalid_shell_marker_structures_without_mutating(self):
        begin = "# >>> ai-continuity >>>"
        end = "# <<< ai-continuity <<<"
        complete = f"{begin}\nsource /tmp/init.sh\n{end}\n"
        malformed_cases = {
            "begin_without_end": f"# user rc\n{begin}\nkeep\n",
            "end_without_begin": f"# user rc\n{end}\nkeep\n",
            "duplicate_pairs": f"# user rc\n{complete}{complete}",
            "end_before_begin": f"# user rc\n{end}\n{begin}\nkeep\n",
        }
        for name, malformed in malformed_cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                home = Path(d)
                zshrc = home / ".zshrc"
                original = malformed.encode()
                zshrc.write_bytes(original)
                result = run_install(home)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(zshrc.read_bytes(), original)
                self.assertFalse(
                    (home / ".zshrc.bak.continuity").exists()
                )

    def test_registers_claude_mcp_at_user_scope(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            fake_bin = home / "fake-bin"
            fake_bin.mkdir()
            fake_claude = fake_bin / "claude"
            fake_claude.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" >> "$CLAUDE_LOG"\n'
            )
            fake_claude.chmod(0o755)
            claude_log = home / "claude.log"
            env = {
                "AI_CONTINUITY_SKIP_MCP": "0",
                "CLAUDE_LOG": str(claude_log),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            }

            first = run_install(home, env)
            self.assertEqual(first.returncode, 0, first.stderr)
            second = run_install(home, env)
            self.assertEqual(second.returncode, 0, second.stderr)
            expected = (
                "mcp add --scope user ai-continuity -- "
                f"python3 {REPO}/continuity_mcp.py"
            )
            self.assertEqual(
                claude_log.read_text().splitlines(),
                [expected, expected],
            )

    def test_claude_mcp_add_failure_warns_but_remains_rerunnable(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            fake_bin = home / "fake-bin"
            fake_bin.mkdir()
            fake_claude = fake_bin / "claude"
            fake_claude.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" >> "$CLAUDE_LOG"\nexit 42\n'
            )
            fake_claude.chmod(0o755)
            claude_log = home / "claude.log"
            env = {
                "AI_CONTINUITY_SKIP_MCP": "0",
                "CLAUDE_LOG": str(claude_log),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            }
            first = run_install(home, env)
            second = run_install(home, env)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            for result in (first, second):
                message = (result.stdout + result.stderr).lower()
                self.assertIn("warning", message)
                self.assertIn("claude mcp", message)
                self.assertIn("user", message)
            self.assertEqual(len(claude_log.read_text().splitlines()), 2)

    def test_installs_idempotent_daily_cleanup_launchd_job(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            fake_bin = home / "fake-bin"
            fake_bin.mkdir()
            fake_launchctl = fake_bin / "launchctl"
            fake_launchctl.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" >> "$LAUNCHCTL_LOG"\n'
            )
            fake_launchctl.chmod(0o755)
            fake_python = fake_bin / "python3"
            fake_python.write_text("#!/bin/sh\nexit 0\n")
            fake_python.chmod(0o755)
            launchctl_log = home / "launchctl.log"
            data_dir = home / "continuity-data"
            env = {
                "AI_CONTINUITY_SKIP_LAUNCHD": "0",
                "AI_CONTINUITY_DATA_DIR": str(data_dir),
                "LAUNCHCTL_LOG": str(launchctl_log),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            }

            first = run_install(home, env)
            self.assertEqual(first.returncode, 0, first.stderr)
            plist = (
                home
                / "Library"
                / "LaunchAgents"
                / "com.ai-continuity.cleanup.plist"
            )
            self.assertTrue(plist.exists())
            original_plist = plist.read_text()
            self.assertIn(
                "<key>Label</key><string>com.ai-continuity.cleanup</string>",
                original_plist,
            )
            self.assertIn(
                f"<string>{REPO}/bin/cleanup-runtime</string>",
                original_plist,
            )
            self.assertIn("<key>Hour</key><integer>2</integer>", original_plist)
            self.assertIn(
                "<key>Minute</key><integer>30</integer>", original_plist
            )
            self.assertIn(str(data_dir), original_plist)
            parsed = plistlib.loads(plist.read_bytes())
            self.assertEqual(parsed["Label"], "com.ai-continuity.cleanup")
            self.assertEqual(
                parsed["ProgramArguments"],
                [str(REPO / "bin" / "cleanup-runtime")],
            )
            self.assertEqual(
                parsed["EnvironmentVariables"]["AI_CONTINUITY_DATA_DIR"],
                str(data_dir),
            )
            self.assertEqual(
                parsed["EnvironmentVariables"]["AI_CONTINUITY_PYTHON"],
                str(fake_python),
            )
            self.assertEqual(
                parsed["StartCalendarInterval"],
                {"Hour": 2, "Minute": 30},
            )
            first_calls = launchctl_log.read_text().splitlines()
            self.assertEqual(
                first_calls,
                [
                    "list com.ai-continuity.cleanup",
                    f"unload {plist}",
                    f"load {plist}",
                ],
            )

            second = run_install(home, env)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(plist.read_text(), original_plist)
            self.assertEqual(
                launchctl_log.read_text().splitlines(),
                [
                    "list com.ai-continuity.cleanup",
                    f"unload {plist}",
                    f"load {plist}",
                    "list com.ai-continuity.cleanup",
                    f"unload {plist}",
                    f"load {plist}",
                ],
            )

    def test_loaded_cleanup_job_unload_failure_keeps_existing_plist(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            plist = (
                home
                / "Library"
                / "LaunchAgents"
                / "com.ai-continuity.cleanup.plist"
            )
            plist.parent.mkdir(parents=True)
            original = "existing plist\n"
            plist.write_text(original)
            fake_bin = home / "fake-bin"
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
            launchctl_log = home / "launchctl.log"
            result = run_install(
                home,
                {
                    "AI_CONTINUITY_SKIP_LAUNCHD": "0",
                    "LAUNCHCTL_LOG": str(launchctl_log),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unload", (result.stdout + result.stderr).lower())
            self.assertEqual(plist.read_text(), original)
            self.assertEqual(
                launchctl_log.read_text().splitlines(),
                [
                    "list com.ai-continuity.cleanup",
                    f"unload {plist}",
                ],
            )
