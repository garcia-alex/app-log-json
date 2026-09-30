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
  library is importable. The handler takes `base_dir` (a path string is fine),
  `filename` and an optional `retention_days`.

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

### Retention

Daily partitioning has no size cap, so `build_config()` sets
`retention_days=30`: a day's partition is deleted once it is more than 30 days
old. Pass a different number, or `retention_days=None` to keep everything.

```python
setup_logging(build_config("my_app", retention_days=7))
```

Pruning is driven by the partition path, not by `mtime`, so a log tree that
was copied or rsync'd still expires by the day each record was written. It
runs whenever the handler opens a file — the first write of a process and each
crossing of UTC midnight — so a short cron run prunes at startup and a
long-lived daemon prunes as it rolls over. A prune that fails never costs a
log line.

Only `<app_name>.log.jsonl` is removed from an expired partition, because a
shared `LOG_DIR` holds other apps' files (with their own retention) beside it;
the `day=`/`month=`/`year=` directories go only once that emptied them.
Directories that don't parse as a partition are never touched.

To prune a tree without logging to it — from a cleanup job, say:

```python
from app_log_json import prune_partitions

prune_partitions("/var/log/my_app", "my_app.log.jsonl", keep_days=30)
```

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

### Releasing

```bash
make release-check   # preflight guards only — safe to run any time
make build           # rm -rf dist, then uv build
make release         # guards, test, build, tag, push, publish, GitHub release
```

**First**, bump `version` in `pyproject.toml` and run `uv lock`, then land it
via its own PR — pre-commit blocks committing to `main`. The lock records the
project's own version, so bumping `pyproject.toml` alone leaves it stale and
every `uv run --frozen` refuses to start.

**Then**, with the bump on `main`, `make release` tags `v<version>`, pushes
the tag, publishes to PyPI and cuts the GitHub release. It publishes before
creating the release, so the release only appears once the artifact is live.

`make release-check` holds the guards, and refuses to proceed unless: on
`main`, clean tree, in sync with `origin`, the tag is free both locally and on
origin, the version is absent from PyPI (it can never be re-uploaded), and
`UV_PUBLISH_TOKEN` is set. Run it alone to check readiness without releasing.

`make build` always clears `dist/` first, because `uv publish` uploads every
file in that directory — a leftover artifact would otherwise ship too.
