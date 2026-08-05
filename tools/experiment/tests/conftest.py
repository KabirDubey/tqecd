"""Shared fixtures. Requires an installed ``tqec`` (orchestration); skips these tests if
absent, so a bare ``tqecd`` checkout without the optional ``tqec`` dep still collects cleanly."""

from __future__ import annotations

import pytest

# Import the tool first: its package-import side effect isolates tqec's detector-database cache
# (sets TQEC_DETECTOR_DATABASE_PATH) before the importorskip below pulls tqec in.
import tools.experiment  # noqa: F401,E402

pytest.importorskip("tqec.orchestration", reason="experiment tests need the optional tqec dep")


@pytest.fixture
def out_dir(tmp_path):
    return tmp_path / "run"
