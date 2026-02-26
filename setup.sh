#!/usr/bin/env bash
set -euo pipefail

echo "[1/7] Checking prerequisites..."
command -v python3 >/dev/null 2>&1 || {
  echo "python3 is required but not found."
  exit 1
}
command -v curl >/dev/null 2>&1 || {
  echo "curl is required but not found."
  exit 1
}
command -v poetry >/dev/null 2>&1 || {
  echo "Poetry is required. Install: https://python-poetry.org/docs/#installation"
  exit 1
}

echo "[2/7] Configuring Poetry local virtualenv..."
poetry config virtualenvs.in-project true --local

echo "[3/7] Using python3 interpreter for environment..."
poetry env use python3

echo "[4/7] Installing project dependencies..."
poetry install

echo "[5/7] Installing pre-commit hooks..."
poetry run pre-commit install

echo "[6/7] Running basic import checks..."
poetry run python -c "import requests, z3; print('python deps: ok')"

echo "[7/7] Checking Ollama endpoint..."
if curl -fsS "http://127.0.0.1:11434/api/version" >/dev/null; then
  echo "ollama server: ok"
else
  echo "ollama server not reachable at http://127.0.0.1:11434"
  echo "start it with: ollama serve"
fi

echo
echo "Setup complete."
echo "Quality checks:"
echo "  poetry run ruff check ."
echo "  poetry run mypy"
echo "  poetry run pytest"
echo "Run experiment:"
echo "  poetry run python scripts/run_experiment.py --model qwen2.5:3b-instruct --benchmark synthetic"

