import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
WRAPPERS = [
    "bin/claude-continuity",
    "bin/codex-continuity",
    "bin/cleanup-runtime",
    "bin/continuity-install",
    "bin/continuity-offboard",
    "bin/continuity-onboard",
    "bin/continuity-shell-init.sh",
    "bin/continuity-uninstall",
    "bin/lib/continuity-common.sh",
    "bin/render-desktop-context",
]


def _write_executable(path: Path, text: str):
    path.write_text(text)
    path.chmod(0o755)


def _fake_cli(path: Path):
    _write_executable(
        path,
        "#!/bin/sh\n"
        'printf "call\\n" >> "$CLI_LOG"\n'
        'for arg in "$@"; do printf "<%s>\\n" "$arg" >> "$CLI_LOG"; done\n'
        'exit "${CLI_EXIT:-0}"\n',
    )


def _fake_python(path: Path):
    _write_executable(
        path,
        "#!/bin/sh\n"
        'for arg in "$@"; do printf "<%s>\\n" "$arg" >> "$PYTHON_LOG"; done\n'
        'test "${PYTHON_EXIT:-0}" -eq 0 || exit "$PYTHON_EXIT"\n'
        'case " $* " in\n'
        '  *" --json-string "*) printf \'"FAKE CONTEXT"\\n\' ;;\n'
        '  *) printf "FAKE CONTEXT\\n" ;;\n'
        "esac\n",
    )

class TestWrappers(unittest.TestCase):
    def test_no_hardcoded_user_home_paths(self):
        """Check that no wrapper contains hardcoded absolute macOS user-home paths."""
        home_prefix = "/" + "Users" + "/"
        home_pattern = re.escape(home_prefix) + r'[^"\'\s]+'
        for rel in WRAPPERS:
            text = (REPO / rel).read_text()
            self.assertIsNone(
                re.search(home_pattern, text),
                f"{rel} contains a hardcoded macOS user-home path",
            )

    def test_no_hardcoded_system_python(self):
        for rel in WRAPPERS:
            text = (REPO / rel).read_text()
            self.assertNotIn("/usr/bin/python3", text, rel)

    def test_shell_init_defines_claude_and_codex_functions(self):
        init = REPO / "bin" / "continuity-shell-init.sh"
        result = subprocess.run(
            [
                "/bin/zsh",
                "-c",
                f'source "{init}"; whence -w claude; whence -w codex',
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("claude: function", result.stdout)
        self.assertIn("codex: function", result.stdout)

    def test_shell_functions_passthrough_outside_project_without_recursion(self):
        init = REPO / "bin" / "continuity-shell-init.sh"
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            _fake_cli(fake_bin / "claude")
            _fake_cli(fake_bin / "codex")
            for cli, exit_code in (("claude", 37), ("codex", 38)):
                with self.subTest(cli=cli):
                    cli_log = root / f"{cli}.log"
                    python_log = root / f"{cli}-python.log"
                    env = {
                        **os.environ,
                        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                        "CLI_LOG": str(cli_log),
                        "CLI_EXIT": str(exit_code),
                        "PYTHON_LOG": str(python_log),
                    }
                    result = subprocess.run(
                        [
                            "/bin/zsh",
                            "-c",
                            f'source "{init}"; {cli} "plain arg" --flag',
                        ],
                        cwd=root,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    self.assertEqual(result.returncode, exit_code, result.stderr)
                    self.assertEqual(
                        cli_log.read_text().splitlines(),
                        ["call", "<plain arg>", "<--flag>"],
                    )
                    self.assertFalse(
                        python_log.exists(),
                        "outside an onboarded project must not generate context",
                    )

    def test_shell_functions_inject_context_inside_nearest_project(self):
        init = REPO / "bin" / "continuity-shell-init.sh"
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            project = root / "My Project"
            nested = project / "nested"
            marker = project / ".ai-continuity"
            nested.mkdir(parents=True)
            marker.mkdir()
            (marker / "continuity.conf").write_text(
                "AI_CONTINUITY_CONVERSATION=my-project-live\n"
            )
            fake_bin = root / "bin"
            fake_bin.mkdir()
            _fake_cli(fake_bin / "claude")
            _fake_cli(fake_bin / "codex")
            _fake_python(fake_bin / "python3")

            expected = {
                "claude": [
                    "call",
                    "<--append-system-prompt>",
                    "<FAKE CONTEXT>",
                    "<user arg>",
                ],
                "codex": [
                    "call",
                    "<-c>",
                    '<developer_instructions="FAKE CONTEXT">',
                    "<user arg>",
                ],
            }
            for cli, exit_code in (("claude", 27), ("codex", 28)):
                with self.subTest(cli=cli):
                    cli_log = root / f"{cli}.log"
                    python_log = root / f"{cli}-python.log"
                    env = {
                        **os.environ,
                        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                        "CLI_LOG": str(cli_log),
                        "CLI_EXIT": str(exit_code),
                        "PYTHON_LOG": str(python_log),
                    }
                    result = subprocess.run(
                        [
                            "/bin/zsh",
                            "-c",
                            f'source "{init}"; {cli} "user arg"',
                        ],
                        cwd=nested,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    self.assertEqual(result.returncode, exit_code, result.stderr)
                    self.assertEqual(cli_log.read_text().splitlines(), expected[cli])
                    python_args = python_log.read_text().splitlines()
                    self.assertEqual(
                        python_args.count("<--conversation>"),
                        1,
                        "one CLI call must generate context exactly once",
                    )
                    self.assertIn("<my-project-live>", python_args)
                    if cli == "codex":
                        self.assertIn("<--json-string>", python_args)
                    else:
                        self.assertNotIn("<--json-string>", python_args)

    def test_shell_functions_fail_closed_when_context_generation_fails(self):
        init = REPO / "bin" / "continuity-shell-init.sh"
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            marker = root / ".ai-continuity"
            marker.mkdir()
            (marker / "continuity.conf").write_text(
                "AI_CONTINUITY_CONVERSATION=fail-closed-live\n"
            )
            fake_bin = root / "bin"
            fake_bin.mkdir()
            _fake_cli(fake_bin / "claude")
            _fake_cli(fake_bin / "codex")
            _fake_python(fake_bin / "python3")
            for cli in ("claude", "codex"):
                with self.subTest(cli=cli):
                    cli_log = root / f"{cli}.log"
                    python_log = root / f"{cli}-python.log"
                    env = {
                        **os.environ,
                        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                        "CLI_LOG": str(cli_log),
                        "PYTHON_LOG": str(python_log),
                        "PYTHON_EXIT": "41",
                    }
                    result = subprocess.run(
                        ["/bin/zsh", "-c", f'source "{init}"; {cli} status'],
                        cwd=root,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    self.assertEqual(result.returncode, 41)
                    self.assertFalse(
                        cli_log.exists(),
                        "an onboarded project must not silently bypass continuity",
                    )

    def test_standalone_wrappers_require_explicit_conversation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            _fake_cli(fake_bin / "claude")
            _fake_cli(fake_bin / "codex")
            for wrapper in ("claude-continuity", "codex-continuity"):
                with self.subTest(wrapper=wrapper):
                    cli_log = root / f"{wrapper}.log"
                    env = {
                        key: value
                        for key, value in os.environ.items()
                        if key != "AI_CONTINUITY_CONVERSATION"
                    }
                    env.update(
                        {
                            "PATH": (
                                f"{fake_bin}{os.pathsep}{os.environ['PATH']}"
                            ),
                            "CLI_LOG": str(cli_log),
                        }
                    )
                    result = subprocess.run(
                        [str(BIN / wrapper), "--version"],
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(
                        cli_log.exists(),
                        "missing conversation must fail before launching the CLI",
                    )

    def test_standalone_wrappers_use_explicit_conversation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            _fake_cli(fake_bin / "claude")
            _fake_cli(fake_bin / "codex")
            _fake_python(fake_bin / "python3")
            for wrapper, cli in (
                ("claude-continuity", "claude"),
                ("codex-continuity", "codex"),
            ):
                with self.subTest(wrapper=wrapper):
                    cli_log = root / f"{wrapper}.log"
                    python_log = root / f"{wrapper}-python.log"
                    env = {
                        **os.environ,
                        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                        "AI_CONTINUITY_CONVERSATION": "explicit-live",
                        "CLI_LOG": str(cli_log),
                        "CLI_EXIT": "0",
                        "PYTHON_LOG": str(python_log),
                    }
                    result = subprocess.run(
                        [str(BIN / wrapper), "status"],
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("<explicit-live>", python_log.read_text())
                    if cli == "claude":
                        expected_cli_args = [
                            "call",
                            "<--append-system-prompt>",
                            "<FAKE CONTEXT>",
                            "<status>",
                        ]
                    else:
                        expected_cli_args = [
                            "call",
                            "<-c>",
                            '<developer_instructions="FAKE CONTEXT">',
                            "<status>",
                        ]
                    self.assertEqual(
                        cli_log.read_text().splitlines(),
                        expected_cli_args,
                    )

    def test_cleanup_runtime_honors_launchd_resolved_python(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fake_python = root / "resolved-python3"
            python_log = root / "python.log"
            data_dir = root / "data"
            _fake_python(fake_python)
            env = {
                **os.environ,
                "AI_CONTINUITY_DATA_DIR": str(data_dir),
                "AI_CONTINUITY_PYTHON": str(fake_python),
                "PYTHON_LOG": str(python_log),
            }
            result = subprocess.run(
                [str(BIN / "cleanup-runtime")],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            args = python_log.read_text().splitlines()
            self.assertEqual(args[-3:], ["<cleanup>", "<--days>", "<30>"])

    def test_shell_init_defines_onboard_and_offboard_functions(self):
        init = REPO / "bin" / "continuity-shell-init.sh"
        result = subprocess.run(
            [
                "/bin/zsh",
                "-c",
                f'source "{init}"; whence -w continuity-onboard; '
                f"whence -w continuity-offboard",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("continuity-onboard: function", result.stdout)
        self.assertIn("continuity-offboard: function", result.stdout)

    def test_continuity_guide_opens_the_welcome_page(self):
        init = REPO / "bin" / "continuity-shell-init.sh"
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            open_log = root / "open.log"
            _write_executable(
                fake_bin / "open",
                '#!/bin/sh\nprintf "%s\\n" "$@" > "$OPEN_LOG"\n',
            )
            env = {
                **os.environ,
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                "OPEN_LOG": str(open_log),
            }
            result = subprocess.run(
                ["/bin/zsh", "-c", f'source "{init}"; continuity-guide'],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                open_log.read_text().strip(),
                "https://ai-continuity-welcome.amber-moth-2612.chatgpt.site",
            )

    def test_onboard_offboard_functions_forward_to_repo_scripts(self):
        src = (REPO / "bin" / "continuity-shell-init.sh").read_text()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            (fake_bin / "continuity-shell-init.sh").write_text(src)
            for name in ("continuity-onboard", "continuity-offboard"):
                _write_executable(
                    fake_bin / name,
                    "#!/bin/sh\n"
                    f'printf "%s\\n" "{name}" >> "$FWD_LOG"\n'
                    'for arg in "$@"; do printf "<%s>\\n" "$arg" '
                    '>> "$FWD_LOG"; done\n',
                )
            init = fake_bin / "continuity-shell-init.sh"
            for name in ("continuity-onboard", "continuity-offboard"):
                with self.subTest(name=name):
                    log = root / f"{name}.log"
                    env = {**os.environ, "FWD_LOG": str(log)}
                    result = subprocess.run(
                        ["/bin/zsh", "-c", f'source "{init}"; {name} . extra'],
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(
                        log.read_text().splitlines(),
                        [name, "<.>", "<extra>"],
                    )
