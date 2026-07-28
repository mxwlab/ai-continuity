#!/bin/sh
# install.sh — one-line bootstrap for AI Continuity.
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/mxwlab/ai-continuity/main/install.sh | bash
# Non-interactive: stdin is the piped script, so this never prompts. It checks
# preconditions, fetches the repo into a stable location, then delegates all
# system changes to the hardened bin/continuity-install.
set -eu
# Fail instead of prompting: curl | bash has no TTY.
export GIT_TERMINAL_PROMPT=0

REPO_URL="${AI_CONTINUITY_REPO_URL:-https://github.com/mxwlab/ai-continuity.git}"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
INSTALL_DIR="$DATA_HOME/ai-continuity"
WELCOME_URL="${AI_CONTINUITY_GUIDE_URL:-https://ai-continuity-welcome.amber-moth-2612.chatgpt.site}"

err() { printf 'AI Continuity install: %s\n' "$1" >&2; exit 1; }

# 1. Preconditions (fail closed, mutate nothing).
os="${AI_CONTINUITY_UNAME:-$(uname -s)}"
[ "$os" = "Darwin" ] || err "macOS is required (detected: $os)."
command -v zsh >/dev/null 2>&1 || \
  err "zsh not found; AI Continuity's shell integration needs zsh."
command -v python3 >/dev/null 2>&1 || \
  err "python3 not found; install it (e.g. 'brew install python') and retry."
command -v git >/dev/null 2>&1 || \
  err "git not found; run 'xcode-select --install' and retry."
if ! command -v claude >/dev/null 2>&1 && ! command -v codex >/dev/null 2>&1; then
  err "install Claude Code or Codex CLI first, then retry."
fi

# 2. Fetch code into a stable location (never overwrite a foreign directory).
if [ -e "$INSTALL_DIR" ]; then
  if [ -d "$INSTALL_DIR/.git" ] && \
     [ "$(git -C "$INSTALL_DIR" remote get-url origin 2>/dev/null || true)" \
       = "$REPO_URL" ]; then
    printf 'Updating existing install at %s\n' "$INSTALL_DIR"
    git -C "$INSTALL_DIR" pull --ff-only
  else
    err "$INSTALL_DIR exists and is not an AI Continuity checkout; remove or move it, then retry."
  fi
else
  printf 'Cloning AI Continuity into %s\n' "$INSTALL_DIR"
  mkdir -p "$DATA_HOME"
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

# 3. Delegate all environment setup to the hardened installer.
"$INSTALL_DIR/bin/continuity-install"

# 4. Print next steps.
cat <<'EOF'

AI Continuity installed.

Open a NEW terminal, then for each project you want continuity in:

    cd /path/to/your/project
    continuity-onboard .
    claude   # or codex

中文使用说明：
https://github.com/mxwlab/ai-continuity/blob/main/docs/USAGE.zh-CN.md

EOF

# 5. Open the visual guide only for a real terminal session. Automated runs,
# redirected output, opt-out installs, and browser failures still succeed.
if [ "${AI_CONTINUITY_NO_OPEN:-0}" != "1" ] && [ -t 1 ] && \
   command -v open >/dev/null 2>&1; then
  if ! open "$WELCOME_URL" >/dev/null 2>&1; then
    printf 'Open the visual guide: %s\n' "$WELCOME_URL"
  fi
fi
