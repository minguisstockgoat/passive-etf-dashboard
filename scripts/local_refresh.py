# -*- coding: utf-8 -*-
"""
국내 PC 전용 갱신: TIGER·RISE 구성종목 + 정기변경 이력 → 빌드 → commit/push.

왜 따로 도나
  미래에셋(TIGER)은 해외 IP 를 403 으로, KB(RISE, kbam.co.kr)는 접속 자체를 막는다.
  GitHub Actions 러너(미국)에서는 두 운용사를 못 받아서 2026-07-13(TIGER)·09-19(RISE) 이후
  구성종목이 멈춘 채 대시보드에 남아 있었다. Actions 는 SKIP_MANAGERS=TIGER,RISE 로
  나머지 6개 운용사만 받고, 이 스크립트가 국내 PC(Mac mini launchd)에서 두 곳을 채운다.

흐름
  git pull → fetch_holdings(TIGER, RISE) → rebal_history(TIGER, RISE, 최근분) → build_data
  → commit → push. push 가 밀리면(그 사이 Actions 가 push) rebase 후 빌드를 다시 돌려 합친다.

실행:  py scripts/local_refresh.py            (로그: scripts/.local_refresh.log)
필요:  KRX_API_KEY(환경변수 또는 저장소 루트 .env), git push 권한(gh auth/SSH),
       pip install -r scripts/requirements.txt
Mac mini(launchd)는 scripts/mac/ 의 run_local_refresh.sh + plist 템플릿을 쓴다(README 참고).
"""
from __future__ import annotations
import os, sys, subprocess, datetime as dt, json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
LOG = os.path.join(HERE, ".local_refresh.log")
MANAGERS = ["TIGER", "RISE"]
PY = sys.executable


def load_dotenv():
    """저장소 루트 .env(KEY=VALUE, gitignore)를 읽어 비어 있는 환경변수만 채운다.
    launchd 는 로그인 셸 환경을 물려받지 않아서 KRX_API_KEY 를 여기서 넣는다."""
    p = os.path.join(ROOT, ".env")
    if not os.path.exists(p):
        return
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip().removeprefix("export ").strip(), v.strip().strip('"').strip("'")
        if k and not os.environ.get(k):
            os.environ[k] = v


def log(msg: str):
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd: list, cwd: str = ROOT, check: bool = True) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.pop("SKIP_MANAGERS", None)
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    tail = (p.stdout or "").strip().splitlines()[-6:] + (p.stderr or "").strip().splitlines()[-4:]
    log(f"$ {' '.join(cmd[-4:])} → {p.returncode}" + ("".join("\n    " + t for t in tail) if tail else ""))
    if check and p.returncode != 0:
        raise RuntimeError(f"실패: {' '.join(cmd)}")
    return p


def build_and_commit(msg: str) -> bool:
    run([PY, "build_data.py"], cwd=HERE)
    run(["git", "add", "data/"])
    if run(["git", "diff", "--cached", "--quiet"], check=False).returncode == 0:
        log("변경 없음")
        return False
    run(["git", "commit", "-m", msg])
    return True


def main():
    load_dotenv()
    log("=== local_refresh 시작 ===")
    if not (os.environ.get("KRX_API_KEY") or os.environ.get("KRX_AUTH_KEY")):
        log("! KRX_API_KEY 환경변수가 없습니다, 중단"); return 1
    if run(["git", "status", "--porcelain", "--", "scripts/", "assets/", "index.html", "etf.html"],
           check=False).stdout.strip():
        log("! 코드 파일에 커밋 안 된 변경이 있어 자동 갱신을 건너뜁니다(작업 중 보호)."); return 1
    run(["git", "checkout", "--", "data/"], check=False)            # 지난 실패 잔여물 정리
    run(["git", "pull", "--ff-only", "-q"])

    run([PY, "fetch_holdings.py", *MANAGERS], cwd=HERE)
    run([PY, "rebal_history.py", "--managers", *MANAGERS], cwd=HERE, check=False)

    asof = ""
    if not build_and_commit("data: TIGER·RISE 국내 수집"):
        return 0
    try:
        asof = json.load(open(os.path.join(ROOT, "data", "etfs.json"), encoding="utf-8")).get("as_of", "")
        run(["git", "commit", "--amend", "-q", "-m", f"data: TIGER·RISE 국내 수집 (기준일 {asof})"])
    except Exception:
        pass

    for attempt in range(3):
        if run(["git", "push", "-q"], check=False).returncode == 0:
            log(f"push 완료 (기준일 {asof})"); return 0
        # 그 사이 Actions 가 push 했다 → 원격 위에 우리 커밋을 다시 얹고(충돌 시 우리 쪽 우선),
        # 다른 운용사의 새 구성종목까지 반영되도록 빌드를 한 번 더 돌린다.
        log("push 거절 → rebase 후 재빌드")
        run(["git", "fetch", "-q"])
        if run(["git", "rebase", "-X", "theirs", "origin/main"], check=False).returncode != 0:
            run(["git", "rebase", "--abort"], check=False)
            log("! rebase 실패, 다음 실행 때 다시 받습니다"); return 1
        build_and_commit("data: 빌드 재생성 (TIGER·RISE 병합)")
    log("! push 3회 실패"); return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as ex:
        log(f"! 예외: {ex}")
        sys.exit(1)
