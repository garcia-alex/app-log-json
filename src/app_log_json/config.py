from pathlib import Path

from app_log_json.formatter import JSONFormatter


def build_config(
    app_name: str,
    log_dir: Path = Path("logs"),
    *,
    console_level: str = "WARNING",
    file_level: str = "DEBUG",
    root_level: str = "DEBUG",
    max_bytes: int = 10 * 1024 * 1024,
    backups: int = 5,
) -> dict[str, object]:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "detailed": {
                "format": "[%(levelname)s|%(module)s|L%(lineno)d] %(asctime)s: %(message)s",
                "datefmt": "%Y-%m-%dT%H:%M:%S%z",
            },
            "json": {
                "()": JSONFormatter,
                "fmt_keys": {
                    "level": "levelname",
                    "message": "message",
                    "timestamp": "timestamp",
                    "logger": "name",
                    "module": "module",
                    "function": "funcName",
                    "line": "lineno",
                    "thread_name": "threadName",
                },
            },
        },
        "handlers": {
            "stderr": {
                "class": "logging.StreamHandler",
                "level": console_level,
                "formatter": "detailed",
                "stream": "ext://sys.stderr",
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": file_level,
                "formatter": "json",
                "filename": str(log_dir / f"{app_name}.log.jsonl"),
                "maxBytes": max_bytes,
                "backupCount": backups,
            },
        },
        "loggers": {
            "root": {
                "level": root_level,
                "handlers": ["stderr", "file"],
            },
        },
    }
