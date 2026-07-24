import logging

from investor_intel.logging_config import configure_logging


def test_configure_logging_returns_working_logger(caplog) -> None:
    logger = configure_logging(level=logging.INFO)
    with caplog.at_level(logging.INFO):
        logger.info("test_event", key="value")
    assert any("test_event" in record.message for record in caplog.records)
