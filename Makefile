.PHONY: sync fetch extract normalize verify quality site clean lint test all

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

quality:
	$(PY) correios_audit.verify.quality

site: quality
	$(PY) correios_audit.site.build

# Order matters: quality + site run BEFORE verify so the qualidade/ pages are
# always rebuilt — even when verify hard-fails on the brochure era — so you
# can browse the quality dashboard to see which docs need manual_overrides.
# verify runs last so a failing build still exits non-zero for CI.
all: fetch extract normalize quality site verify

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

test:
	uv run pytest

clean:
	rm -rf data/interim data/processed data/site
