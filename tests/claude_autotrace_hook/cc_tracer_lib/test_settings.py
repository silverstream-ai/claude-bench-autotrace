import importlib
from pathlib import Path

import pytest

from claude_autotrace_hook.cc_tracer_lib import settings


def test_settings_loads_from_project_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_dir = tmp_path / 'myproject'
    project_dir.mkdir()
    (project_dir / '.env').write_text('CLAUDE_CODE_ENDPOINT_CODE=from-project-dir\n')

    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(project_dir))
    monkeypatch.delenv('CLAUDE_CODE_ENDPOINT_CODE', raising=False)

    reloaded = importlib.reload(settings)
    s = reloaded.ClaudeCodeTracingSettings()

    assert s.endpoint_code == 'from-project-dir'


def test_settings_loads_from_parent_of_project_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    parent = tmp_path / 'workspace'
    parent.mkdir()
    (parent / '.env').write_text('CLAUDE_CODE_ENDPOINT_CODE=from-parent\n')

    project_dir = parent / 'child'
    project_dir.mkdir()

    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(project_dir))
    monkeypatch.delenv('CLAUDE_CODE_ENDPOINT_CODE', raising=False)

    reloaded = importlib.reload(settings)
    s = reloaded.ClaudeCodeTracingSettings()

    assert s.endpoint_code == 'from-parent'


def test_settings_closer_env_wins_over_farther(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    parent = tmp_path / 'workspace'
    parent.mkdir()
    (parent / '.env').write_text('CLAUDE_CODE_ENDPOINT_CODE=from-parent\n')

    project_dir = parent / 'child'
    project_dir.mkdir()
    (project_dir / '.env').write_text('CLAUDE_CODE_ENDPOINT_CODE=from-child\n')

    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(project_dir))
    monkeypatch.delenv('CLAUDE_CODE_ENDPOINT_CODE', raising=False)

    reloaded = importlib.reload(settings)
    s = reloaded.ClaudeCodeTracingSettings()

    assert s.endpoint_code == 'from-child'
