#!/usr/bin/env bash
# Run RQ6 cross-model campaigns on lifted_auto_eval via OpenRouter (paid models).
# Records full LLM transcripts + reports under results/campaigns/ for replay.
#
# Required env:
#   OPENROUTER_API_KEY or OR_KEY
#
# Usage:
#   ./scripts/run_crossmodel_campaigns.sh paid          # Opus 4.8 + GPT-5.5
#   ./scripts/run_crossmodel_campaigns.sh claude        # Anthropic only
#   ./scripts/run_crossmodel_campaigns.sh openai        # OpenAI only
#   OR_CLAUDE_MODEL=anthropic/claude-opus-4.8 ... ./scripts/run_crossmodel_campaigns.sh paid
#   OR_MODEL=... OR_LABEL=... ./scripts/run_crossmodel_campaigns.sh one

set -euo pipefail

ROOT="$(cd "$(dirname "${0}")/.." && pwd)"
cd "${ROOT}"

if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
fi

OR_KEY="${OPENROUTER_API_KEY:-${OR_KEY:-}}"

# Paid proprietary coding models (NOT open-weight Gemma/Llama/etc.).
# Budget est. from Qwen run_01 (~210k tokens / 200 LLM calls per 40-case run):
# Default pair (~$3.6 total on Qwen-scale token load):
#   Anthropic Claude Opus 4.8  (~$1.71/run)
#   OpenAI GPT-5.5             (~$1.87/run)
CLAUDE_MODEL="${OR_CLAUDE_MODEL:-anthropic/claude-opus-4.8}"
CLAUDE_LABEL="${OR_CLAUDE_LABEL:-openrouter_claude_opus48}"
OPENAI_MODEL="${OR_OPENAI_MODEL:-openai/gpt-5.5}"
OPENAI_LABEL="${OR_OPENAI_LABEL:-openrouter_gpt55}"

run_one() {
  local model="$1"
  local label="$2"
  local mode="${3:-fresh}"
  [[ -n "${OR_KEY}" ]] || { echo "missing OPENROUTER_API_KEY / OR_KEY" >&2; exit 2; }

  local out_dir="${ROOT}/results/campaigns/lifted_auto_eval__${label}"
  local log_file="${out_dir}/campaign.log"
  local transcript="${out_dir}/run_01/transcript.jsonl"
  mkdir -p "${out_dir}"

  local extra=(--no-throttle)
  if [[ "${mode}" == "resume" && -f "${transcript}" ]]; then
    extra+=(--resume)
    echo "==> OpenRouter ${model} (resume, label=${label})"
  else
    extra+=(--fresh)
    echo "==> OpenRouter ${model} (fresh 40-case run, label=${label})"
  fi
  echo "    artifacts: ${out_dir}/run_01/{transcript.jsonl,report,aggregate.json}"
  echo "    log:       ${log_file}"

  PYTHONPATH=src poetry run python scripts/run_campaign.py \
    --provider openai \
    --base-url https://openrouter.ai/api \
    --api-key "${OR_KEY}" \
    --model "${model}" \
    --benchmark lifted_auto_eval \
    --runs 1 \
    --label "${label}" \
    "${extra[@]}" \
    2>&1 | tee -a "${log_file}"
}

target="${1:-paid}"
case "${target}" in
  paid|both)
    run_one "${CLAUDE_MODEL}" "${CLAUDE_LABEL}" fresh
    run_one "${OPENAI_MODEL}" "${OPENAI_LABEL}" resume
    ;;
  claude|anthropic)
    run_one "${CLAUDE_MODEL}" "${CLAUDE_LABEL}" fresh
    ;;
  openai|gpt|codex)
    run_one "${OPENAI_MODEL}" "${OPENAI_LABEL}" resume
    ;;
  gemini|google)
    run_one "${OR_GEMINI_MODEL:-google/gemini-2.5-flash}" "${OR_GEMINI_LABEL:-openrouter_gemini25_flash}"
    ;;
  one)
    [[ -n "${OR_MODEL:-}" && -n "${OR_LABEL:-}" ]] || {
      echo "usage: OR_MODEL=... OR_LABEL=... $0 one" >&2
      exit 2
    }
    run_one "${OR_MODEL}" "${OR_LABEL}"
    ;;
  *)
    echo "usage: $0 {paid|claude|openai|gemini|one}" >&2
    exit 2
    ;;
esac
