# AI Continuity

AI Continuity is a local-first bridge for carrying the current conversation
between Claude Code and Codex CLI. Each onboarded project gets its own local
conversation, bounded handoff, and recent-turn history.

> **Supported path:** macOS, zsh, `python3`, and Claude Code and/or Codex CLI.
> The runtime uses only the Python standard library. Linux and bash are not yet
> guaranteed.

第一次使用？打开 [四步可视化引导](https://ai-continuity-welcome.amber-moth-2612.chatgpt.site)，
或阅读 [中文使用说明](docs/USAGE.zh-CN.md)。安装、项目接入、验证、日常切换、
退出和卸载都可以照着执行。

## Install (one line)

```bash
curl -fsSL https://raw.githubusercontent.com/mxwlab/ai-continuity/main/install.sh | bash
```

This checks prerequisites (macOS, zsh, `python3`, git, and Claude Code and/or
Codex CLI), clones AI Continuity into `~/.local/share/ai-continuity`, and wires
up the shell integration, MCP server, and daily cleanup. In a real terminal it
then opens the visual guide; set `AI_CONTINUITY_NO_OPEN=1` to disable that.
Run `continuity-guide` later to reopen it. Prefer to read first?
Download `install.sh`, read it, then run `bash install.sh` — it only clones the
repo and calls `bin/continuity-install`.

Manual alternative:

```bash
git clone https://github.com/mxwlab/ai-continuity.git
cd ai-continuity
bin/continuity-install
```

## How you actually use it (two steps)

AI Continuity has two layers:

1. **Install once** (the command above) — makes your `claude` / `codex`
   commands continuity-aware.
2. **Onboard each project you choose** — you decide which projects get
   continuity; nothing is enabled automatically.

From zero:

```bash
# 1) Install once (ever). Then open a NEW terminal.

# 2) Turn on continuity for a project (once per project):
cd ~/workspace/my-app
continuity-onboard .

# 3) Work as usual — context is carried automatically:
claude   # or codex
```

Coming back later is just `cd ~/workspace/my-app && claude`. A different
project needs its own one-time `continuity-onboard .`.

Run onboarding once for every project that should use continuity. See the
[Full quickstart](docs/QUICKSTART.md) for verification, troubleshooting, and
safe removal.

## What it does

AI Continuity combines four local mechanisms:

1. **Per-project identity.** Onboarding writes the ignored marker
   `.ai-continuity/continuity.conf`. The shell resolver uses the nearest marker
   above the current directory. The isolation rule is one project = one
   conversation.
2. **Automatic CLI startup context.** The installer adds zsh functions for the
   ordinary `claude` and `codex` commands. Inside an onboarded project, they
   compile the current handoff and recent turns and inject that bundle at
   process startup. Outside an onboarded project, both commands pass through
   unchanged. Context generation fails closed: if the bundle cannot be built,
   the requested CLI is not started without continuity.
3. **A local MCP server.** `continuity_mcp.py` exposes tools to append events,
   read current context, update a revisioned handoff, and apply retention
   cleanup. The installer registers it for any installed supported CLI.
4. **Instruction-driven turn capture.** Onboarding adds a delimited AI
   Continuity block to the project's `AGENTS.md` and `CLAUDE.md`. It instructs
   compatible agents to record substantive incoming and outgoing turns, read
   the current context, and update the handoff only when the active state
   changes. This is agent-instruction behavior, not an operating-system
   keystroke recorder.

Runtime events are append-only JSONL. The current handoff uses revision checks
so concurrent agents cannot silently overwrite a newer update.

## Local isolation and privacy

Every user runs an **independent local instance**. There is no cloud service,
cross-user workspace, or automatic machine-to-machine sync. Local instances
share nothing unless the user separately copies their data.

Each project must use a distinct conversation id. If no id is supplied,
onboarding derives one from the sanitized project directory name plus
`-live`. Projects with the same directory name need explicit distinct ids:

```bash
/path/to/ai-continuity/bin/continuity-onboard . client-a-app
```

By default, owned data lives under:

```text
~/Library/Application Support/AI Continuity/
├── runtime/
└── logs/
```

Set `AI_CONTINUITY_DATA_DIR` to an absolute directory before install and
onboarding to use another data root:

```bash
export AI_CONTINUITY_DATA_DIR="/absolute/path/to/ai-continuity-data"
```

The cleanup launch agent redacts raw event content after 30 days while keeping
event metadata. A handoff may contain optional links to canonical external
notes; linked note content is not copied automatically.

## Install, onboard, offboard, uninstall

`bin/continuity-install` is idempotent. It:

- adds a marked source block to `~/.zshrc`, backing up an existing file before
  an actual change
- registers the MCP server at Claude user scope when Claude Code is installed
- adds the MCP server to the Codex user config when Codex CLI is installed,
  backing up an existing config before an actual change
- installs a daily macOS cleanup launch agent

`continuity-onboard` validates the conversation id before writing project
state, creates the local marker and projection, appends delimited instruction
blocks without replacing existing project rules, and installs a per-project
projection refresh agent:

```bash
/path/to/ai-continuity/bin/continuity-onboard \
  /path/to/project [conversation-id]
```

`continuity-offboard` removes that project's marker, generated projection,
instruction blocks, and refresh agent while preserving event history:

```bash
/path/to/ai-continuity/bin/continuity-offboard /path/to/project
```

Offboarding validates its owned instruction blocks before making changes. If
their markers are damaged, or a loaded launch agent cannot be unloaded, it
stops and preserves project state for repair and retry.

After offboarding projects you no longer want connected, remove the global
shell, MCP, and cleanup integration:

```bash
cd /path/to/ai-continuity
bin/continuity-uninstall
```

Uninstall preserves local data by default. The explicit purge option deletes
only the owned `runtime/` and `logs/` children, not the configured data root or
unrelated neighboring files:

```bash
bin/continuity-uninstall --purge
```

## Desktop surfaces

Setup is still done from the CLI (`continuity-onboard .`). Onboarding generates
`.ai-continuity/desktop-context.md` and refreshes it every minute, and adds a
project instruction asking a compatible desktop agent to read it. Desktop
continuity is therefore **assisted**: the client reads the projection and the
project instructions — it is not passive startup injection like the CLI. Restart
the desktop app once after onboarding.

Note: the installer wires the MCP server for the Claude Code CLI and Codex, not
the separate Claude desktop-app MCP config.

## Known limits

- The verified automatic startup path is macOS + zsh CLI.
- Two unrelated projects with the same directory basename derive the same
  default conversation id. Use explicit distinct ids.
- A missing or empty marker is treated as absent while the resolver continues
  toward parent directories. Remove project integration with
  `continuity-offboard` instead of leaving a damaged marker.
- Marker values are parsed as data and are never sourced as shell code.

## Development

```bash
python3 -m unittest discover -s tests -v
bin/check-release-clean
```

## License

MIT — see [LICENSE](LICENSE).
