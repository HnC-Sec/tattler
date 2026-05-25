import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from tattler.config.loader import load_config


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(body))
    return p


def test_loads_valid_yaml(tmp_path: Path):
    path = _write(tmp_path, """
        webhooks:
          alerts:
            url: https://example.com/hook
            format: generic
        rules:
          - name: r1
            pattern: foo
            message: hi
            webhooks: [alerts]
    """)
    cfg = load_config(path)
    assert cfg.rules[0].name == "r1"


def test_raises_on_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")


def test_raises_on_invalid_yaml(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text("::: not yaml :::")
    with pytest.raises(ValueError):
        load_config(path)


def test_raises_on_invalid_schema(tmp_path: Path):
    path = _write(tmp_path, """
        webhooks: {}
        rules:
          - name: r1
            pattern: foo
            message: hi
            webhooks: [missing]
    """)
    with pytest.raises(ValidationError):
        load_config(path)
