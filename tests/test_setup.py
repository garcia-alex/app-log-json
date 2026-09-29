import datetime as dt
import json
import logging
import logging.handlers
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from app_log_json import HiveDailyFileHandler, build_config, get_logger, setup_logging
from app_log_json.config import find_project_root, resolve_log_dir
from app_log_json.setup import _install_queue_listener


@pytest.fixture(autouse=True)
def _reset_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    original_excepthook = sys.excepthook
    yield
    for handler in root.handlers:
        if isinstance(handler, logging.handlers.QueueHandler):
            listener = getattr(handler, "listener", None)
            if listener is not None:
                listener.stop()
    root.handlers = original_handlers
    root.setLevel(original_level)
    sys.excepthook = original_excepthook


def _hive_path(base_dir: Path, filename: str, *, at: dt.datetime | None = None) -> Path:
    at = at or dt.datetime.now(tz=dt.UTC)
    return (
        base_dir / f"year={at.year:04d}" / f"month={at.month:02d}" / f"day={at.day:02d}" / filename
    )


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

    log_file = _hive_path(tmp_path, "t.log.jsonl")
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


def test_log_dir_defaults_to_project_root_local_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").touch()
    nested = tmp_path / "src" / "pkg"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    monkeypatch.delenv("LOG_DIR", raising=False)

    assert resolve_log_dir() == tmp_path.resolve() / ".local" / "logs"


def test_log_dir_falls_back_to_cwd_without_root_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert find_project_root(tmp_path) == tmp_path.resolve()


def test_log_dir_env_var_overrides_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "env-logs"))

    config = build_config("t")
    handlers = config["handlers"]
    assert isinstance(handlers, dict)
    assert handlers["file"]["base_dir"] == tmp_path / "env-logs"
    assert handlers["file"]["filename"] == "t.log.jsonl"


def test_explicit_log_dir_beats_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "env-logs"))
    assert resolve_log_dir(tmp_path / "explicit") == tmp_path / "explicit"


def test_mutable_args_are_rendered_at_call_time(tmp_path: Path) -> None:
    config = build_config("t", log_dir=tmp_path)
    setup_logging(config)

    payload = {"state": "BEFORE"}
    get_logger("t").info("value=%s", payload)
    payload["state"] = "AFTER"

    _stop_listener()

    log_file = _hive_path(tmp_path, "t.log.jsonl")
    logged = json.loads(log_file.read_text().splitlines()[0])
    assert logged["message"] == "value={'state': 'BEFORE'}"


def test_hive_handler_accepts_a_string_base_dir(tmp_path: Path) -> None:
    handler = HiveDailyFileHandler(base_dir=str(tmp_path), filename="t.log.jsonl")
    handler.setFormatter(logging.Formatter("%(message)s"))

    handler.emit(logging.LogRecord("t", logging.INFO, __file__, 1, "hello", None, None))
    handler.close()

    assert _hive_path(tmp_path, "t.log.jsonl").read_text() == "hello\n"


def test_hive_handler_reuses_one_handle_per_day_and_rolls_over(tmp_path: Path) -> None:
    handler = HiveDailyFileHandler(base_dir=tmp_path, filename="t.log.jsonl")
    handler.setFormatter(logging.Formatter("%(message)s"))

    late = dt.datetime(2026, 3, 14, 23, 59, tzinfo=dt.UTC)
    later = dt.datetime(2026, 3, 14, 23, 59, 30, tzinfo=dt.UTC)
    next_day = dt.datetime(2026, 3, 15, 0, 1, tzinfo=dt.UTC)

    def emit_at(at: dt.datetime, message: str) -> None:
        record = logging.LogRecord("t", logging.INFO, __file__, 1, message, None, None)
        record.created = at.timestamp()
        handler.emit(record)

    emit_at(late, "before midnight")
    handle = handler._stream
    emit_at(later, "still before midnight")
    assert handler._stream is handle

    emit_at(next_day, "after midnight")
    assert handler._stream is not handle
    handler.close()

    day_one = _hive_path(tmp_path, "t.log.jsonl", at=late)
    assert day_one.read_text() == "before midnight\nstill before midnight\n"
    assert _hive_path(tmp_path, "t.log.jsonl", at=next_day).read_text() == "after midnight\n"


def test_unhandled_exception_is_logged_as_critical(tmp_path: Path) -> None:
    config = build_config("t", log_dir=tmp_path)
    setup_logging(config)

    try:
        raise ValueError("boom")
    except ValueError:
        exc_type, exc_value, exc_tb = sys.exc_info()
    assert exc_type is not None
    assert exc_value is not None

    sys.excepthook(exc_type, exc_value, exc_tb)
    _stop_listener()

    log_file = _hive_path(tmp_path, "t.log.jsonl")
    lines = log_file.read_text().splitlines()
    payloads = [json.loads(line) for line in lines]
    critical = next(p for p in payloads if p["level"] == "CRITICAL")
    assert critical["message"] == "Unhandled exception"
    assert "ValueError: boom" in critical["exc_info"]


def test_double_setup_does_not_chain_excepthooks(tmp_path: Path) -> None:
    config = build_config("t", log_dir=tmp_path)
    setup_logging(config)
    installed_hook = sys.excepthook
    setup_logging(config)

    assert sys.excepthook is installed_hook
    _stop_listener()


def test_double_setup_does_not_leak_a_listener_thread(tmp_path: Path) -> None:
    config = build_config("t", log_dir=tmp_path)
    before = threading.active_count()

    setup_logging(config)
    setup_logging(config)
    setup_logging(config)

    assert threading.active_count() == before + 1
    _stop_listener()
    assert threading.active_count() == before


def test_crash_traceback_is_not_duplicated_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = build_config("t", log_dir=tmp_path)
    setup_logging(config)

    try:
        raise ValueError("boom")
    except ValueError:
        exc_type, exc_value, exc_tb = sys.exc_info()
    assert exc_type is not None
    assert exc_value is not None

    sys.excepthook(exc_type, exc_value, exc_tb)
    _stop_listener()

    captured = capsys.readouterr()
    assert captured.err.count("Traceback (most recent call last):") == 1
    assert "[CRITICAL" not in captured.err

    log_file = _hive_path(tmp_path, "t.log.jsonl")
    logged = json.loads(log_file.read_text().splitlines()[0])
    assert logged["level"] == "CRITICAL"
    assert "_crash_report" not in logged


def test_keyboard_interrupt_is_not_logged(tmp_path: Path) -> None:
    config = build_config("t", log_dir=tmp_path)
    setup_logging(config)

    try:
        raise KeyboardInterrupt
    except KeyboardInterrupt:
        exc_type, exc_value, exc_tb = sys.exc_info()
    assert exc_type is not None
    assert exc_value is not None

    sys.excepthook(exc_type, exc_value, exc_tb)
    _stop_listener()

    log_file = _hive_path(tmp_path, "t.log.jsonl")
    assert not log_file.exists()
