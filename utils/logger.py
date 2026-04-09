"""
utils/logger.py
───────────────
Structured logging with console + rotating file output.
Each strategy gets its own child logger for easy filtering.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from config.settings import LogConfig

_CONFIGURED = False


def setup_logging(cfg: Optional[LogConfig] = None) -> None:
    """
    Initialise root logger once.  Safe to call multiple times — subsequent
    calls are no-ops.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    cfg = cfg or LogConfig()
    cfg.log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s | %(name)-22s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── Console handler ──────────────────────────────────────────────────
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(getattr(logging, cfg.console_level.upper(), logging.INFO))
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # ── File handler (rotating) ──────────────────────────────────────────
    log_file = cfg.log_dir / "trading.log"
    fh = RotatingFileHandler(
        log_file,
        maxBytes=cfg.max_bytes,
        backupCount=cfg.backup_count,
    )
    fh.setLevel(getattr(logging, cfg.file_level.upper(), logging.DEBUG))
    fh.setFormatter(fmt)
    root.addHandler(fh)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the 'trading' namespace."""
    setup_logging()
    return logging.getLogger(f"trading.{name}")
