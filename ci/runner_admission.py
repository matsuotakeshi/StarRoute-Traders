"""Installed outside the checkout as a root-owned pre-job hook on the SRT runner."""
import json,os,re
from pathlib import Path
REPOSITORY='matsuotakeshi/StarRoute-Traders'
def allowed(env,event):
    return (env.get('GITHUB_REPOSITORY')==REPOSITORY and env.get('GITHUB_REF')=='refs/heads/main'
            and env.get('GITHUB_EVENT_NAME') in ('push','workflow_dispatch')
            and re.fullmatch('[0-9a-f]{40}',env.get('GITHUB_SHA','')) is not None
            and event.get('repository',{}).get('full_name')==REPOSITORY
            and 'pull_request' not in event
            and event.get('ref') in ('main','refs/heads/main'))
def main():
    try:ok=allowed(os.environ,json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text()))
    except Exception:ok=False
    print('StarRoute runner admission: '+('trusted main accepted' if ok else 'rejected before checkout'))
    return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
