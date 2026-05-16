import logging
import sys


def setup_logger(
    logger_name: str,
    log_level: str = "INFO"
) -> logging.Logger:

    logger = logging.getLogger(logger_name)

    # Prevent duplicate handlers
    if logger.handlers:
        return logger

    logger.setLevel(log_level.upper())

    formatter = logging.Formatter(
        fmt=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(name)s | "
            "%(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    logger.addHandler(console_handler)

    logger.propagate = False

    return logger