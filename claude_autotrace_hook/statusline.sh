#!/usr/bin/env bash
# Silverstream Bench statusline — appends a clickable deep-dive link below the Claude Code status bar.

SESSION_ID=$(python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null)
URL_FILE="/tmp/cc_tracer/${SESSION_ID}.url"

if [[ -n "$SESSION_ID" && -f "$URL_FILE" ]]; then
    URL=$(cat "$URL_FILE")
    printf '\e]8;;%s\e\\\e[4m🔗 See this session on Bench\e[24m\e]8;;\e\\' "$URL"
fi
