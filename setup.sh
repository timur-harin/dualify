#!/usr/bin/env bash
set -euo pipefail

echo "[1/8] Checking prerequisites..."
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

MODEL_NAME="${DUALIFY_MODEL:-qwen2.5:3b-instruct}"

echo "[2/8] Checking Ollama installation..."
if ! command -v ollama >/dev/null 2>&1; then
  echo "ollama not found."
  if command -v brew >/dev/null 2>&1; then
    echo "Installing ollama via Homebrew..."
    brew install ollama
  else
    echo "Homebrew is not available. Install Ollama manually: https://ollama.com/download"
    exit 1
  fi
fi

echo "[3/8] Ensuring Ollama service is reachable..."
if ! curl -fsS "http://127.0.0.1:11434/api/version" >/dev/null; then
  if command -v brew >/dev/null 2>&1; then
    echo "Trying to start Ollama service via Homebrew..."
    brew services start ollama || true
  fi
fi
if ! curl -fsS "http://127.0.0.1:11434/api/version" >/dev/null; then
  echo "ollama server not reachable at http://127.0.0.1:11434"
  echo "start it with: ollama serve"
  exit 1
fi
echo "ollama server: ok"

echo "[4/8] Pulling model: ${MODEL_NAME}"
ollama pull "${MODEL_NAME}"

echo "[5/8] Configuring Poetry local virtualenv..."
poetry config virtualenvs.in-project true --local

echo "[6/8] Using python3 interpreter for environment..."
poetry env use python3

echo "[7/8] Installing project dependencies..."
poetry install

echo "[8/8] Installing pre-commit hooks and running import checks..."
poetry run pre-commit install
poetry run python -c "import requests, z3; print('python deps: ok')"

echo
echo "Setup complete."
echo "Model ready:"
echo "  ${MODEL_NAME}"
echo "Quality checks:"
echo "  poetry run ruff check ."
echo "  poetry run mypy"
echo "  poetry run pytest"
echo "Run experiment:"
echo "  poetry run python scripts/run_experiment.py --model qwen2.5:3b-instruct --benchmark synthetic"

