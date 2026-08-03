"""Structured logging configuration."""

import logging
import sys

from app.core.config import get_settings


def configure_logging() -> None:
    """Configure root logging with a structured, timestamped format."""
    settings = get_settings()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(settings.log_level)
    root_logger.handlers = [handler]
