import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from cc_tracer_lib.models import BENCH_AUTOTRACE_DIR

ENV_FILE = BENCH_AUTOTRACE_DIR / ".env"


def _collect_env_files() -> tuple[Path, ...]:
    """Collect .env files: repo root (lowest priority) then ancestors up to project dir (highest)."""
    files: list[Path] = [ENV_FILE]
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if project_dir is not None:
        cur = Path(project_dir).resolve()
        ancestors: list[Path] = []
        while True:
            ancestors.append(cur / ".env")
            parent = cur.parent
            if parent == cur:
                break
            cur = parent
        # farthest ancestor first (low priority) → project_dir last (high priority)
        files.extend(reversed(ancestors))
    return tuple(files)


class ClaudeCodeTracingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CLAUDE_CODE_",
        env_file=_collect_env_files(),
        extra="ignore",
    )

    collector_base_url: str | None = None
    endpoint_code: str | None = None
    model: str = Field(default="claude-code")
    harness: str = Field(default="claude-code-hooks")
    notify_sessions: bool = Field(default=True)
