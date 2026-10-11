"""Environment-based configuration and logging setup. No secrets are read or logged."""

from __future__ import annotations

import logging
import os

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def ai_mode() -> str:
    return os.environ.get("CAPACITYTWIN_AI_MODE", "mock").strip().lower() or "mock"


def configure_logging() -> None:
    """Send capacitytwin.* logs to stderr once; safe to call on every Streamlit rerun."""
    root = logging.getLogger("capacitytwin")
    if root.handlers:
        return
    level_name = os.environ.get("CAPACITYTWIN_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, None)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(handler)
    root.setLevel(level if isinstance(level, int) else logging.INFO)
    root.propagate = False
    root.info("application startup ai_mode=%s log_level=%s", ai_mode(), logging.getLevelName(root.level))
