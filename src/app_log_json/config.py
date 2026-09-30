import os
from pathlib import Path

from app_log_json.formatter import JSONFormatter
from app_log_json.hive import HiveDailyFileHandler
from app_log_json.setup import ExcludeCrashReports

LOG_DIR_ENV_VAR = "LOG_DIR"
PROJECT_ROOT_MARKERS = ("pyproject.toml", ".git")
DEFAULT_RETENTION_DAYS = 30


def find_project_root(start: Path | None = None) -> Path:
    """Nearest ancestor of ``start`` (default: CWD) holding a root marker, else ``start``."""
    start = (start or Path.cwd()).resolve()
    for directory in (start, *start.parents):
        if any((directory / marker).exists() for marker in PROJECT_ROOT_MARKERS):
            return directory
    return start


def resolve_log_dir(log_dir: Path | None = None) -> Path:
    """Explicit ``log_dir``, then ``$LOG_DIR``, then ``<project root>/.local/logs``."""
    if log_dir is not None:
        return log_dir
    if env_dir := os.environ.get(LOG_DIR_ENV_VAR):
        return Path(env_dir).expanduser()
    return find_project_root() / ".local" / "logs"


def build_config(
    app_name: str,
    log_dir: Path | None = None,
    *,
    console_level: str = "WARNING",
    file_level: str = "DEBUG",
    root_level: str = "DEBUG",
    retention_days: int | None = DEFAULT_RETENTION_DAYS,
) -> dict[str, object]:
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
                "filters": ["exclude_crash_reports"],
                "stream": "ext://sys.stderr",
            },
            "file": {
                "()": HiveDailyFileHandler,
                "level": file_level,
                "formatter": "json",
                "base_dir": resolve_log_dir(log_dir),
                "filename": f"{app_name}.log.jsonl",
                "retention_days": retention_days,
            },
        },
        "loggers": {
            "root": {
                "level": root_level,
                "handlers": ["stderr", "file"],
            },
        },
    }
