import logging

from utils.logging_config import setup_logging


setup_logging()

logger = logging.getLogger("test")


logger.info("Logging system initialized successfully.")
logger.warning("This is a test warning.")


try:
    result = 10 / 0
except Exception:
    logger.exception("Test exception occurred.")