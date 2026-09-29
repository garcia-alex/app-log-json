import atexit
import copy
import json
import logging
import logging.config
import logging.handlers
import sys
from collections.abc import Callable
from pathlib import Path
from queue import Queue
from types import TracebackType


def setup_logging(config: Path | str | dict[str, object] | None = None) -> None:
    resolved_config = _resolve_config(config)
    _ensure_file_handler_dirs(resolved_config)
    logging.config.dictConfig(resolved_config)
    _install_queue_listener()
    _install_excepthook()


def _resolve_config(config: Path | str | dict[str, object] | None) -> dict[str, object]:
    if config is None:
        return {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "exclude_crash_reports": {"()": ExcludeCrashReports},
            },
            "formatters": {
                "detailed": {
                    "format": "[%(levelname)s|%(module)s|L%(lineno)d] %(asctime)s: %(message)s",
                    "datefmt": "%Y-%m-%dT%H:%M:%S%z",
                },
            },
            "handlers": {
                "stderr": {
                    "class": "logging.StreamHandler",
                    "level": "WARNING",
                    "formatter": "detailed",
                    "filters": ["exclude_crash_reports"],
                    "stream": "ext://sys.stderr",
                },
            },
            "loggers": {
                "root": {
                    "level": "DEBUG",
                    "handlers": ["stderr"],
                },
            },
        }
    if isinstance(config, Path | str):
        return json.loads(Path(config).read_text())
    return config


def _ensure_file_handler_dirs(config: dict[str, object]) -> None:
    handlers = config.get("handlers", {})
    if not isinstance(handlers, dict):
        return
    for handler in handlers.values():
        if not isinstance(handler, dict):
            continue
        if handler.get("class") != "logging.handlers.RotatingFileHandler":
            continue
        filename = handler.get("filename")
        if isinstance(filename, str):
            Path(filename).parent.mkdir(parents=True, exist_ok=True)


class _RawQueueHandler(logging.handlers.QueueHandler):
    # Render args on the calling thread (base prepare() does this too, so a
    # mutable arg logs its value at call time) but keep exc_info/stack_info
    # live, which base prepare() drops to stay picklable across processes.
    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        record = copy.copy(record)
        record.msg = record.getMessage()
        record.args = None
        return record


_listener: logging.handlers.QueueListener | None = None


def _install_queue_listener() -> None:
    global _listener
    root = logging.getLogger()
    handlers = root.handlers
    if len(handlers) == 1 and isinstance(handlers[0], logging.handlers.QueueHandler):
        return

    # dictConfig() has already swapped root.handlers, so the guard above cannot
    # see a previous run; retire its listener here or its thread outlives us.
    if _listener is not None:
        _listener.stop()
        atexit.unregister(_listener.stop)

    real_handlers = list(handlers)
    queue: Queue[logging.LogRecord] = Queue()
    queue_handler = _RawQueueHandler(queue)
    root.handlers = [queue_handler]

    listener = logging.handlers.QueueListener(queue, *real_handlers, respect_handler_level=True)
    queue_handler.listener = listener  # mirrors stdlib dictConfig's convention (3.12+)
    listener.start()
    atexit.register(listener.stop)
    _listener = listener


CRASH_RECORD_ATTR = "_crash_report"


class ExcludeCrashReports(logging.Filter):
    """Drops the excepthook's crash record — ``sys.excepthook`` prints that traceback itself."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not getattr(record, CRASH_RECORD_ATTR, False)


_original_excepthook: (
    Callable[[type[BaseException], BaseException, TracebackType | None], None] | None
) = None


def _install_excepthook() -> None:
    global _original_excepthook
    if sys.excepthook is _excepthook:
        return
    _original_excepthook = sys.excepthook
    sys.excepthook = _excepthook


def _excepthook(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    if not issubclass(exc_type, KeyboardInterrupt):
        logging.getLogger().critical(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, exc_tb),
            extra={CRASH_RECORD_ATTR: True},
        )
    if _original_excepthook is not None:
        _original_excepthook(exc_type, exc_value, exc_tb)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
