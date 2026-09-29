# app-log-json

> This is a public-source project — see [CONTRIBUTING.md](CONTRIBUTING.md)
> for the PR policy.

Typed, non-blocking JSON application logging setup: a `JSONFormatter`, a
`dictConfig`-building helper, and a `setup_logging()` that wires a
`QueueHandler`/`QueueListener` so logging never blocks the calling thread.

Library code must never call `setup_logging()` on import — only an
application's entrypoint should call it.

## Quickstart

```bash
uv add app-log-json
```

```python
from app_log_json import build_config, get_logger, setup_logging

setup_logging(build_config("my_app"))
logger = get_logger("my_app")

logger.info("started", extra={"version": "1.2.3"})
```

## Install

```bash
uv add app-log-json
```

For local development against a sibling checkout instead of the published
package:

```bash
uv add --editable "../app-log-json"
```

## Usage

```python
from app_log_json import build_config, get_logger, setup_logging

setup_logging(build_config("my_app"))
logger = get_logger("my_app")

logger.info("started", extra={"version": "1.2.3"})
```

- `setup_logging(None)` — stderr-only, no file handler, filesystem-safe.
- `setup_logging(build_config(...))` — stderr (text) + a Hive-partitioned
  JSON Lines file at
  `<log_dir>/year=YYYY/month=MM/day=DD/<app_name>.log.jsonl`, one file per
  UTC day.
- `setup_logging(Path("logging.json"))` — load a JSON `dictConfig` file; a
  `"()": "app_log_json.JSONFormatter"` or
  `"()": "app_log_json.HiveDailyFileHandler"` reference resolves because the
  library is importable. The handler takes `base_dir` (a path string is fine)
  and `filename`.

### Log location

`build_config()` picks the log directory in this order:

1. The `log_dir=` argument, if given.
2. The `LOG_DIR` environment variable, if set (`~` is expanded).
3. `<project root>/.local/logs/`, where the project root is the nearest
   ancestor of the current working directory containing `pyproject.toml` or
   `.git` (falling back to the CWD itself).

So an app run anywhere inside, say, `~/git/project` logs to
`~/git/project/.local/logs/` by default. Add `.local/` to the app's
`.gitignore`.

### Unhandled exceptions

`setup_logging()` installs a `sys.excepthook` that logs any exception which
escapes the program as `CRITICAL` (via the `root` logger, so it goes through
the same JSON file handler) before calling through to the previous hook.
`KeyboardInterrupt` is left alone. This only covers exceptions that would
otherwise crash the main thread — wrap background threads in their own
`try`/`except` and call `logger.exception(...)` explicitly.

The terminal still shows exactly the traceback an unmodified Python program
would print, and nothing extra: the crash record carries a marker that the
console handler filters out, so the traceback isn't printed twice. A
hand-written config that wants the same behaviour should add the filter to
its console handler:

```json
"filters": {"exclude_crash_reports": {"()": "app_log_json.ExcludeCrashReports"}},
"handlers": {"stderr": {"filters": ["exclude_crash_reports"], "…": "…"}}
```

## Development

```bash
make test
make pre-commit-all
```
