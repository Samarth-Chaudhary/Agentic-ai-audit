.PHONY: help install lint test validate reproduce benchmark clean

PYTHON ?= python

help:
	@echo "AI Agent Governance & Audit Trail Analyzer"
	@echo "Available targets:"
	@echo "  install   Install dependencies from requirements.txt"
	@echo "  lint      Run ruff check without bypasses"
	@echo "  test      Run pytest foundation test suite"
	@echo "  validate  Validate sample fixture trace"
	@echo "  reproduce Verify all published README metrics match outputs"
	@echo "  benchmark Regenerate all evaluation benchmarks and calibrations"
	@echo "  clean     Remove python cache and temporary test artifacts"

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

lint:
	$(PYTHON) -m ruff check .

test:
	$(PYTHON) -m pytest -v

validate:
	$(PYTHON) scripts/validate_trace.py fixtures/valid_trace.json

reproduce:
	$(PYTHON) scripts/reproduce_all_metrics.py --verify-all

benchmark:
	$(PYTHON) scripts/reproduce_all_metrics.py --regenerate-all

clean:
	$(PYTHON) -c "import pathlib, shutil; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]; [p.unlink(missing_ok=True) for p in pathlib.Path('.').rglob('*.py[cod]')]; [shutil.rmtree(p, ignore_errors=True) for p in ['.pytest_cache', '.ruff_cache', '.mypy_cache', '.coverage', 'htmlcov'] if pathlib.Path(p).exists()]"

