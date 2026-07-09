"""Shared logging configuration for CLI and server processes."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(
    name: str = "thunder",
    level: int = logging.INFO,
    log_to_file: bool = True,
) -> logging.Logger:
    """Configure a logger with consistent formatting for stdout and file.

    This is idempotent: calling it multiple times for the same logger will
    not add duplicate handlers.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")

    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    if log_to_file:
        if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
            base_dir = Path(__file__).resolve().parent.parent
            logs_dir = base_dir / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                logs_dir / "thunder.log",
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

    return logger
