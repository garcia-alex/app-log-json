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
- `setup_logging(build_config(...))` — stderr (text) + rotating JSON file at
  `<log_dir>/<app_name>.log.jsonl`.
- `setup_logging(Path("logging.json"))` — load a JSON `dictConfig` file; a
  `"()": "app_log_json.JSONFormatter"` reference resolves because the library
  is importable.

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

## Development

```bash
make test
make pre-commit-all
```
