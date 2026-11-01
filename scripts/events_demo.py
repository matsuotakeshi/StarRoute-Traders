"""Forced-probability CLI demonstrations; isolated worlds and manual clocks."""
import sys,json,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from starroute.catalog import Catalog
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.adapters.cli import CLI
for kind in ('surge','crash'):
 with tempfile.TemporaryDirectory() as tmp:
  data=json.loads((Path(__file__).resolve().parents[1]/'examples/events-trial.json').read_text())
  data['market_events']['targets']=[dict(planet_id='aurora',goods_id='grain',surge_bps=10000 if kind=='surge' else 0,crash_bps=10000 if kind=='crash' else 0,surge_credits=200,crash_credits=150)]
  clock=ManualClock(100);path=Path(tmp)/'demo.db';r=SQLiteRepository(path,Catalog(data),now=100)
  try:
   a=Application(r,clock);cli=CLI(a,'p',language='en')
   print('Forced trial:',kind)
   for cmd in ('register Captain','buy grain 1'):assert cli.safe_execute(cmd)==(True,0)
   clock.advance(60)
   for cmd in ('events','trade-quote sell grain 1','request sale sell grain 1','request sale sell grain 1','events-history'):assert cli.safe_execute(cmd)==(True,0)
   assert a.get_player('p')['cash']==(5195 if kind=='surge' else 4900)
   snapshot=a.get_events('p')
  finally:r.close()
  r=SQLiteRepository(path)
  try:
   a=Application(r,clock);assert snapshot==a.get_events('p');clock.advance(30)
   cli=CLI(a,'p',language='en');cli.execute('events');cli.execute('events-history');cli.execute('trade-quote buy grain 1')
   assert a.get_events('p')==[] and len(a.event_history('p'))==1
   assert a.quote_trade('p','grain',1,'buy')['total']==96
  finally:r.close()
print('Surge/crash, restart, retry and expiry: OK')
