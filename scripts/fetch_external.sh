#!/usr/bin/env bash
# Public benchmark data we run our own harnesses on. Not committed (data/ is git-ignored).
#   InjecAgent  (Zhan et al., ACL Findings 2024)          -> data/external/injecagent
#   MemEvoBench (Xie et al., 2026)                         -> data/external/memevobench
#   AgentDojo   ships with `pip install agentdojo==0.1.35` (nothing to fetch)
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/external
[ -d data/external/injecagent/.git ] || git clone --depth 1 https://github.com/uiuc-kang-lab/InjecAgent.git data/external/injecagent
[ -d data/external/memevobench/.git ] || git clone --depth 1 https://github.com/xiewwee11/MemEvoBench.git data/external/memevobench
echo "MemEvoBench commit: $(git -C data/external/memevobench rev-parse --short HEAD)"
ls data/external/memevobench/memorybench/QA
