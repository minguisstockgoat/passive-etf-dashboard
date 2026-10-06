#!/bin/bash
# launchd 용 래퍼: PATH 를 보강하고 scripts/local_refresh.py 를 돌린다.
# 저장소 안 .venv 가 있으면 그 파이썬을, 없으면 python3 을 쓴다.
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export LANG="ko_KR.UTF-8" PYTHONIOENCODING="utf-8"
cd "$REPO" || exit 1
PY="python3"
[ -x "$REPO/.venv/bin/python" ] && PY="$REPO/.venv/bin/python"
exec "$PY" -u scripts/local_refresh.py
