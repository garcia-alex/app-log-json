import datetime as dt
import io
import logging
from pathlib import Path


class HiveDailyFileHandler(logging.Handler):
    """Appends each record to ``base_dir/year=YYYY/month=MM/day=DD/filename`` by its timestamp."""

    def __init__(self, base_dir: Path | str, filename: str, *, encoding: str = "utf-8") -> None:
        super().__init__()
        # A JSON dictConfig file can only supply base_dir as a string.
        self.base_dir = Path(base_dir)
        self.filename = filename
        self.encoding = encoding
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
        return self._stream

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
