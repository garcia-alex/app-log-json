.PHONY: sync upgrade pre-commit pre-commit-all test build release-check release

NAME := $(shell grep -m1 '^name' pyproject.toml | cut -d'"' -f2)
VERSION := $(shell grep -m1 '^version' pyproject.toml | cut -d'"' -f2)

# Creates .venv if missing (same prompt + macOS flag fix as the scaffold),
# then installs the locked deps. Idempotent; the wt pre-start hook runs it.
sync:
	uv venv --allow-existing --prompt venv-$(NAME)
	@[ "$$(uname)" != Darwin ] || chflags nohidden .venv
	uv sync --frozen

upgrade:
	uv lock --upgrade
	uv sync --frozen

pre-commit:
	@git symbolic-ref -q refs/remotes/origin/HEAD >/dev/null || git remote set-head origin -a
	uv run --frozen pre-commit run --files $$(git diff --name-only origin/HEAD...HEAD)

pre-commit-all:
	uv run --frozen pre-commit run --all-files

test:
	uv run --frozen pytest tests/

# uv publish uploads every file in dist/, so never build onto a stale one.
build:
	rm -rf dist
	uv build

# Everything `release` refuses to proceed on. Safe to run on its own.
release-check:
	@test "$$(git branch --show-current)" = "main" \
		|| { echo "ERROR: not on main"; exit 1; }
	@test -z "$$(git status --porcelain)" \
		|| { echo "ERROR: working tree is dirty"; exit 1; }
	@git fetch --quiet origin main
	@test "$$(git rev-parse HEAD)" = "$$(git rev-parse origin/main)" \
		|| { echo "ERROR: main is not in sync with origin/main"; exit 1; }
	@! git rev-parse -q --verify refs/tags/v$(VERSION) >/dev/null \
		|| { echo "ERROR: tag v$(VERSION) already exists locally"; exit 1; }
	@test -z "$$(git ls-remote --tags origin refs/tags/v$(VERSION))" \
		|| { echo "ERROR: tag v$(VERSION) already exists on origin"; exit 1; }
	@test "$$(curl -s -o /dev/null -w '%{http_code}' https://pypi.org/pypi/$(NAME)/$(VERSION)/json)" != "200" \
		|| { echo "ERROR: $(NAME) $(VERSION) is already on PyPI and cannot be replaced"; exit 1; }
	@test -n "$$UV_PUBLISH_TOKEN" \
		|| { echo "ERROR: UV_PUBLISH_TOKEN is not set"; exit 1; }
	@echo "Ready to release $(NAME) v$(VERSION)"

# Assumes the version bump has already landed on main: pre-commit blocks
# committing to main, so the bump goes through its own PR first.
release: release-check test build
	git tag -a v$(VERSION) -m "v$(VERSION)"
	git push origin v$(VERSION)
	uv publish
	gh release create v$(VERSION) --title "v$(VERSION)" --generate-notes --verify-tag
	@echo "Released $(NAME) v$(VERSION) -> https://pypi.org/project/$(NAME)/$(VERSION)/"
