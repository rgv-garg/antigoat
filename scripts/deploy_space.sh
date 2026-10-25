#!/usr/bin/env bash
# Upload the web demo to a Hugging Face Space (Docker SDK).
#   bash scripts/deploy_space.sh <hf-user>/<space-name>
# Needs: pip install -U huggingface_hub  and  hf auth login  (a token with write access).
set -euo pipefail
SPACE="${1:?usage: bash scripts/deploy_space.sh <hf-user>/<space-name>}"
cd "$(dirname "$0")/.."
TMP="$(mktemp -d)"
# code + published results only (never .env, venvs, caches or private run files)
tar --exclude=.git --exclude=.env --exclude='__pycache__' --exclude='*.pyc' --exclude=.pytest_cache \
    --exclude=venv --exclude=.venv --exclude='results/*' -cf - . | tar -xf - -C "$TMP"
mkdir -p "$TMP/results"
cp results/final-* results/demo-* "$TMP/results/" 2>/dev/null || true
# a Space reads its settings from the README front matter
{
  printf -- '---\ntitle: AntiGOAT\nemoji: 🐐\ncolorFrom: yellow\ncolorTo: blue\nsdk: docker\napp_port: 7860\npinned: false\n'
  printf -- 'short_description: Does your AI agent really forget? Memory X-ray + audits\n---\n\n'
  cat README.md
} > "$TMP/README.md"
hf repos create "$SPACE" --type space --sdk docker --public --exist-ok
hf upload "$SPACE" "$TMP" . --type space --commit-message "Deploy AntiGOAT demo"
echo "Deployed: https://huggingface.co/spaces/$SPACE  (add the secrets listed in docs/DEPLOY.md)"
rm -rf "$TMP"
