import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO / "install.sh"


def _write_executable(path: Path, text: str):
    path.write_text(text)
    path.chmod(0o755)


def _fake_cli(path: Path):
    _write_executable(path, "#!/bin/sh\nexit 0\n")


def _run(env, extra=None):
    full = {**os.environ, **env}
    if extra:
        full.update(extra)
    return subprocess.run(
        ["bash", str(INSTALL_SH)],
        env=full,
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestBootstrap(unittest.TestCase):
    def _base_env(self, home: Path, fake_bin: Path):
        # Real system PATH kept so git/python3/zsh resolve; fake claude/codex
        # prepended. Delegates to continuity-install with launchd skipped.
        return {
            "HOME": str(home),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "AI_CONTINUITY_REPO_URL": f"file://{REPO}",
            "AI_CONTINUITY_UNAME": "Darwin",
            "AI_CONTINUITY_SKIP_LAUNCHD": "1",
        }

    def test_rejects_non_macos(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            result = _run(
                {"HOME": str(home)},
                {"AI_CONTINUITY_UNAME": "Linux"},
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("macOS", result.stderr)
            self.assertFalse((home / ".local/share/ai-continuity").exists())

    def test_requires_a_supported_cli(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            only_bin = home / "onlybin"
            only_bin.mkdir()
            # A controlled PATH that has python3/git/zsh but NO claude/codex.
            # bash is needed to run the script, so use the real bash.
            for tool in ("python3", "git", "zsh"):
                _write_executable(only_bin / tool, "#!/bin/sh\nexit 0\n")
            _write_executable(only_bin / "bash", "#!/bin/sh\nexec /bin/bash \"$@\"\n")
            env = {
                "HOME": str(home),
                "PATH": f"{only_bin}:/bin",
                "AI_CONTINUITY_UNAME": "Darwin",
            }
            result = _run(env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Claude Code or Codex", result.stderr)

    def test_requires_python3(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            only_bin = home / "onlybin"
            only_bin.mkdir()
            for tool in ("git", "zsh", "claude"):
                _write_executable(only_bin / tool, "#!/bin/sh\nexit 0\n")
            _write_executable(only_bin / "bash", "#!/bin/sh\nexec /bin/bash \"$@\"\n")
            env = {
                "HOME": str(home),
                "PATH": f"{only_bin}:/bin",
                "AI_CONTINUITY_UNAME": "Darwin",
            }
            result = _run(env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("python3", result.stderr)

    def test_happy_path_clones_and_delegates(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            fake_bin = home / "fakebin"
            fake_bin.mkdir()
            _fake_cli(fake_bin / "claude")
            _fake_cli(fake_bin / "codex")
            result = _run(self._base_env(home, fake_bin))
            self.assertEqual(result.returncode, 0, result.stderr)
            install_dir = home / ".local/share/ai-continuity"
            self.assertTrue((install_dir / ".git").is_dir())
            self.assertTrue((install_dir / "bin/continuity-install").exists())
            # Delegation evidence: continuity-install wrote the shell block.
            self.assertIn(
                "continuity-shell-init.sh",
                (home / ".zshrc").read_text(),
            )
            self.assertIn("continuity-onboard .", result.stdout)
            self.assertIn("USAGE.zh-CN.md", result.stdout)

    def test_rerun_updates_idempotently(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            fake_bin = home / "fakebin"
            fake_bin.mkdir()
            _fake_cli(fake_bin / "claude")
            _fake_cli(fake_bin / "codex")
            env = self._base_env(home, fake_bin)
            first = _run(env)
            self.assertEqual(first.returncode, 0, first.stderr)
            second = _run(env)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertTrue(
                (home / ".local/share/ai-continuity/.git").is_dir()
            )

    def test_refuses_foreign_install_dir(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            fake_bin = home / "fakebin"
            fake_bin.mkdir()
            _fake_cli(fake_bin / "claude")
            _fake_cli(fake_bin / "codex")
            install_dir = home / ".local/share/ai-continuity"
            install_dir.mkdir(parents=True)
            (install_dir / "someone-elses-file").write_text("keep me\n")
            result = _run(self._base_env(home, fake_bin))
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((install_dir / "someone-elses-file").exists())
            self.assertFalse((install_dir / ".git").exists())

    def test_git_is_non_interactive(self):
        self.assertIn("GIT_TERMINAL_PROMPT=0", INSTALL_SH.read_text())

    def test_welcome_page_open_is_tty_only_and_can_be_disabled(self):
        source = INSTALL_SH.read_text()
        self.assertIn("AI_CONTINUITY_NO_OPEN", source)
        self.assertIn('[ -t 1 ]', source)
        self.assertIn(
            "https://ai-continuity-welcome.amber-moth-2612.chatgpt.site",
            source,
        )


if __name__ == "__main__":
    unittest.main()
