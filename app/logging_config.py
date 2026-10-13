from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


class SafeStreamHandler(logging.StreamHandler):
    """Stream handler that safely formats log records without failing on terminal encoding limits."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            super().emit(record)
        except UnicodeEncodeError:
            msg = self.format(record)
            enc = getattr(self.stream, "encoding", "utf-8") or "utf-8"
            safe_msg = msg.encode(enc, errors="backslashreplace").decode(enc)
            self.stream.write(safe_msg + self.terminator)
            self.flush()


def setup_logging(
    log_level: str = "INFO",
    log_file: str | Path | None = "logs/bot.log",
) -> None:
    """Configure robust, unified structured logging for both terminal console and persistent file."""
    # Ensure stdout and stderr use utf-8 if possible
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if isinstance(log_level, str):
        numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    else:
        numeric_level = logging.INFO
    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATEFMT)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Remove existing handlers to prevent duplicate lines
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    # 1. Console Stream Handler (sys.stdout)
    console_handler = SafeStreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 2. Rotating File Handler
    if log_file and isinstance(log_file, (str, Path)):
        file_path = Path(log_file)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            str(file_path),
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Set appropriate levels on common loggers
    logging.getLogger("app").setLevel(numeric_level)
    logging.getLogger("aiogram").setLevel(numeric_level)
    logging.getLogger("aiogram.event").setLevel(numeric_level)
    logging.getLogger("aiogram.dispatcher").setLevel(numeric_level)
    logging.getLogger("alembic").setLevel(numeric_level)

    # Prevent noisy SQL queries unless in DEBUG
    if numeric_level > logging.DEBUG:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logging configured at level %s (terminal: stdout, file: %s)",
        log_level.upper(),
        str(log_file) if log_file else "none",
    )
