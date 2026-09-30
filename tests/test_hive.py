import datetime as dt
import logging
from pathlib import Path

import pytest

from app_log_json import (
    DEFAULT_RETENTION_DAYS,
    HiveDailyFileHandler,
    build_config,
    iter_day_partitions,
    prune_partitions,
)
from app_log_json import hive as hive_module

TODAY = dt.date(2026, 9, 30)


def _partition(base_dir: Path, date: dt.date, filename: str = "t.log.jsonl") -> Path:
    path = (
        base_dir
        / f"year={date.year:04d}"
        / f"month={date.month:02d}"
        / f"day={date.day:02d}"
        / filename
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n")
    return path


def _emit_at(handler: HiveDailyFileHandler, at: dt.datetime, message: str) -> None:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, message, None, None)
    record.created = at.timestamp()
    handler.emit(record)


def test_prune_deletes_only_partitions_older_than_keep_days(tmp_path: Path) -> None:
    stale = _partition(tmp_path, TODAY - dt.timedelta(days=31))
    boundary = _partition(tmp_path, TODAY - dt.timedelta(days=30))
    today = _partition(tmp_path, TODAY)

    assert prune_partitions(tmp_path, "t.log.jsonl", keep_days=30, today=TODAY) == 1

    assert not stale.exists()
    assert boundary.exists()
    assert today.exists()


def test_prune_keeps_today_when_keep_days_is_zero(tmp_path: Path) -> None:
    yesterday = _partition(tmp_path, TODAY - dt.timedelta(days=1))
    today = _partition(tmp_path, TODAY)

    assert prune_partitions(tmp_path, "t.log.jsonl", keep_days=0, today=TODAY) == 1

    assert not yesterday.exists()
    assert today.exists()


def test_prune_leaves_other_apps_files_in_a_shared_partition(tmp_path: Path) -> None:
    stale = _partition(tmp_path, TODAY - dt.timedelta(days=90))
    neighbour = _partition(tmp_path, TODAY - dt.timedelta(days=90), filename="other.log.jsonl")

    assert prune_partitions(tmp_path, "t.log.jsonl", keep_days=30, today=TODAY) == 1

    assert not stale.exists()
    assert neighbour.exists()
    assert stale.parent.is_dir()


def test_prune_removes_emptied_partition_dirs_but_not_base_dir(tmp_path: Path) -> None:
    stale = _partition(tmp_path, dt.date(2025, 1, 5))

    prune_partitions(tmp_path, "t.log.jsonl", keep_days=30, today=TODAY)

    assert not (tmp_path / "year=2025").exists()
    assert not stale.parent.exists()
    assert tmp_path.is_dir()


def test_prune_keeps_a_year_dir_that_still_holds_a_live_partition(tmp_path: Path) -> None:
    _partition(tmp_path, dt.date(2026, 1, 5))
    kept = _partition(tmp_path, TODAY)

    prune_partitions(tmp_path, "t.log.jsonl", keep_days=30, today=TODAY)

    assert kept.exists()
    assert not (tmp_path / "year=2026" / "month=01").exists()
    assert (tmp_path / "year=2026").is_dir()


def test_prune_ignores_paths_it_did_not_write(tmp_path: Path) -> None:
    strays = [
        tmp_path / "year=abc" / "month=01" / "day=05" / "t.log.jsonl",
        tmp_path / "year=2025" / "month=13" / "day=05" / "t.log.jsonl",
        tmp_path / "year=2025" / "month=02" / "day=30" / "t.log.jsonl",
        tmp_path / "notes" / "t.log.jsonl",
    ]
    for stray in strays:
        stray.parent.mkdir(parents=True, exist_ok=True)
        stray.write_text("{}\n")
    stray_file = tmp_path / "year=2025" / "month=01" / "day=05"
    stray_file.parent.mkdir(parents=True, exist_ok=True)
    stray_file.write_text("a file where a partition dir would go")

    assert prune_partitions(tmp_path, "t.log.jsonl", keep_days=30, today=TODAY) == 0

    for stray in strays:
        assert stray.exists()
    assert stray_file.is_file()


def test_iter_day_partitions_yields_well_formed_partitions_in_order(tmp_path: Path) -> None:
    dates = [dt.date(2026, 9, 1), dt.date(2025, 12, 31), dt.date(2026, 1, 2)]
    for date in dates:
        _partition(tmp_path, date)
    (tmp_path / "year=nope").mkdir()

    assert [date for date, _ in iter_day_partitions(tmp_path)] == sorted(dates)


def test_prune_rejects_a_negative_keep_days(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="keep_days"):
        prune_partitions(tmp_path, "t.log.jsonl", keep_days=-1, today=TODAY)


def test_handler_rejects_a_negative_retention_days(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="retention_days"):
        HiveDailyFileHandler(base_dir=tmp_path, filename="t.log.jsonl", retention_days=-1)


def test_handler_prunes_on_the_first_write(tmp_path: Path) -> None:
    stale = _partition(tmp_path, TODAY - dt.timedelta(days=31))
    handler = HiveDailyFileHandler(base_dir=tmp_path, filename="t.log.jsonl", retention_days=30)
    handler.setFormatter(logging.Formatter("%(message)s"))

    _emit_at(handler, dt.datetime(2026, 9, 30, 9, 0, tzinfo=dt.UTC), "hello")
    handler.close()

    assert not stale.exists()


def test_handler_prunes_again_at_the_day_rollover(tmp_path: Path) -> None:
    handler = HiveDailyFileHandler(base_dir=tmp_path, filename="t.log.jsonl", retention_days=1)
    handler.setFormatter(logging.Formatter("%(message)s"))

    first = dt.datetime(2026, 9, 30, 23, 59, tzinfo=dt.UTC)
    second = dt.datetime(2026, 10, 1, 0, 1, tzinfo=dt.UTC)
    third = dt.datetime(2026, 10, 2, 0, 1, tzinfo=dt.UTC)

    _emit_at(handler, first, "day one")
    _emit_at(handler, second, "day two")
    _emit_at(handler, third, "day three")
    handler.close()

    # keep_days=1 at 2026-10-02 drops 2026-09-30 and keeps 2026-10-01 onward.
    assert not (tmp_path / "year=2026" / "month=09").exists()
    assert (tmp_path / "year=2026" / "month=10" / "day=01" / "t.log.jsonl").exists()
    assert (tmp_path / "year=2026" / "month=10" / "day=02" / "t.log.jsonl").exists()


def test_handler_without_retention_keeps_everything(tmp_path: Path) -> None:
    stale = _partition(tmp_path, dt.date(2020, 1, 1))
    handler = HiveDailyFileHandler(base_dir=tmp_path, filename="t.log.jsonl")
    handler.setFormatter(logging.Formatter("%(message)s"))

    _emit_at(handler, dt.datetime(2026, 9, 30, 9, 0, tzinfo=dt.UTC), "hello")
    handler.close()

    assert stale.exists()


def test_a_failing_prune_does_not_cost_a_log_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[tuple[object, ...]] = []

    def explode(*args: object, **kwargs: object) -> int:
        attempts.append((args, kwargs))
        raise OSError("partition tree vanished")

    monkeypatch.setattr(hive_module, "prune_partitions", explode)
    handler = HiveDailyFileHandler(base_dir=tmp_path, filename="t.log.jsonl", retention_days=30)
    handler.setFormatter(logging.Formatter("%(message)s"))

    _emit_at(handler, dt.datetime(2026, 9, 30, 9, 0, tzinfo=dt.UTC), "hello")
    handler.close()

    written = tmp_path / "year=2026" / "month=09" / "day=30" / "t.log.jsonl"
    assert attempts
    assert written.read_text() == "hello\n"


def test_build_config_defaults_to_thirty_day_retention(tmp_path: Path) -> None:
    handlers = build_config("t", log_dir=tmp_path)["handlers"]
    assert isinstance(handlers, dict)
    assert DEFAULT_RETENTION_DAYS == 30
    assert handlers["file"]["retention_days"] == DEFAULT_RETENTION_DAYS


def test_build_config_retention_days_is_overridable(tmp_path: Path) -> None:
    handlers = build_config("t", log_dir=tmp_path, retention_days=None)["handlers"]
    assert isinstance(handlers, dict)
    assert handlers["file"]["retention_days"] is None
