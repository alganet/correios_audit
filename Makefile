.PHONY: sync fetch extract normalize verify site clean lint test all

PY := uv run python -m

sync:
	uv sync

fetch:
	$(PY) correios_audit.fetch

extract:
	$(PY) correios_audit.extract

normalize:
	$(PY) correios_audit.normalize.apply

verify:
	$(PY) correios_audit.verify.checks

site:
	$(PY) correios_audit.site.build

all: fetch extract normalize verify site

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

test:
	uv run pytest

clean:
	rm -rf data/interim data/processed data/site
