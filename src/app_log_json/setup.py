import atexit
import json
import logging
import logging.config
import logging.handlers
from pathlib import Path
from queue import Queue


def setup_logging(config: Path | str | dict[str, object] | None = None) -> None:
    resolved_config = _resolve_config(config)
    _ensure_file_handler_dirs(resolved_config)
    logging.config.dictConfig(resolved_config)
    _install_queue_listener()


def _resolve_config(config: Path | str | dict[str, object] | None) -> dict[str, object]:
    if config is None:
        return {
            "version": 1,
            "disable_existing_loggers": False,
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


def _install_queue_listener() -> None:
    root = logging.getLogger()
    handlers = root.handlers
    if len(handlers) == 1 and isinstance(handlers[0], logging.handlers.QueueHandler):
        return

    real_handlers = list(handlers)
    queue: Queue[logging.LogRecord] = Queue()
    queue_handler = logging.handlers.QueueHandler(queue)
    root.handlers = [queue_handler]

    listener = logging.handlers.QueueListener(queue, *real_handlers, respect_handler_level=True)
    queue_handler.listener = listener  # mirrors stdlib dictConfig's convention (3.12+)
    listener.start()
    atexit.register(listener.stop)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
