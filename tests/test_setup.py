import json
import logging
import logging.handlers
from collections.abc import Iterator
from pathlib import Path

import pytest

from app_log_json import build_config, get_logger, setup_logging
from app_log_json.setup import _install_queue_listener


@pytest.fixture(autouse=True)
def _reset_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    yield
    for handler in root.handlers:
        if isinstance(handler, logging.handlers.QueueHandler):
            listener = getattr(handler, "listener", None)
            if listener is not None:
                listener.stop()
    root.handlers = original_handlers
    root.setLevel(original_level)


def _stop_listener() -> None:
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.handlers.QueueHandler):
            listener = getattr(handler, "listener", None)
            if listener is not None:
                listener.stop()


def test_setup_logging_writes_json_file_and_filters_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = build_config("t", log_dir=tmp_path)
    setup_logging(config)

    logger = get_logger("t")
    logger.debug("debug message")
    logger.info("info message")
    logger.warning("warning message")
    logger.error("error message")
    logger.critical("critical message")

    _stop_listener()

    log_file = tmp_path / "t.log.jsonl"
    lines = log_file.read_text().splitlines()
    assert len(lines) == 5
    for line in lines:
        payload = json.loads(line)
        assert "message" in payload

    captured = capsys.readouterr()
    assert "debug message" not in captured.err
    assert "info message" not in captured.err
    assert "warning message" in captured.err
    assert "critical message" in captured.err


def test_setup_logging_installs_single_queue_handler(tmp_path: Path) -> None:
    config = build_config("t", log_dir=tmp_path)
    setup_logging(config)

    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0], logging.handlers.QueueHandler)

    listener = root.handlers[0].listener
    assert listener is not None
    _stop_listener()
    assert listener._thread is None


def test_setup_logging_none_is_stderr_only_and_creates_no_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    setup_logging()

    logger = get_logger("t")
    logger.warning("warning message")

    _stop_listener()

    captured = capsys.readouterr()
    assert "warning message" in captured.err
    assert list(tmp_path.iterdir()) == []


def test_double_init_is_a_noop(tmp_path: Path) -> None:
    config = build_config("t", log_dir=tmp_path)
    setup_logging(config)
    root = logging.getLogger()
    first_handler = root.handlers[0]

    _install_queue_listener()

    assert root.handlers[0] is first_handler
    _stop_listener()
