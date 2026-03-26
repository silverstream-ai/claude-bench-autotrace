#!/usr/bin/env bash
# Silverstream Bench statusline — appends a clickable deep-dive link below the Claude Code status bar.
# Claude Code pipes session JSON to stdin; we ignore it and just check for a saved URL.

URL_FILE="${TMPDIR:-/tmp}/bench_deep_dive_url"

if [[ -f "$URL_FILE" ]]; then
    URL=$(cat "$URL_FILE")
    printf '\e]8;;%s\e\\\e[4m🔗 See this session on Bench\e[24m\e]8;;\e\\' "$URL"
fi
