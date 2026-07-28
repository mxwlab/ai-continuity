# AI Continuity — 5-minute quickstart

AI Continuity keeps a bounded handoff and recent turns available when you switch
between Claude Code and Codex CLI in the same project.

## Before you start

- macOS with zsh
- `python3` (the runtime uses only the Python standard library)
- Claude Code and/or Codex CLI already installed

This guide covers the verified macOS CLI path. Linux, bash, and fully passive
desktop startup are not currently guaranteed.

## 1. Install

```bash
curl -fsSL https://raw.githubusercontent.com/mxwlab/ai-continuity/main/install.sh | bash
```

Open a new terminal after installation. (Manual alternative: `git clone` the
repo and run `bin/continuity-install`.)

The installer is safe to rerun. It:

- checks prerequisites (macOS, zsh, `python3`, git, and Claude Code and/or
  Codex CLI) and clones AI Continuity into `~/.local/share/ai-continuity`
  (manual clones can go anywhere)
- adds a marked shell block to `~/.zshrc`; before an actual change to an
  existing file, it saves `~/.zshrc.bak.continuity`
- registers the Claude MCP server at **user scope** through the Claude CLI,
  when Claude Code is installed
- adds `[mcp_servers.ai-continuity]` to the Codex user config at
  `~/.codex/config.toml`, when Codex CLI is installed; before an actual change
  to an existing file, it saves `~/.codex/config.toml.bak.continuity`
- installs the macOS launchd job `com.ai-continuity.cleanup`, which runs daily
  at 02:30 to apply the 30-day raw-content retention policy

To use a non-default local data root, export an absolute
`AI_CONTINUITY_DATA_DIR` before running both install and onboarding. Rerun
install and onboarding if you later change it so the launchd jobs capture the
new location.

## 2. Onboard each project

In the new terminal, run `continuity-onboard` from every project that should
use continuity:

```bash
cd /path/to/your/project
continuity-onboard .
```

Onboarding creates the ignored local marker
`.ai-continuity/continuity.conf`, initializes that conversation, adds bounded
AI Continuity instruction blocks to `AGENTS.md` and `CLAUDE.md`, and installs a
per-project launchd job to refresh the local desktop-context projection. The
instruction blocks ask compatible agents to append substantive incoming and
outgoing turns through MCP, read the latest context, and update the handoff
only when its active state changes. Turn capture is instruction-driven; it is
not a background operating-system recorder.

The isolation rule is **one project = one conversation**. The default
conversation id is the sanitized project directory name plus `-live`. If two
unrelated projects have the same directory name, give each a distinct id:

```bash
continuity-onboard . my-project-client-a
```

Do not deliberately reuse one conversation id across unrelated projects;
doing so would also reuse their continuity context.

## 3. Verify and use

Confirm that the project marker exists:

```bash
cat .ai-continuity/continuity.conf
```

Then start the CLI you normally use, from anywhere inside the onboarded
project:

```bash
claude
# or
codex
```

The shell integration injects the project's current continuity bundle when
the CLI starts. Outside an onboarded project, the normal `claude` and `codex`
commands are unchanged. If context generation fails, the shell integration
stops instead of launching the CLI without continuity. MCP registration can
also be checked with `claude mcp get ai-continuity` or `codex mcp list`, for
the CLI you installed.

Desktop clients do not inherit this automatic zsh startup injection.
Onboarding provides a refreshed local projection and project instructions,
but desktop continuity remains assisted and depends on the client reading the
projection or calling MCP.

## Isolation and local data

Every user runs an **independent local instance**. There is **no cloud sync**,
no shared workspace between users, and no automatic transfer of continuity
data between machines.

By default, this machine's owned data is under:

```text
~/Library/Application Support/AI Continuity/
├── runtime/
└── logs/
```

## Uninstall

If you also want to remove a project's marker, generated projection,
instruction blocks, and per-project refresh job, offboard it first:

```bash
/path/to/ai-continuity/bin/continuity-offboard /path/to/your/project
```

Offboarding validates its instruction markers before changing anything. A
damaged marker structure or failure to unload a running project launch agent
causes it to stop and preserve the project state for repair and retry.

Then, from the AI Continuity clone:

```bash
cd /path/to/ai-continuity
bin/continuity-uninstall
```

The default uninstall removes the global shell block, MCP registrations, and
daily cleanup job, but **preserves local data**. To also delete only AI
Continuity's owned `runtime/` and `logs/` directories, opt in explicitly:

```bash
bin/continuity-uninstall --purge
```

`--purge` does not delete the configured data-root directory or unrelated
files placed beside `runtime/` and `logs/`.

## Quick troubleshooting

- No context on CLI startup: open a new terminal (or run `source ~/.zshrc`),
  then confirm your current directory is inside a project containing a valid
  `.ai-continuity/continuity.conf`.
- The CLI reports that context generation failed: confirm `python3` is
  available and the marker names an initialized conversation; the CLI was not
  launched without continuity.
- The installer reported an MCP warning: run the matching check above, fix the
  Claude/Codex CLI configuration issue, and rerun `bin/continuity-install`.
- Onboarding warns that a conversation id already exists: if this is a
  different project, rerun onboarding with a new explicit id.
- Cleanup job missing: check with
  `launchctl list com.ai-continuity.cleanup`, then rerun the installer.
