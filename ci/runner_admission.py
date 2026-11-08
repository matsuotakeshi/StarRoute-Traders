"""Installed outside the checkout as a root-owned pre-job hook on the SRT runner."""
import json,os,re
from pathlib import Path
REPOSITORY='matsuotakeshi/StarRoute-Traders'
def allowed(env,event):
    if (env.get('GITHUB_REPOSITORY') != REPOSITORY
        or event.get('repository',{}).get('full_name') != REPOSITORY
        or re.fullmatch('[0-9a-f]{40}',env.get('GITHUB_SHA','')) is None):
        return False
    if env.get('GITHUB_EVENT_NAME') == 'pull_request':
        pr=event.get('pull_request',{})
        return (event.get('action') in ('opened','synchronize','reopened')
            and pr.get('user',{}).get('login') == 'matsuotakeshi'
            and pr.get('head',{}).get('repo',{}).get('full_name') == REPOSITORY
            and pr.get('base',{}).get('repo',{}).get('full_name') == REPOSITORY
            and pr.get('base',{}).get('ref') == 'main'
            and re.fullmatch('[0-9a-f]{40}',pr.get('head',{}).get('sha','')) is not None
            and env.get('GITHUB_REF') == 'refs/pull/'+str(event.get('number'))+'/merge')
    return (env.get('GITHUB_REF')=='refs/heads/main'
            and env.get('GITHUB_EVENT_NAME') in ('push','workflow_dispatch')
            and 'pull_request' not in event
            and event.get('ref') in ('main','refs/heads/main'))

def main():
    try:ok=allowed(os.environ,json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text()))
    except Exception:ok=False
    print('StarRoute runner admission: '+('trusted event accepted' if ok else 'rejected before checkout'))
    return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
