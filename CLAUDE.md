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
   CLAUDE_CODE_COLLECTOR_BASE_URL=https://bench.silverstream.ai # Or change if using a local collector, as requested by the user
   ```

3. To install globally, integrate the contents of .claude/settings.json into the global settings.json in your home directory (~/.claude/settings.json), changing the hook commands to use absolute paths.
    - IMPORTANT: This file is the user's global Claude config. Make sure not to override it! You should _integrate_ the settings you read in this repository with the existing config.

4. To uninstall globally, revert the changes you made to settings.json. IMPORTANT: Remember that this is the user's global config! Only revert changes specific to this hook and this repository's directory.

5. Notify the user of the result. Provide the user with a tracking link for their runs: `${collector_endpoint}/last-runs?tracker={collector_code}`. If global install/uninstall was done, note that the change will apply on new claude code sessions (suggest they restart their existing sessions).

Hooks run on every tool use. After creating `.env`, you'll see `{"status":"ok",...}` on subsequent tool calls confirming telemetry is active.

### Configuration options

- `CLAUDE_CODE_ENDPOINT_CODE=<string> ` modifies the tracker associated with your runs.
- `CLAUDE_CODE_COLLECTOR_BASE_URL=<url>` modifies the OTel server traces are sent to.
- `CLAUDE_CODE_NOTIFY_SESSIONS=<bool>` (optional) toggles system notifications for the user when sessions are started.
