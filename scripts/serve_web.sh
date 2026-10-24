#!/usr/bin/env bash
# The AntiGOAT web app: Sahayak chat (/) + findings & replay (/report).
#   bash scripts/serve_web.sh            # uses current .env (mock locally, or Brev)
# Then open http://localhost:8100 . On Brev, add port 8100 under instance -> Access.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d ~/venv ] && source ~/venv/bin/activate || true
pip show python-multipart >/dev/null 2>&1 || pip install "python-multipart>=0.0.9"
exec python -m uvicorn web.app:app --host 0.0.0.0 --port 8100
