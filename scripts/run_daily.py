#!/usr/bin/env python3
"""Single writer for the unified ETF site. Does not send messages.
Use --publish only from the installed domestic job. Failures remain observable.
"""
from __future__ import annotations
import argparse,datetime as dt,fcntl,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
KST=dt.timezone(dt.timedelta(hours=9))

def credentials():
    for p in [ROOT/'.env',Path.home()/'.config/secrets/keys.env',Path.home()/'short-dashboard/.env']:
        if not p.exists():continue
        for line in p.read_text().splitlines():
            k,sep,v=line.strip().removeprefix('export ').partition('=')
            if sep and k.strip() in ('KRX_API_KEY','KRX_AUTH_KEY'):
                os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))
    if not(os.environ.get('KRX_API_KEY') or os.environ.get('KRX_AUTH_KEY')):
        raise RuntimeError('KRX API key unavailable')

def git(*args,check=True):
    return subprocess.run(['git',*args],cwd=ROOT,text=True,capture_output=True,check=check)

def push():
    for delay in [0,5,15]:
        if delay:time.sleep(delay)
        p=git('push','origin','main',check=False)
        if p.returncode==0:return
        # A concurrent code update needs review; never rewrite either side automatically.
        if 'non-fast-forward' in p.stderr or '[rejected]' in p.stderr:
            raise RuntimeError('Remote changed; local data commit retained for reconciliation')
    raise RuntimeError('Push failed after 3 attempts; local commit retained')

def command(script,*args,timeout=1800):
    subprocess.run([sys.executable,str(ROOT/'scripts'/script),*args],cwd=ROOT,check=True,timeout=timeout)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--publish',action='store_true');a=ap.parse_args()
    (ROOT/'logs').mkdir(exist_ok=True)
    with (ROOT/'logs/daily.lock').open('w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:print('A collection is already running');return 0
        if a.publish:
            changed=git('status','--porcelain','--untracked-files=no').stdout.splitlines()
            if any(not row[3:].startswith('data/') for row in changed):
                raise RuntimeError('Uncommitted source changes: scheduled update stopped')
            git('fetch','origin','main')
            behind=int(git('rev-list','--count','HEAD..origin/main').stdout)
            ahead=int(git('rev-list','--count','origin/main..HEAD').stdout)
            if behind and (changed or ahead):
                raise RuntimeError('Local pending work and remote updates both exist; manual reconciliation required')
            if behind:git('merge','--ff-only','origin/main')
            if ahead:push()  # Retry a previous deployment even if this run has no new data.
        credentials()
        command('build_data.py')
        command('collect_daily.py')
        command('build_data.py')
        command('daily_changes.py')
        impact_ok=True
        try:command('impact_data.py',timeout=600)
        except (subprocess.CalledProcessError,subprocess.TimeoutExpired):
            impact_ok=False
            from daily_changes import write
            write(ROOT/'data/impact/status.json',{'ok':False,'checked_at':dt.datetime.now(KST).isoformat(timespec='seconds'),'note':'보고서 자료 갱신 실패. 직전 자료 기준일 확인 필요.'})
            print('Impact report inputs failed; previous report data retained')
        now=dt.datetime.now(KST)
        # Preserve the scheduled-event view with bounded weekly incremental collection.
        if now.weekday()==4 and now.hour>=18:
            try:
                p=subprocess.run([sys.executable,str(ROOT/'scripts/rebal_history.py'),'--budget','4'],cwd=ROOT,timeout=600)
                if p.returncode:print('Rebalance-history refresh failed; existing history retained')
            except subprocess.TimeoutExpired:
                print('History budget exhausted; publishing completed daily snapshots')
        health=subprocess.run([sys.executable,str(ROOT/'scripts/check_health.py')],cwd=ROOT)
        if a.publish:
            git('add','--','data/')
            if git('diff','--cached','--quiet',check=False).returncode:
                git('commit','-m','data: unified ETF refresh '+now.strftime('%Y-%m-%d %H:%M KST'))
            push()
        return health.returncode or int(not impact_ok)

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as ex:
        print('UPDATE FAILED:',type(ex).__name__,str(ex),file=sys.stderr)
        raise SystemExit(1)
