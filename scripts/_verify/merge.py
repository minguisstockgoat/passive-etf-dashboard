# -*- coding: utf-8 -*-
"""지수규칙 소스(fn/krxwise/상품페이지/수동)를 병합해 index_rules.json 생성.
뒤 파일이 앞을 덮어씀(manual 이 최우선)."""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ORDER = ["fn1.json", "fn2.json", "krxwise.json", "pages.json", "pages_agent.json", "manual.json"]
m = {}
for f in ORDER:
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        d = json.load(open(p, encoding="utf-8"))
        m.update(d)
        print(f"  {f}: {len(d)}")
json.dump(m, open(os.path.join(HERE, "index_rules.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print(f"→ index_rules.json: {len(m)}개 지수")
