"""Professional logging utility with neon-themed console formatting,
file rotation, and automatic sensitive data redaction.
"""

from __future__ import annotations

import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

# Regular expressions for scrubbing sensitive information
RE_TOKEN = re.compile(r"([a-zA-Z0-9_\-]{24,26}\.[a-zA-Z0-9_\-]{6}\.[a-zA-Z0-9_\-]{27,38})")
RE_MONGO_PASSWORD = re.compile(r"://([^:]+):([^@]+)@")


class SensitiveDataFilter(logging.Filter):
    """Filter that masks tokens and credentials before writing to logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # Ensure message formatting args are evaluated and scrubbed
            msg = record.getMessage()
            msg = RE_TOKEN.sub(r"***DISCORD_TOKEN_REDACTED***", msg)
            msg = RE_MONGO_PASSWORD.sub(r"://\1:***REDACTED***@", msg)
            record.msg = msg
            record.args = ()
        except Exception:
            pass
        return True


class ColoredFormatter(logging.Formatter):
    """ANSI color-coded console formatter matching the black & neon purple identity."""

    # ANSI color codes
    GRAY = "\033[90m"
    PURPLE = "\033[38;2;157;78;221m"  # Neon purple #9D4EDD
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    BOLD_RED = "\033[1;31m"
    RESET = "\033[0m"

    LEVEL_COLORS = {
        logging.DEBUG: GRAY,
        logging.INFO: PURPLE,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: BOLD_RED,
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.LEVEL_COLORS.get(record.levelno, self.RESET)
        time_str = f"{self.GRAY}{self.formatTime(record, '%Y-%m-%d %H:%M:%S')}{self.RESET}"
        level_str = f"{color}[{record.levelname:<8}]{self.RESET}"
        name_str = f"{self.CYAN}[{record.name}]{self.RESET}"
        msg = f"{record.getMessage()}"

        formatted = f"{time_str} {level_str} {name_str} {msg}"

        if record.exc_info:
            formatted += f"\n{self.formatException(record.exc_info)}"
        return formatted


def setup_logging(
    level: str = "INFO",
    log_dir: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Initialize system-wide logging configuration.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_dir: Directory to save log files (defaults to 'logs' in project root).
        max_bytes: Maximum log file size before rotating (default: 10MB).
        backup_count: Number of rotated log archives to keep.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Determine log directory
    if log_dir is None:
        root_dir = Path(__file__).resolve().parent.parent.parent
        log_path = root_dir / "logs"
    else:
        log_path = Path(log_dir)

    log_path.mkdir(parents=True, exist_ok=True)
    log_file = log_path / "bot.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Remove existing handlers to avoid duplicates
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    data_filter = SensitiveDataFilter()

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(ColoredFormatter())
    console_handler.addFilter(data_filter)
    root_logger.addHandler(console_handler)

    # File Handler (Rotating)
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(file_formatter)
    file_handler.addFilter(data_filter)
    root_logger.addHandler(file_handler)

    # Silence overly verbose external libraries
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    logging.getLogger("discord.client").setLevel(logging.INFO)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger with proper configuration."""
    return logging.getLogger(name)

