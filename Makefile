.PHONY: pre-commit pre-commit-all test

pre-commit:
	@git symbolic-ref -q refs/remotes/origin/HEAD >/dev/null || git remote set-head origin -a
	uv run --frozen pre-commit run --files $$(git diff --name-only origin/HEAD...HEAD)

pre-commit-all:
	uv run --frozen pre-commit run --all-files

test:
	uv run --frozen pytest tests/
