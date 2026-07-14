# -*- coding: utf-8 -*-
"""전체 데이터 갱신: 운용사 구성종목(PDF) 수집 → 유니버스/시총/비중cap 빌드."""
from __future__ import annotations
import sys
sys.stdout.reconfigure(encoding="utf-8")
import urllib3
urllib3.disable_warnings()

import fetch_holdings
import build_data

if __name__ == "__main__":
    print("[1/2] 운용사별 구성종목(PDF) 수집…")
    fetch_holdings.main()
    print("\n[2/2] 유니버스·시가총액·비중 cap 빌드…")
    build_data.main()
    print("\n완료.")
