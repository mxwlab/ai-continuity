import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
INSTALL = REPO / "bin" / "continuity-install"
UNINSTALL = REPO / "bin" / "continuity-uninstall"


def _env(home):
    env = dict(os.environ)
    env.update(
        {
            "AI_CONTINUITY_HOME": str(home),
            "AI_CONTINUITY_SKIP_MCP": "1",
            "AI_CONTINUITY_SKIP_LAUNCHD": "1",
        }
    )
    return env


class TestUninstall(unittest.TestCase):
    def test_removes_shell_block_keeps_user_content(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / ".zshrc").write_text("# user rc\nexport FOO=1\n")
            subprocess.run(
                [str(INSTALL)],
                env=_env(home),
                check=True,
                capture_output=True,
                text=True,
            )
            result = subprocess.run(
                [str(UNINSTALL)],
                env=_env(home),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            rc = (home / ".zshrc").read_text()
            self.assertNotIn("continuity-shell-init.sh", rc)
            self.assertIn("export FOO=1", rc)

    def test_shell_removal_is_idempotent_and_backup_is_pre_mutation_state(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / ".zshrc").write_text("# user rc\nexport FOO=1\n")
            subprocess.run(
                [str(INSTALL)],
                env=_env(home),
                check=True,
                capture_output=True,
                text=True,
            )
            installed = (home / ".zshrc").read_text()

            first = subprocess.run(
                [str(UNINSTALL)],
                env=_env(home),
                capture_output=True,
                text=True,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            cleaned = (home / ".zshrc").read_text()
            backup = home / ".zshrc.bak.continuity"
            self.assertEqual(backup.read_text(), installed)

            second = subprocess.run(
                [str(UNINSTALL)],
                env=_env(home),
                capture_output=True,
                text=True,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual((home / ".zshrc").read_text(), cleaned)
            self.assertEqual(backup.read_text(), installed)

    def test_refuses_malformed_shell_block_without_mutating(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            malformed = (
                "# user rc\n"
                "# >>> ai-continuity >>>\n"
                "source \"/tmp/continuity-shell-init.sh\"\n"
                "export KEEP=1\n"
            )
            (home / ".zshrc").write_text(malformed)
            result = subprocess.run(
                [str(UNINSTALL)],
                env=_env(home),
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((home / ".zshrc").read_text(), malformed)
            self.assertFalse((home / ".zshrc.bak.continuity").exists())

    def test_refuses_duplicate_or_unpaired_shell_markers(self):
        complete = (
            "# >>> ai-continuity >>>\n"
            "source \"/tmp/continuity-shell-init.sh\"\n"
            "# <<< ai-continuity <<<\n"
        )
        cases = {
            "complete_then_unclosed_begin": (
                "# user rc\n" + complete + "# >>> ai-continuity >>>\nkeep\n"
            ),
            "unmatched_end_then_complete": (
                "# user rc\n# <<< ai-continuity <<<\n" + complete
            ),
            "duplicate_complete_blocks": (
                "# user rc\n" + complete + complete
            ),
        }
        for name, malformed in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                home = Path(d)
                (home / ".zshrc").write_text(malformed)
                result = subprocess.run(
                    [str(UNINSTALL)],
                    env=_env(home),
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((home / ".zshrc").read_text(), malformed)
                self.assertFalse(
                    (home / ".zshrc.bak.continuity").exists()
                )

    def test_inline_marker_references_are_ordinary_user_text(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            original = (
                "# user rc\n"
                "echo 'Docs mention # >>> ai-continuity >>> inline.'\n"
                "echo 'Docs mention # <<< ai-continuity <<< inline.'\n"
            )
            (home / ".zshrc").write_text(original)
            result = subprocess.run(
                [str(UNINSTALL)],
                env=_env(home),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((home / ".zshrc").read_text(), original)
            self.assertFalse((home / ".zshrc.bak.continuity").exists())

    def test_removes_only_own_codex_section_and_backs_up_config(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            codex_dir = home / ".codex"
            codex_dir.mkdir()
            original = (
                "[features]\n"
                "web_search = true\n"
                "\n"
                "[mcp_servers.ai-continuity]\n"
                'command = "python3"\n'
                'args = ["/tmp/continuity_mcp.py"]\n'
                "\n"
                "[mcp_servers.keep-me]\n"
                'command = "keep"\n'
            )
            config = codex_dir / "config.toml"
            config.write_text(original)
            config.chmod(0o600)

            fake_bin = home / "fake-bin"
            fake_bin.mkdir()
            fake_claude = fake_bin / "claude"
            fake_claude.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" >> "$CLAUDE_LOG"\n'
            )
            fake_claude.chmod(0o755)
            claude_log = home / "claude.log"
            env = _env(home)
            env["AI_CONTINUITY_SKIP_MCP"] = "0"
            env["CLAUDE_LOG"] = str(claude_log)
            env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

            first = subprocess.run(
                [str(UNINSTALL)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            cleaned = config.read_text()
            self.assertNotIn("[mcp_servers.ai-continuity]", cleaned)
            self.assertIn("[features]", cleaned)
            self.assertIn("[mcp_servers.keep-me]", cleaned)
            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
            backup = codex_dir / "config.toml.bak.continuity"
            self.assertEqual(backup.read_text(), original)
            self.assertEqual(
                claude_log.read_text(), "mcp remove ai-continuity\n"
            )

            second = subprocess.run(
                [str(UNINSTALL)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(config.read_text(), cleaned)
            self.assertEqual(backup.read_text(), original)

    def test_preserves_zshrc_and_codex_config_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            actual_zshrc = home / "actual-zshrc"
            actual_zshrc.write_text(
                "# user rc\n"
                "export KEEP=1\n"
                "\n"
                "# >>> ai-continuity >>>\n"
                "source \"/tmp/continuity-shell-init.sh\"\n"
                "# <<< ai-continuity <<<\n"
            )
            (home / ".zshrc").symlink_to(actual_zshrc)

            codex_dir = home / ".codex"
            codex_dir.mkdir()
            actual_codex = home / "actual-codex.toml"
            actual_codex.write_text(
                "[features]\n"
                "web_search = true\n"
                "\n"
                "[mcp_servers.ai-continuity]\n"
                'command = "python3"\n'
                'args = ["/tmp/continuity_mcp.py"]\n'
            )
            actual_codex.chmod(0o600)
            config_link = codex_dir / "config.toml"
            config_link.symlink_to(actual_codex)

            fake_bin = home / "fake-bin"
            fake_bin.mkdir()
            fake_claude = fake_bin / "claude"
            fake_claude.write_text("#!/bin/sh\nexit 0\n")
            fake_claude.chmod(0o755)
            env = _env(home)
            env["AI_CONTINUITY_SKIP_MCP"] = "0"
            env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

            result = subprocess.run(
                [str(UNINSTALL)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((home / ".zshrc").is_symlink())
            self.assertTrue(config_link.is_symlink())
            self.assertNotIn(
                "continuity-shell-init.sh", actual_zshrc.read_text()
            )
            self.assertIn("export KEEP=1", actual_zshrc.read_text())
            self.assertNotIn(
                "[mcp_servers.ai-continuity]", actual_codex.read_text()
            )
            self.assertIn("[features]", actual_codex.read_text())
            self.assertEqual(
                stat.S_IMODE(actual_codex.stat().st_mode), 0o600
            )

    def test_warns_when_claude_mcp_removal_fails(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            fake_bin = home / "fake-bin"
            fake_bin.mkdir()
            fake_claude = fake_bin / "claude"
            fake_claude.write_text("#!/bin/sh\nexit 42\n")
            fake_claude.chmod(0o755)
            env = _env(home)
            env["AI_CONTINUITY_SKIP_MCP"] = "0"
            env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
            result = subprocess.run(
                [str(UNINSTALL)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            combined = (result.stdout + result.stderr).lower()
            self.assertIn("warning", combined)
            self.assertIn("claude", combined)

    def test_skip_mcp_leaves_codex_config_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            codex_dir = home / ".codex"
            codex_dir.mkdir()
            config = codex_dir / "config.toml"
            original = (
                "[mcp_servers.ai-continuity]\n"
                'command = "python3"\n'
                'args = ["/tmp/continuity_mcp.py"]\n'
            )
            config.write_text(original)
            result = subprocess.run(
                [str(UNINSTALL)],
                env=_env(home),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(config.read_text(), original)
            self.assertFalse(
                (codex_dir / "config.toml.bak.continuity").exists()
            )

    def test_preserves_data_dir_without_purge(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            data = home / "data"
            (data / "runtime").mkdir(parents=True)
            (data / "runtime" / "keep.txt").write_text("x")
            env = _env(home)
            env["AI_CONTINUITY_DATA_DIR"] = str(data)
            subprocess.run(
                [str(UNINSTALL)],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertTrue((data / "runtime" / "keep.txt").exists())

    def test_purge_deletes_only_runtime_and_logs(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            data = home / "data"
            (data / "runtime").mkdir(parents=True)
            (data / "runtime" / "gone.txt").write_text("x")
            (data / "logs").mkdir()
            (data / "logs" / "gone.log").write_text("x")
            (data / "keep").mkdir()
            (data / "keep" / "preserved.txt").write_text("x")
            env = _env(home)
            env["AI_CONTINUITY_DATA_DIR"] = str(data)
            subprocess.run(
                [str(UNINSTALL), "--purge"],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertFalse((data / "runtime").exists())
            self.assertFalse((data / "logs").exists())
            self.assertTrue((data / "keep" / "preserved.txt").exists())
            self.assertTrue(data.exists())

    def test_purge_refuses_root_data_dir(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            env = _env(home)
            env["AI_CONTINUITY_DATA_DIR"] = "/"
            result = subprocess.run(
                [str(UNINSTALL), "--purge"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refus", (result.stdout + result.stderr).lower())

    def test_unknown_argument_fails_before_mutating(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            original = "# user rc\n# >>> ai-continuity >>>\n"
            (home / ".zshrc").write_text(original)
            result = subprocess.run(
                [str(UNINSTALL), "--everything"],
                env=_env(home),
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((home / ".zshrc").read_text(), original)

    def test_unloads_and_removes_cleanup_launchd_job(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            plist = (
                home
                / "Library"
                / "LaunchAgents"
                / "com.ai-continuity.cleanup.plist"
            )
            plist.parent.mkdir(parents=True)
            plist.write_text("test plist\n")
            fake_bin = home / "fake-bin"
            fake_bin.mkdir()
            fake_launchctl = fake_bin / "launchctl"
            fake_launchctl.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" >> "$LAUNCHCTL_LOG"\n'
            )
            fake_launchctl.chmod(0o755)
            launchctl_log = home / "launchctl.log"
            env = _env(home)
            env.update(
                {
                    "AI_CONTINUITY_SKIP_LAUNCHD": "0",
                    "LAUNCHCTL_LOG": str(launchctl_log),
                    "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
                }
            )
            result = subprocess.run(
                [str(UNINSTALL)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(plist.exists())
            self.assertEqual(
                launchctl_log.read_text(),
                (
                    "list com.ai-continuity.cleanup\n"
                    f"unload {plist}\n"
                ),
            )

    def test_loaded_cleanup_unload_failure_keeps_plist_for_retry(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            plist = (
                home
                / "Library"
                / "LaunchAgents"
                / "com.ai-continuity.cleanup.plist"
            )
            plist.parent.mkdir(parents=True)
            original = "test plist\n"
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
                "esac\n"
            )
            fake_launchctl.chmod(0o755)
            launchctl_log = home / "launchctl.log"
            env = _env(home)
            env.update(
                {
                    "AI_CONTINUITY_SKIP_LAUNCHD": "0",
                    "LAUNCHCTL_LOG": str(launchctl_log),
                    "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
                }
            )
            result = subprocess.run(
                [str(UNINSTALL)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unload", (result.stdout + result.stderr).lower())
            self.assertTrue(plist.exists())
            self.assertEqual(plist.read_text(), original)
            self.assertEqual(
                launchctl_log.read_text().splitlines(),
                [
                    "list com.ai-continuity.cleanup",
                    f"unload {plist}",
                ],
            )

    def test_not_loaded_cleanup_job_removes_plist_without_unload(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            plist = (
                home
                / "Library"
                / "LaunchAgents"
                / "com.ai-continuity.cleanup.plist"
            )
            plist.parent.mkdir(parents=True)
            plist.write_text("test plist\n")
            fake_bin = home / "fake-bin"
            fake_bin.mkdir()
            fake_launchctl = fake_bin / "launchctl"
            fake_launchctl.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n" "$*" >> "$LAUNCHCTL_LOG"\n'
                'case "$1" in\n'
                "  list) exit 1 ;;\n"
                "  *) exit 99 ;;\n"
                "esac\n"
            )
            fake_launchctl.chmod(0o755)
            launchctl_log = home / "launchctl.log"
            env = _env(home)
            env.update(
                {
                    "AI_CONTINUITY_SKIP_LAUNCHD": "0",
                    "LAUNCHCTL_LOG": str(launchctl_log),
                    "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
                }
            )
            result = subprocess.run(
                [str(UNINSTALL)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(plist.exists())
            self.assertEqual(
                launchctl_log.read_text(),
                "list com.ai-continuity.cleanup\n",
            )

    def test_skip_launchd_leaves_cleanup_job_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            plist = (
                home
                / "Library"
                / "LaunchAgents"
                / "com.ai-continuity.cleanup.plist"
            )
            plist.parent.mkdir(parents=True)
            plist.write_text("test plist\n")
            result = subprocess.run(
                [str(UNINSTALL)],
                env=_env(home),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(plist.exists())
