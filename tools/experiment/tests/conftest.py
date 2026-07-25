"""Shared fixtures. Requires an installed ``tqec`` (orchestration); skips the whole battery if
absent, so a bare ``tqecd`` checkout without the optional ``tqec`` dep still collects cleanly."""

from __future__ import annotations

import pytest

pytest.importorskip("tqec.orchestration", reason="experiment tests need the optional tqec dep")


@pytest.fixture
def out_dir(tmp_path):
    return tmp_path / "run"
