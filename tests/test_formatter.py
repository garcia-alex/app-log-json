import datetime as dt
import json
import logging

from app_log_json.formatter import JSONFormatter


def _make_record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=None,
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_format_produces_expected_keys() -> None:
    formatter = JSONFormatter(
        fmt_keys={"level": "levelname", "message": "message", "logger": "name"}
    )
    record = _make_record()

    payload = json.loads(formatter.format(record))

    assert payload["level"] == "INFO"
    assert payload["message"] == "hello"
    assert payload["logger"] == "test"


def test_format_emits_iso8601_utc_timestamp() -> None:
    formatter = JSONFormatter()
    record = _make_record()

    payload = json.loads(formatter.format(record))

    timestamp = dt.datetime.fromisoformat(payload["timestamp"])
    assert timestamp.tzinfo is not None
    assert timestamp.utcoffset() == dt.timedelta(0)


def test_format_includes_extra_attrs() -> None:
    formatter = JSONFormatter()
    record = _make_record(x="hello")

    payload = json.loads(formatter.format(record))

    assert payload["x"] == "hello"


def test_format_includes_exc_info() -> None:
    formatter = JSONFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _make_record(exc_info=sys.exc_info())

    payload = json.loads(formatter.format(record))

    assert "ValueError: boom" in payload["exc_info"]
