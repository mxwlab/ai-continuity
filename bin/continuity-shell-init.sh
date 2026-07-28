# bin/continuity-shell-init.sh
# Source this from ~/.zshrc. Provides marker-based continuity resolution.
# Derive the runtime project path from this file's own location (zsh).
_AI_CONTINUITY_PROJECT="${0:A:h:h}"

_ai_continuity_conversation() {
  local dir="$PWD"
  local conf val
  while true; do
    conf="$dir/.ai-continuity/continuity.conf"
    if [ -f "$conf" ]; then
      # Parse the marker instead of sourcing it: take the LAST line
      # matching the key, strip a single layer of surrounding quotes if
      # present. Never execute the file's contents.
      val="$(sed -n 's/^AI_CONTINUITY_CONVERSATION=//p' "$conf" | tail -n 1)"
      case "$val" in
        \"*\") val="${val#\"}"; val="${val%\"}" ;;
        \'*\') val="${val#\'}"; val="${val%\'}" ;;
      esac
      if [ -n "$val" ]; then
        printf '%s' "$val"
        return 0
      fi
    fi
    [ "$dir" = "/" ] && break
    dir="${dir:h}"
  done
  return 1
}

_ai_continuity_claude_context() {
  local conv="${1:-}"
  [ -n "$conv" ] || conv="$(_ai_continuity_conversation)" || return 1
  python3 "$_AI_CONTINUITY_PROJECT/context_prompt.py" --conversation "$conv"
}

_ai_continuity_codex_devinstr() {
  local conv="${1:-}"
  [ -n "$conv" ] || conv="$(_ai_continuity_conversation)" || return 1
  python3 "$_AI_CONTINUITY_PROJECT/context_prompt.py" --conversation "$conv" --json-string
}

claude() {
  local conv context context_status
  if ! conv="$(_ai_continuity_conversation)"; then
    command claude "$@"
    return
  fi
  context="$(_ai_continuity_claude_context "$conv")" || {
    context_status=$?
    print -u2 "AI Continuity: failed to generate Claude context"
    return "$context_status"
  }
  command claude --append-system-prompt "$context" "$@"
}

codex() {
  local conv developer_instructions context_status
  if ! conv="$(_ai_continuity_conversation)"; then
    command codex "$@"
    return
  fi
  developer_instructions="$(_ai_continuity_codex_devinstr "$conv")" || {
    context_status=$?
    print -u2 "AI Continuity: failed to generate Codex context"
    return "$context_status"
  }
  command codex -c "developer_instructions=$developer_instructions" "$@"
}

# Short project commands. The body calls an absolute path, so there is no
# recursion with the function name.
continuity-onboard() {
  "$_AI_CONTINUITY_PROJECT/bin/continuity-onboard" "$@"
}

continuity-offboard() {
  "$_AI_CONTINUITY_PROJECT/bin/continuity-offboard" "$@"
}

# Reopen the visual guide at any time. Print the URL as a safe fallback.
continuity-guide() {
  local url="${AI_CONTINUITY_GUIDE_URL:-https://ai-continuity-welcome.amber-moth-2612.chatgpt.site}"
  if command -v open >/dev/null 2>&1 && open "$url"; then
    return 0
  fi
  print -r -- "$url"
}
