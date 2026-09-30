import contextlib
import datetime as dt
import io
import logging
from collections.abc import Iterator
from pathlib import Path

PARTITION_PREFIXES = ("year=", "month=", "day=")


def iter_day_partitions(base_dir: Path | str) -> Iterator[tuple[dt.date, Path]]:
    """Yields ``(date, directory)`` for every well-formed ``year=/month=/day=`` partition."""
    base_dir = Path(base_dir)
    for year_dir in sorted(base_dir.glob("year=*")):
        for month_dir in sorted(year_dir.glob("month=*")):
            for day_dir in sorted(month_dir.glob("day=*")):
                if not day_dir.is_dir():
                    continue
                names = (year_dir.name, month_dir.name, day_dir.name)
                try:
                    year, month, day = (
                        int(name.removeprefix(prefix))
                        for name, prefix in zip(names, PARTITION_PREFIXES, strict=True)
                    )
                    date = dt.date(year, month, day)
                except ValueError:
                    # Not a partition this library wrote — leave it alone.
                    continue
                yield date, day_dir


def prune_partitions(
    base_dir: Path | str,
    filename: str,
    *,
    keep_days: int,
    today: dt.date | None = None,
) -> int:
    """Deletes ``filename`` from day partitions older than ``keep_days``; returns the count.

    The partition path carries the date, so nothing is stat'ed — a copied or
    rsync'd tree prunes by the day it was logged, not the day it was written.
    Only ``filename`` is removed, because a shared log directory holds other
    apps' files (with their own retention) beside it; the partition directories
    are then removed if that emptied them. ``keep_days=0`` keeps only today.
    """
    if keep_days < 0:
        msg = f"keep_days must not be negative, got {keep_days}"
        raise ValueError(msg)
    base_dir = Path(base_dir)
    cutoff = (today or dt.datetime.now(tz=dt.UTC).date()) - dt.timedelta(days=keep_days)
    removed = 0
    for date, day_dir in iter_day_partitions(base_dir):
        if date >= cutoff:
            continue
        path = day_dir / filename
        if path.is_file():
            path.unlink()
            removed += 1
        _remove_empty_partition_dirs(day_dir, base_dir)
    return removed


def _remove_empty_partition_dirs(day_dir: Path, base_dir: Path) -> None:
    """Removes ``day_dir`` and its emptied ``month=``/``year=`` parents, never ``base_dir``."""
    directory = day_dir
    for _ in range(len(PARTITION_PREFIXES)):
        if directory == base_dir or any(directory.iterdir()):
            return
        directory.rmdir()
        directory = directory.parent


class HiveDailyFileHandler(logging.Handler):
    """Appends each record to ``base_dir/year=YYYY/month=MM/day=DD/filename`` by its timestamp."""

    def __init__(
        self,
        base_dir: Path | str,
        filename: str,
        *,
        encoding: str = "utf-8",
        retention_days: int | None = None,
    ) -> None:
        super().__init__()
        if retention_days is not None and retention_days < 0:
            msg = f"retention_days must not be negative, got {retention_days}"
            raise ValueError(msg)
        # A JSON dictConfig file can only supply base_dir as a string.
        self.base_dir = Path(base_dir)
        self.filename = filename
        self.encoding = encoding
        self.retention_days = retention_days
        self._stream: io.TextIOWrapper | None = None
        self._stream_day: dt.date | None = None

    def _path_for(self, at: dt.datetime) -> Path:
        return (
            self.base_dir
            / f"year={at.year:04d}"
            / f"month={at.month:02d}"
            / f"day={at.day:02d}"
            / self.filename
        )

    def _stream_for(self, at: dt.datetime) -> io.TextIOWrapper:
        if self._stream is None or self._stream_day != at.date():
            self._close_stream()
            path = self._path_for(at)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._stream = path.open("a", encoding=self.encoding)
            self._stream_day = at.date()
            self._prune(at.date())
        return self._stream

    def _prune(self, today: dt.date) -> None:
        # Opening a stream happens on the first write and at each day rollover,
        # so a short cron run prunes at startup and a daemon prunes at midnight.
        if self.retention_days is None:
            return
        # Another process pruning the same tree is not worth a lost log line.
        with contextlib.suppress(OSError):
            prune_partitions(
                self.base_dir, self.filename, keep_days=self.retention_days, today=today
            )

    def _close_stream(self) -> None:
        if self._stream is not None:
            self._stream.close()
        self._stream = None
        self._stream_day = None

    def emit(self, record: logging.LogRecord) -> None:
        # Handler.handle() holds the lock here, so _stream is not raced.
        try:
            stream = self._stream_for(dt.datetime.fromtimestamp(record.created, tz=dt.UTC))
            stream.write(self.format(record) + "\n")
            stream.flush()
        except Exception:
            self.handleError(record)

    def flush(self) -> None:
        self.acquire()
        try:
            if self._stream is not None:
                self._stream.flush()
        finally:
            self.release()

    def close(self) -> None:
        self.acquire()
        try:
            self._close_stream()
        finally:
            self.release()
        super().close()
