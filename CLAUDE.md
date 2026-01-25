# Claude Code Telemetry

This repo has hooks that trace your Claude Code sessions. On session start, you'll see either:
- `{"status":"ok","message":"Telemetry active. Trace ID: ..."}` - tracing is working
- `{"status":"info","message":"Tracing disabled..."}` - needs configuration
- `{"status":"error",...}` - setup issue (follow the instructions in the message)

## Self-Setup

If tracing is disabled or erroring, set it up:

1. Create the Python venv (if missing):
   ```bash
   python3 -m venv venv && venv/bin/pip install -r requirements.txt
   ```

2. Create `.env` with the endpoint URL and code provided by the user:
   ```
   CLAUDE_CODE_ENDPOINT_CODE=<code-from-user>
   CLAUDE_CODE_COLLECTOR_BASE_URL=https://bench.silverstream.ai/traces # Or change if using a local collector, as requested by the user
   ```

Hooks run on every tool use. After creating `.env`, you'll see `{"status":"ok",...}` on subsequent tool calls confirming telemetry is active.
