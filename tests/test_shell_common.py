# tests/test_shell_common.py
import os, plistlib, stat, subprocess, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LIB = REPO / "bin" / "lib" / "continuity-common.sh"

def run_sh(script: str, cwd=None, env=None):
    full = f'set -eu\nRUNTIME_PROJECT="{REPO}"\n. "{LIB}"\n{script}'
    return subprocess.run(["/bin/sh", "-c", full], cwd=cwd,
                          env=env,
                          capture_output=True, text=True)

class TestCommon(unittest.TestCase):
    def test_read_conversation_reads_marker(self):
        with tempfile.TemporaryDirectory() as d:
            conf = Path(d) / ".ai-continuity"
            conf.mkdir()
            (conf / "continuity.conf").write_text("AI_CONTINUITY_CONVERSATION=brand-site-live\n")
            r = run_sh(f'continuity_read_conversation "{d}"')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), "brand-site-live")

    def test_read_conversation_missing_marker_fails(self):
        with tempfile.TemporaryDirectory() as d:
            r = run_sh(f'continuity_read_conversation "{d}"')
            self.assertNotEqual(r.returncode, 0)

    def test_read_conversation_does_not_execute_marker_content(self):
        # continuity_read_conversation must parse the marker, never source
        # it: a value containing a command substitution must not run.
        with tempfile.TemporaryDirectory() as d:
            conf = Path(d) / ".ai-continuity"
            conf.mkdir()
            sentinel = Path(d) / "pwned"
            (conf / "continuity.conf").write_text(
                f'AI_CONTINUITY_CONVERSATION=$(touch {sentinel})\n')
            r = run_sh(f'continuity_read_conversation "{d}"')
            self.assertFalse(sentinel.exists(),
                              "marker content must not be executed")
            # Either treated literally (validation would later reject it) or
            # rejected outright; either way nothing executed.
            if r.returncode == 0:
                self.assertIn("$(touch", r.stdout)

    def test_read_conversation_does_not_execute_backticks(self):
        with tempfile.TemporaryDirectory() as d:
            conf = Path(d) / ".ai-continuity"
            conf.mkdir()
            sentinel = Path(d) / "pwned2"
            (conf / "continuity.conf").write_text(
                f'AI_CONTINUITY_CONVERSATION=`touch {sentinel}`\n')
            r = run_sh(f'continuity_read_conversation "{d}"')
            self.assertFalse(sentinel.exists(),
                              "marker content must not be executed")

    def test_read_conversation_strips_quotes(self):
        with tempfile.TemporaryDirectory() as d:
            conf = Path(d) / ".ai-continuity"
            conf.mkdir()
            (conf / "continuity.conf").write_text(
                'AI_CONTINUITY_CONVERSATION="quoted-live"\n')
            r = run_sh(f'continuity_read_conversation "{d}"')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), "quoted-live")

    def test_launchd_label_differs_for_same_basename_different_paths(self):
        with tempfile.TemporaryDirectory() as d:
            a = Path(d) / "a" / "myproj"; a.mkdir(parents=True)
            b = Path(d) / "b" / "myproj"; b.mkdir(parents=True)
            ra = run_sh(f'continuity_launchd_label "{a}"')
            rb = run_sh(f'continuity_launchd_label "{b}"')
            self.assertEqual(ra.returncode, 0, ra.stderr)
            self.assertEqual(rb.returncode, 0, rb.stderr)
            la, lb = ra.stdout.strip(), rb.stdout.strip()
            self.assertNotEqual(la, lb,
                                 "same-basename projects at different paths must get distinct labels")
            prefix = "com.ai-continuity.desktop-context.myproj-"
            self.assertTrue(la.startswith(prefix), la)
            self.assertTrue(lb.startswith(prefix), lb)

    def test_launchd_label_stable_for_same_path(self):
        with tempfile.TemporaryDirectory() as d:
            r1 = run_sh(f'continuity_launchd_label "{d}"')
            r2 = run_sh(f'continuity_launchd_label "{d}"')
            self.assertEqual(r1.returncode, 0, r1.stderr)
            self.assertEqual(r1.stdout.strip(), r2.stdout.strip(),
                              "same input must produce the same label")

    def test_ensure_gitignore_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            run_sh(f'continuity_ensure_gitignore "{d}"')
            run_sh(f'continuity_ensure_gitignore "{d}"')
            gi = (Path(d) / ".gitignore").read_text().splitlines()
            self.assertEqual(gi.count(".ai-continuity/"), 1)

    def test_replace_or_append_block_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "AGENTS.md"
            f.write_text("# Existing\n")
            cmd = ('continuity_replace_or_append_block '
                   f'"{f}" "<!-- B -->" "<!-- E -->" '
                   '"<!-- B -->\nhello\n<!-- E -->"')
            r1 = run_sh(cmd)
            self.assertEqual(r1.returncode, 0, r1.stderr)
            r2 = run_sh(cmd)
            self.assertEqual(r2.returncode, 0, r2.stderr)
            text = f.read_text()
            self.assertEqual(text.count("<!-- B -->"), 1)
            self.assertIn("# Existing", text)
            self.assertIn("hello", text)

    def test_replace_or_append_block_replaces_body(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "AGENTS.md"
            f.write_text("# Existing\n")
            cmd_a = ('continuity_replace_or_append_block '
                     f'"{f}" "<!-- B -->" "<!-- E -->" '
                     '"<!-- B -->\nalpha-body\n<!-- E -->"')
            cmd_b = ('continuity_replace_or_append_block '
                     f'"{f}" "<!-- B -->" "<!-- E -->" '
                     '"<!-- B -->\nbeta-body\n<!-- E -->"')
            ra = run_sh(cmd_a)
            self.assertEqual(ra.returncode, 0, ra.stderr)
            rb = run_sh(cmd_b)
            self.assertEqual(rb.returncode, 0, rb.stderr)
            text = f.read_text()
            self.assertEqual(text.count("<!-- B -->"), 1)
            self.assertEqual(text.count("<!-- E -->"), 1)
            self.assertIn("beta-body", text)
            self.assertNotIn("alpha-body", text)
            self.assertIn("# Existing", text)

    def test_replace_or_append_ignores_inline_marker_references(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "AGENTS.md"
            inline = (
                "# Existing\n"
                "Docs mention <!-- B --> and <!-- E --> as literal text.\n"
                "Keep this tail.\n"
            )
            target.write_text(inline)
            command = (
                "continuity_replace_or_append_block "
                f'"{target}" "<!-- B -->" "<!-- E -->" '
                '"<!-- B -->\nnew-body\n<!-- E -->"'
            )
            result = run_sh(command)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = target.read_text()
            self.assertIn(inline, text)
            self.assertEqual(text.count("\n<!-- B -->\n"), 1)
            self.assertIn("new-body", text)

    def test_replace_or_append_rejects_invalid_marker_structures(self):
        begin = "<!-- B -->"
        end = "<!-- E -->"
        complete = f"{begin}\nold-body\n{end}\n"
        malformed_cases = {
            "begin_without_end": f"keep\n{begin}\nuser tail\n",
            "end_without_begin": f"keep\n{end}\nuser tail\n",
            "duplicate_pairs": f"keep\n{complete}{complete}user tail\n",
            "end_before_begin": f"keep\n{end}\n{begin}\nuser tail\n",
            "nested_begin": (
                f"keep\n{begin}\nold-body\n{begin}\n"
                f"nested-body\n{end}\nuser tail\n"
            ),
        }
        for name, malformed in malformed_cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                target = Path(d) / "AGENTS.md"
                original = malformed.encode()
                target.write_bytes(original)
                command = (
                    "continuity_replace_or_append_block "
                    f'"{target}" "{begin}" "{end}" '
                    f'"{begin}\nnew-body\n{end}"'
                )
                result = run_sh(command)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(target.read_bytes(), original)

    def test_remove_block_preserves_file_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "config"
            target.write_text(
                "keep\n\n<!-- B -->\nremove\n<!-- E -->\n"
            )
            target.chmod(0o600)
            result = run_sh(
                f'continuity_remove_block "{target}" "<!-- B -->" "<!-- E -->"'
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(target.read_text(), "keep\n")

    def test_remove_block_preserves_symlink_and_edits_target(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "actual-config"
            target.write_text(
                "keep\n\n<!-- B -->\nremove\n<!-- E -->\n"
            )
            link = Path(d) / "config-link"
            link.symlink_to(target)
            target.chmod(0o600)
            original_uid = target.stat().st_uid
            original_gid = target.stat().st_gid
            result = run_sh(
                f'continuity_remove_block "{link}" "<!-- B -->" "<!-- E -->"'
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_text(), "keep\n")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(target.stat().st_uid, original_uid)
            self.assertEqual(target.stat().st_gid, original_gid)

    def test_remove_block_ignores_inline_marker_references(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "config"
            original = (
                "keep\n"
                "User text references <!-- B --> and <!-- E --> inline.\n"
                "keep tail\n"
            )
            target.write_text(original)
            result = run_sh(
                f'continuity_remove_block "{target}" "<!-- B -->" "<!-- E -->"'
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(target.read_text(), original)

    def test_remove_block_rejects_invalid_marker_structures(self):
        begin = "<!-- B -->"
        end = "<!-- E -->"
        complete = f"{begin}\nold-body\n{end}\n"
        malformed_cases = {
            "begin_without_end": f"keep\n{begin}\nuser tail\n",
            "end_without_begin": f"keep\n{end}\nuser tail\n",
            "duplicate_pairs": f"keep\n{complete}{complete}user tail\n",
            "end_before_begin": f"keep\n{end}\n{begin}\nuser tail\n",
            "nested_begin": (
                f"keep\n{begin}\nold-body\n{begin}\n"
                f"nested-body\n{end}\nuser tail\n"
            ),
        }
        for name, malformed in malformed_cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                target = Path(d) / "AGENTS.md"
                original = malformed.encode()
                target.write_bytes(original)
                result = run_sh(
                    f'continuity_remove_block "{target}" "{begin}" "{end}"'
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(target.read_bytes(), original)

    def test_commit_failure_leaves_original_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            target_dir = root / "locked"
            target_dir.mkdir()
            target = target_dir / "config"
            original = b"original bytes\n"
            target.write_bytes(original)
            source = root / "generated-edit"
            source.write_bytes(b"replacement bytes\n")
            target_dir.chmod(0o500)
            try:
                result = run_sh(
                    f'continuity_commit_edit "{source}" "{target}"'
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(target.read_bytes(), original)
                self.assertFalse(source.exists())
            finally:
                target_dir.chmod(0o700)

    def test_install_launchd_unload_failure_preserves_existing_plist(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            home = root / "home"
            project = root / "project"
            fake_bin = root / "bin"
            home.mkdir()
            project.mkdir()
            fake_bin.mkdir()
            label_result = run_sh(
                f'continuity_launchd_label "{project}"'
            )
            self.assertEqual(label_result.returncode, 0, label_result.stderr)
            label = label_result.stdout.strip()
            plist = home / "Library" / "LaunchAgents" / f"{label}.plist"
            plist.parent.mkdir(parents=True)
            original = b"existing plist bytes\n"
            plist.write_bytes(original)
            launchctl = fake_bin / "launchctl"
            launchctl.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n" "$*" >> "$LAUNCHCTL_LOG"\n'
                'case "$1" in\n'
                "  list) exit 0 ;;\n"
                "  unload) exit 42 ;;\n"
                "  *) exit 0 ;;\n"
                "esac\n"
            )
            launchctl.chmod(0o755)
            launchctl_log = root / "launchctl.log"
            env = {
                **os.environ,
                "HOME": str(home),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                "LAUNCHCTL_LOG": str(launchctl_log),
            }
            result = run_sh(
                f'continuity_install_launchd "{project}" "{REPO}"',
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unload", (result.stdout + result.stderr).lower())
            self.assertEqual(plist.read_bytes(), original)
            self.assertEqual(
                launchctl_log.read_text().splitlines(),
                [f"list {label}", f"unload {plist}"],
            )

    def test_install_launchd_uses_data_dir_logs_and_valid_environment(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            home = root / "home"
            project = root / "project"
            data_dir = root / "data & continuity"
            fake_bin = root / "bin"
            home.mkdir()
            project.mkdir()
            fake_bin.mkdir()
            launchctl = fake_bin / "launchctl"
            launchctl.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n" "$*" >> "$LAUNCHCTL_LOG"\n'
                'case "$1" in list) exit 1 ;; *) exit 0 ;; esac\n'
            )
            launchctl.chmod(0o755)
            python3 = fake_bin / "python3"
            python3.write_text("#!/bin/sh\nexit 0\n")
            python3.chmod(0o755)
            launchctl_log = root / "launchctl.log"
            env = {
                **os.environ,
                "HOME": str(home),
                "AI_CONTINUITY_DATA_DIR": str(data_dir),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                "LAUNCHCTL_LOG": str(launchctl_log),
            }
            result = run_sh(
                f'continuity_install_launchd "{project}" "{REPO}"',
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            plists = list((home / "Library" / "LaunchAgents").glob("*.plist"))
            self.assertEqual(len(plists), 1)
            parsed = plistlib.loads(plists[0].read_bytes())
            expected_logs = data_dir / "logs"
            self.assertEqual(
                parsed["EnvironmentVariables"]["AI_CONTINUITY_DATA_DIR"],
                str(data_dir),
            )
            self.assertEqual(
                parsed["EnvironmentVariables"]["AI_CONTINUITY_PYTHON"],
                str(python3),
            )
            self.assertEqual(
                parsed["StandardOutPath"],
                str(expected_logs / f"desktop-context.{parsed['Label']}.log"),
            )
            self.assertEqual(
                parsed["StandardErrorPath"],
                str(expected_logs / f"desktop-context.{parsed['Label']}.err.log"),
            )
            self.assertTrue(expected_logs.is_dir())
            calls = launchctl_log.read_text().splitlines()
            self.assertEqual(calls[0], f"list {parsed['Label']}")
            self.assertEqual(calls[1], f"load {plists[0]}")
            original_plist = plists[0].read_bytes()
            second = run_sh(
                f'continuity_install_launchd "{project}" "{REPO}"',
                env=env,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(plists[0].read_bytes(), original_plist)
            self.assertEqual(
                launchctl_log.read_text().splitlines(),
                [
                    f"list {parsed['Label']}",
                    f"load {plists[0]}",
                    f"list {parsed['Label']}",
                    f"load {plists[0]}",
                ],
            )

if __name__ == "__main__":
    unittest.main()
