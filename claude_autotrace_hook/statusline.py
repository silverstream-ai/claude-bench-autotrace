#!/usr/bin/env python3
import json
import sys
from uuid import UUID

from cc_tracer_lib.models import SessionState
from cc_tracer_lib.settings import ClaudeCodeTracingSettings
from cc_tracer_lib.url_generator import build_deep_dive_url

data = json.load(sys.stdin)
session_id = data.get("session_id", "")
if not session_id:
    sys.exit(0)

state = SessionState.from_session_id(session_id)
if state is None:
    sys.exit(0)

settings = ClaudeCodeTracingSettings()
if settings.collector_base_url is None or settings.endpoint_code is None:
    sys.exit(0)

try:
    tracker_id = UUID(settings.endpoint_code)
except ValueError:
    sys.exit(0)

url = build_deep_dive_url(settings.collector_base_url, tracker_id, state.trace_id)
print(f"\x1b]8;;{url}\x1b\\\x1b[4m\U0001f517 See this session on Bench\x1b[24m\x1b]8;;\x1b\\", end="")
