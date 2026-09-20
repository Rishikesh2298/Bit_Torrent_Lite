"""
BitTorrent-Lite: Centralized Logging

Usage in any module:
    from bittorrent_lite.logger import get_logger
    logger = get_logger("TRACKER")
    logger.info("Peer registered: %s", peer_id)

Log output format:
    [14:32:01] [TRACKER     ] INFO    Peer registered: peer-001
"""

import logging
import sys

from bittorrent_lite.config import LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT


def get_logger(name: str) -> logging.Logger:
    """
    Create and return a named logger with console output.

    Args:
        name: Logger name (e.g., "TRACKER", "PEER-001", "CONNECTION").
              This appears in the log output for easy filtering.

    Returns:
        Configured logging.Logger instance.
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers if get_logger is called multiple times
    if not logger.handlers:
        logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

        formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
        console_handler.setFormatter(formatter)

        logger.addHandler(console_handler)

    return logger
