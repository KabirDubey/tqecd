"""Timestamped run logging for the experiment tool.

Each run writes a log file under ``<out_dir>/logs`` named ``{DDMMMYY}_{HHMM}_experiment.log``
(for example ``25Jul26_0537_experiment.log``). The same messages can be mirrored to the console by
the caller; this module only owns the file.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path


def timestamp() -> str:
    """Return the ``DDMMMYY_HHMM`` run stamp, e.g. ``25Jul26_0537``."""
    return datetime.now().strftime("%d%b%y_%H%M")


def make_logger(out_dir: str | Path, name: str = "experiment") -> tuple[logging.Logger, Path]:
    """Create a file logger under ``<out_dir>/logs`` and return ``(logger, log_path)``."""
    logs_dir = Path(out_dir) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"{timestamp()}_{name}.log"
    logger = logging.getLogger(f"tools.experiment.{path.stem}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger, path
