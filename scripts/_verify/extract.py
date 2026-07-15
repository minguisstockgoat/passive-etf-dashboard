# -*- coding: utf-8 -*-
"""에이전트 transcript(JSONL)에서 [{"index":...}] 배열을 추출해 dict로 저장."""
import json, re, sys
sys.stdout.reconfigure(encoding="utf-8")

src, dest = sys.argv[1], sys.argv[2]
ARR = re.compile(r'\[\s*\{.*?"index".*\}\s*\]', re.S)


def walk_strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from walk_strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk_strings(v)


best = None
for line in open(src, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    try:
        obj = json.loads(line)
    except Exception:
        continue
    for s in walk_strings(obj):
        if '"index"' not in s or '"cap_type"' not in s:
            continue
        for mt in ARR.finditer(s):
            frag = mt.group(0)
            try:
                arr = json.loads(frag)
            except Exception:
                continue
            if isinstance(arr, list) and (best is None or len(arr) > len(best)):
                best = arr

if not best:
    print("추출 실패:", src); sys.exit(1)

out = {}
for o in best:
    ix = str(o.get("index", "")).replace("&amp;", "&").strip()
    if ix:
        o["index"] = ix
        out[ix] = o
json.dump(out, open(dest, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"{dest}: {len(out)}개")
