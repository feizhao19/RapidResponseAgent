#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"

if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
elif [[ -f "${HOME}/miniconda3/etc/profile.d/conda.sh" ]]; then
  # shellcheck disable=SC1091
  source "${HOME}/miniconda3/etc/profile.d/conda.sh"
  conda activate sam
elif [[ -f "${HOME}/anaconda3/etc/profile.d/conda.sh" ]]; then
  # shellcheck disable=SC1091
  source "${HOME}/anaconda3/etc/profile.d/conda.sh"
  conda activate sam
else
  echo "Missing .venv or conda env 'sam' — activate Python first." >&2
  exit 1
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
if [[ -f scripts/project_env.sh ]]; then
  # shellcheck disable=SC1091
  source scripts/project_env.sh
fi

pip install -q -r web/requirements.txt 2>/dev/null || true
export PYTHONPATH=.

if [[ -z "${VIPDE_PYTHON:-}" ]]; then
  _vipde_candidates=()
  [[ -n "${CONDA_PREFIX:-}" ]] && _vipde_candidates+=("${CONDA_PREFIX}/bin/python")
  _vipde_candidates+=(
    "${HOME}/anaconda3/envs/sam/bin/python"
    "${HOME}/miniconda3/envs/sam/bin/python"
    "${HOME}/mambaforge/envs/sam/bin/python"
    "${HOME}/miniforge3/envs/sam/bin/python"
  )
  for _py in "${_vipde_candidates[@]}"; do
    if [[ -x "${_py}" ]] && "${_py}" -c "import segment_anything" 2>/dev/null; then
      export VIPDE_PYTHON="${_py}"
      echo "ViPDE will use: ${VIPDE_PYTHON}" >&2
      break
    fi
  done
  unset _py _vipde_candidates
fi

FRONTEND_DIR="$ROOT/web/frontend"
FRONTEND_DIST="$FRONTEND_DIR/dist/index.html"
if [[ ! -f "$FRONTEND_DIST" ]]; then
  echo "Frontend not built — run: cd web/frontend && npm install && npm run build" >&2
  echo "Or use Vite dev server: cd web/frontend && npm run dev  →  http://localhost:5173" >&2
elif find "$FRONTEND_DIR/src" -type f -newer "$FRONTEND_DIST" -print -quit | grep -q .; then
  echo "Frontend source is newer than dist — rebuilding…" >&2
  (cd "$FRONTEND_DIR" && npm run build) >&2
fi

exec uvicorn web.api.main:app --reload --host "$HOST" --port "$PORT"
