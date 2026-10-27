#!/usr/bin/env bash
# Fetch the public InjecAgent benchmark data (Zhan et al., Findings of ACL 2024; MIT licence) into
# data/external/injecagent. It is not committed: we run our own harness on the authors' data.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/external
if [ ! -d data/external/injecagent/.git ]; then
  git clone --depth 1 https://github.com/uiuc-kang-lab/InjecAgent.git data/external/injecagent
fi
ls data/external/injecagent/data
