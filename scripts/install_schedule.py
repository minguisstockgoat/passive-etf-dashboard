"""Install the unified domestic collector as one per-user launchd job."""
import os,plistlib,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
label='com.wondaehan.etf-unified'
logs=ROOT/'logs';logs.mkdir(exist_ok=True)
plist=Path.home()/'Library/LaunchAgents'/(label+'.plist')
args={'Label':label,'ProgramArguments':[str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/run_daily.py'),'--publish'],
      'WorkingDirectory':str(ROOT),'StartCalendarInterval':[{'Weekday':d,'Hour':h,'Minute':m} for d in range(1,6) for h,m in [(8,50),(20,40)]],
      'ProcessType':'Background','StandardOutPath':str(logs/'daily.out.log'),'StandardErrorPath':str(logs/'daily.err.log'),
      'EnvironmentVariables':{'PATH':'/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin','PYTHONUNBUFFERED':'1'}}
# Replace this task's own registration only; leave every unrelated job untouched.
subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}/{label}'],capture_output=True)
plist.write_bytes(plistlib.dumps(args));plist.chmod(0o644)
subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(plist)],check=True)
print('Installed:',label,'weekdays 08:50 / 20:40 KST')
