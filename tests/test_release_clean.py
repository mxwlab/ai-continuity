import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "bin" / "check-release-clean"


def is_export_ignored(relative_path):
    candidate = relative_path
    while True:
        result = subprocess.run(
            ["git", "check-attr", "export-ignore", "--", candidate],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        )
        if result.stdout.rstrip().endswith(": set"):
            return True
        if "/" not in candidate:
            return False
        candidate = candidate.rsplit("/", 1)[0]


def shippable_tracked_files():
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        path
        for path in result.stdout.splitlines()
        if not is_export_ignored(path) and (REPO / path).is_file()
    ]


class TestReleaseClean(unittest.TestCase):
    def test_gate_exists_and_runs(self):
        self.assertTrue(GATE.exists(), "gate script must exist")

    def test_gate_flags_a_forbidden_string(self):
        # Feed a fake line via stdin-mode: gate scans given files if args passed.
        author = "moxi" + "uwen"
        home_path = "/" + "Users" + "/" + author + "/secret"
        r = subprocess.run(
            [str(GATE), "--scan-text", home_path],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(author, r.stdout + r.stderr)

    def test_gate_flags_every_public_release_secret_pattern(self):
        cases = {
            "author username": "moxi" + "uwen",
            "macOS home path": "/" + "Users" + "/example/private",
            "account id": "m194" + "1696989",
            "provider secret": "DEEP" + "SEEK_API_KEY=value",
            "service account": "fei" + "shu-app-id",
            "private key": "BEGIN " + "OPENAI " + "PRIVATE KEY",
            "prototype label": "P" + "0 runtime",
            "internal conversation id": "ai-continuity-" + "shadow",
            "internal observation id": "ai-continuity-" + "live",
            "observation phrase": "one-" + "week observation",
            "shadow label": "shadow-" + "mode",
        }
        for label, text in cases.items():
            with self.subTest(label=label):
                result = subprocess.run(
                    [str(GATE), "--scan-text", text],
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(
                    result.returncode,
                    0,
                    f"release gate missed {label}",
                )

    def test_gate_passes_on_clean_text(self):
        r = subprocess.run([str(GATE), "--scan-text", "hello world"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_default_gate_passes_on_repo(self):
        r = subprocess.run([str(GATE)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_license_is_mit(self):
        lic = (REPO / "LICENSE").read_text()
        self.assertIn("MIT License", lic)

    def test_internal_docs_export_ignored(self):
        attrs = (REPO / ".gitattributes").read_text().splitlines()
        self.assertIn("docs/superpowers export-ignore", attrs)
        self.assertIn("/AGENTS.md export-ignore", attrs)
        self.assertIn("/CLAUDE.md export-ignore", attrs)
        self.assertIn("/welcome-site export-ignore", attrs)

    def test_gate_scans_its_own_source_and_release_tests(self):
        source = GATE.read_text()
        self.assertNotIn(":(exclude)bin/check-release-clean", source)
        self.assertNotIn(":(exclude)tests/test_release_clean.py", source)

    def test_shippable_surface_has_no_private_or_internal_terms(self):
        forbidden = {
            "author username": "moxi" + "uwen",
            "macOS home prefix": "/" + "Users" + "/",
            "account id": "m194" + "1696989",
            "provider marker": "DEEP" + "SEEK",
            "service marker": "fei" + "shu",
            "prototype label": "P" + "0",
            "internal shadow id": "ai-continuity-" + "shadow",
            "internal live id": "ai-continuity-" + "live",
            "observation phrase": "one-" + "week",
            "shadow label": "shadow-" + "mode",
        }
        hits = []
        for path in shippable_tracked_files():
            text = (REPO / path).read_text(errors="ignore").lower()
            for label, token in forbidden.items():
                if token.lower() in text:
                    hits.append(f"{path}: {label}")
        self.assertEqual(hits, [], "\n".join(hits))

    def test_readme_is_a_public_entry_point(self):
        readme = (REPO / "README.md").read_text()
        self.assertIn("## Install (one line)", readme)
        self.assertIn(
            "curl -fsSL https://raw.githubusercontent.com/mxwlab/ai-continuity/main/install.sh | bash",
            readme,
        )
        self.assertIn("git clone https://github.com/mxwlab/ai-continuity.git", readme)
        self.assertIn("bin/continuity-install", readme)

        walkthrough_heading = "## How you actually use it"
        start = readme.index(walkthrough_heading)
        next_heading = readme.index("\n## ", start + len(walkthrough_heading))
        walkthrough = readme[start:next_heading]
        self.assertIn("continuity-onboard .", walkthrough)
        self.assertNotIn(
            "/path/to/ai-continuity/bin/continuity-onboard", walkthrough
        )

        self.assertIn("[Full quickstart](docs/QUICKSTART.md)", readme)
        self.assertIn("instruction-driven", readme.lower())
        self.assertIn("assisted", readme)
        self.assertIn("independent local instance", readme)
        self.assertIn("AI_CONTINUITY_DATA_DIR", readme)
        self.assertIn("continuity-offboard", readme)
        self.assertIn("continuity-uninstall", readme)

        lower = readme.lower()
        for internal_term in (
            "p" + "0",
            "ai-continuity-" + "shadow",
            "ai-continuity-" + "live",
            "one-" + "week",
            "controlled " + "live",
        ):
            self.assertNotIn(internal_term, lower)

    def test_quickstart_exists_and_has_install_workflow(self):
        qs = (REPO / "docs" / "QUICKSTART.md").read_text()
        self.assertIn(
            "curl -fsSL https://raw.githubusercontent.com/mxwlab/ai-continuity/main/install.sh | bash",
            qs,
        )
        self.assertIn("bin/continuity-install", qs)
        self.assertIn("continuity-onboard .", qs)

    def test_quickstart_states_local_isolation_boundary(self):
        qs = (REPO / "docs" / "QUICKSTART.md").read_text().lower()
        self.assertIn("one project = one conversation", qs)
        self.assertIn("independent local instance", qs)
        self.assertIn("no cloud sync", qs)
        self.assertIn('sanitized project directory name plus `-live`', qs)

    def test_quickstart_states_uninstall_data_boundary(self):
        qs = (REPO / "docs" / "QUICKSTART.md").read_text()
        self.assertIn("bin/continuity-uninstall", qs)
        self.assertIn("--purge", qs)
        self.assertIn("runtime/", qs)
        self.assertIn("logs/", qs)

    def test_chinese_friend_guide_covers_the_complete_first_run(self):
        guide_path = REPO / "docs" / "USAGE.zh-CN.md"
        self.assertTrue(guide_path.exists())
        guide = guide_path.read_text()
        for expected in (
            "continuity-onboard .",
            "cat .ai-continuity/continuity.conf",
            "claude",
            "codex",
            "continuity-offboard .",
            "continuity-uninstall",
            "不会自动同步到云端",
        ):
            self.assertIn(expected, guide)

        readme = (REPO / "README.md").read_text()
        self.assertIn("[中文使用说明](docs/USAGE.zh-CN.md)", readme)
        self.assertIn(
            "https://ai-continuity-welcome.amber-moth-2612.chatgpt.site",
            readme,
        )
