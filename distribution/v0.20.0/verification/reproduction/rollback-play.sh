set -eu
ROOT=/home/takeshi/starroute-ports-verification-20261102
jexec srt_pkg_acceptance pkg add -f /old-packages/starroute-traders-client-0.19.0.pkg /old-packages/starroute-traders-0.19.0.pkg /old-packages/starroute-traders-master-0.19.0.pkg > "$ROOT/logs/rollback-reinstall.log" 2>&1
jexec srt_pkg_acceptance /usr/local/bin/python3.12 - <<'PY'
import sys,sqlite3,json
from pathlib import Path
sys.path.insert(0,'/usr/local/libexec/starroute-traders')
import starroute
assert starroute.__version__=='0.19.0'
from starroute.local_door import LocalDoor
from starroute.clock import ManualClock
root=Path('/var/db/starroute-traders/world');c=sqlite3.connect(root/'game.db');out=sqlite3.connect('/verification/rollback-play.db');c.backup(out);out.close();c.close()
cfg={'database':'/verification/rollback-play.db','reference_key':str(root/'reference.key'),'profile':str(root/'site-profile.json')}
door=LocalDoor(cfg,'recovery','Recovery Pilot',ManualClock(json.loads((root/'expected.json').read_text())['at']))
door.connect();before=door.call('status');market=door.call('market');good=next(r['goods_id'] for r in market['entries'] if r['stock']>0)
door.call('buy',{'goods_id':good,'quantity':1});after=door.call('status');assert after['cash']<before['cash'];assert after['cargo'];door.logout()
print('ROLLED_BACK_019_DOOR_TRADE_ON_RESTORED_DATABASE_PASS')
PY
jexec srt_pkg_acceptance /usr/local/bin/python3.12 /verification/pkg_lifecycle_fixture.py check
jexec srt_pkg_acceptance pkg upgrade -y -g -r StarRouteTest 'starroute-traders*' > "$ROOT/logs/upgrade-after-rollback-play.log" 2>&1
printf 'LATEST_RESTORED_AFTER_ROLLBACK_GAMEPLAY\n'
