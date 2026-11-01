import copy,json,tempfile,unittest,sqlite3,threading
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from starroute.catalog import Catalog
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.model import GameError
from starroute.events import draw
from starroute.rules import fingerprint
from starroute.adapters.cli import CLI
ROOT=Path(__file__).resolve().parents[1]
def trial():
 d=json.loads((ROOT/'examples/events-trial.json').read_text(encoding='utf-8'))
 d['market_events']['targets']=[dict(planet_id='aurora',goods_id='grain',surge_bps=10000,crash_bps=0,surge_credits=200,crash_credits=150)]
 return d
class EventTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'w.db';self.clock=ManualClock(100)
 def open(self,data=None):
  r=SQLiteRepository(self.path,Catalog(data) if data else None,now=100);self.addCleanup(r.close);return r,Application(r,self.clock)
 def ready(self,data=None):
  r,a=self.open(data or trial());a.create_player('p','P');return r,a
 def test_surge_start_end_current_stock_price(self):
  r,a=self.ready();self.clock.advance(59);self.assertEqual(a.get_events('p'),[])
  self.clock.advance(1);self.assertEqual(a.quote_trade('p','grain',1,'buy')['total'],296)
  self.assertEqual(len(a.get_events('p')),1)
  self.clock.advance(30);self.assertEqual(a.get_events('p'),[])
  self.assertEqual(a.quote_trade('p','grain',1,'buy')['total'],96)
  self.assertEqual(len(a.event_history('p')),1)
 def test_crash_clamps_and_roundtrip_no_profit(self):
  d=trial();d['market_events']['targets'][0].update(surge_bps=0,crash_bps=10000)
  r,a=self.ready(d);self.clock.advance(60)
  self.assertEqual(a.quote_trade('p','grain',3,'buy')['total'],3)
  a.buy_goods('p','grain',3);a.sell_goods('p','grain',3);self.assertEqual(a.get_player('p')['cash'],5000)
 def test_quantity_sum_and_market_display(self):
  r,a=self.ready();self.clock.advance(60);q=a.quote_trade('p','grain',3,'buy')
  self.assertEqual(q['total'],296+297+298)
  self.assertEqual(a.get_market('p')['entries'][0]['price'],296)
  self.assertEqual(sum(a.buy_goods('p','grain',1)['total'] for _ in range(3)),q['total'])
 def test_restart_does_not_redraw(self):
  r,a=self.ready();self.clock.advance(60);first=a.get_events('p');r.close();r,a=self.open()
  self.assertEqual(first,a.get_events('p'));self.assertEqual(len(a.event_history('p')),1)
 def test_batched_history_equals_periodic(self):
  d=json.loads((ROOT/'examples/events-trial.json').read_text(encoding='utf-8'))
  r,a=self.ready(d);self.clock.advance(600);a.get_events('p');rows=a.event_history('p',limit=100);r.close()
  self.path=Path(self.tmp.name)/'other.db';self.clock=ManualClock(100);r,a=self.ready(d)
  for _ in range(10):self.clock.advance(60);a.get_events('p')
  self.assertEqual(rows,a.event_history('p',limit=100))
 def test_no_extension_or_overlap(self):
  r,a=self.ready();self.clock.advance(60);row=a.get_events('p')[0]
  self.clock.advance(10);self.assertEqual(row,a.get_events('p')[0]);self.clock.advance(50)
  new=a.get_events('p')[0];self.assertEqual(new['slot'],2);self.assertGreaterEqual(new['starts_at'],row['ends_at'])
 def test_failure_rolls_back_draw_and_clock(self):
  r,a=self.ready();self.clock.advance(60)
  with patch.object(r,'record_trade',side_effect=RuntimeError('injected')):
   with self.assertRaises(RuntimeError):a.buy_goods('p','grain',1)
  self.assertEqual(r.connection.execute('SELECT last_slot FROM event_clock').fetchone()[0],0)
  self.assertEqual(r.event_history(),[]);a.buy_goods('p','grain',1);self.assertEqual(len(r.event_history()),1)
 def test_retry_does_not_apply_new_events(self):
  r,a=self.ready();x=a.buy_goods('p','grain',1,request_id='b');self.clock.advance(60)
  self.assertEqual(x,a.buy_goods('p','grain',1,request_id='b'));self.assertEqual(r.event_history(),[])
  a.get_events('p');self.assertEqual(len(r.event_history()),1)
 def test_concurrent_reads_one_event(self):
  r,a=self.ready();r.close();errors=[]
  def read():
   rr=SQLiteRepository(self.path)
   try:Application(rr,ManualClock(160)).get_events('p')
   except Exception as e:errors.append(type(e).__name__)
   finally:rr.close()
  threads=[threading.Thread(target=read) for _ in range(2)]
  for t in threads:t.start()
  for t in threads:t.join()
  self.assertEqual(errors,[]);r,a=self.open();self.assertEqual(len(r.event_history()),1)
 def test_long_backlog_sync_without_skipping(self):
  d=trial();d['market_events'].update(interval_seconds=1,duration_seconds=1);r,a=self.ready(d);self.clock.advance(2001)
  with self.assertRaises(GameError) as cm:a.get_events('p')
  self.assertEqual(cm.exception.code,'EVENT_SYNC_REQUIRED')
  self.assertTrue(a.events_sync('p')['pending']);self.assertTrue(a.events_sync('p')['pending']);self.assertFalse(a.events_sync('p')['pending'])
  self.assertEqual(r.connection.execute('SELECT count(*) FROM market_event_history').fetchone()[0],2001)
  self.assertEqual(a.get_events('p')[0]['slot'],2001)
 def test_seed_order_and_config_hash(self):
  d=trial();before=fingerprint(Catalog(d));d['market_events']['seed']='another'
  self.assertNotEqual(before,fingerprint(Catalog(d)))
  self.assertEqual(draw('seed',1,3,'aurora','grain'),draw('seed',1,3,'aurora','grain'))
  d=json.loads((ROOT/'examples/events-trial.json').read_text(encoding='utf-8'));before=fingerprint(Catalog(d));d['market_events']['targets'].reverse();self.assertEqual(before,fingerprint(Catalog(d)))
 def test_event_state_not_hashed(self):
  r,a=self.ready();before=a.configuration_info();self.clock.advance(600);a.get_events('p');self.assertEqual(before,a.configuration_info())
 def test_invalid_policy(self):
  for edit in [lambda p:p.update(duration_seconds=61),lambda p:p['targets'][0].update(crash_bps=1),lambda p:p.update(seed=''),lambda p:p['targets'].append(p['targets'][0])]:
   d=trial();edit(d['market_events'])
   with self.assertRaises(GameError):Catalog(d)
 def test_fuel_shock_does_not_change_warp(self):
  d=trial();d['market_events']['targets'][0]['goods_id']='fusion_fuel';r,a=self.ready(d);a.buy_goods('p','fusion_fuel',1);cargo=a.get_player('p')['cargo'];self.clock.advance(60)
  q=a.quote_navigation('p','forge','warp','fast');self.assertEqual(q['fuel_cost'],20)
  a.navigate('p','forge','warp','fast',q['quote_id']);self.assertEqual(a.get_player('p')['cargo'],cargo)
 def test_disabled_legacy_and_pagination(self):
  r,a=self.open();a.create_player('p','P');self.clock.advance(1000000);self.assertEqual(a.get_events('p'),[])
  self.assertEqual(a.get_market('p')['entries'][0]['price'],60)
 def test_ja_en_history_and_no_private_values(self):
  r,a=self.ready();self.clock.advance(60)
  for lang in ('ja','en'):
   out=[];cli=CLI(a,'p',output=out.append,language=lang)
   self.assertEqual(cli.safe_execute('events'),(True,0));self.assertEqual(cli.safe_execute('events-history'),(True,0))
   self.assertTrue(any('grain' in s for s in out));self.assertNotIn('private_caps',''.join(out))
 def test_v7_migration_and_rollback(self):
  r,a=self.open();a.create_player('p','P');world=r.world_id;r.connection.execute('DROP TABLE industry_periods');r.connection.execute('DROP TABLE market_event_history');r.connection.execute('DROP TABLE event_clock');r.connection.execute("UPDATE metadata SET value='7' WHERE key='schema_version'");r.close()
  original=SQLiteRepository._event_tables
  def fail(rr):original(rr);raise RuntimeError('injected')
  with patch.object(SQLiteRepository,'_event_tables',fail):
   with self.assertRaises(RuntimeError):SQLiteRepository(self.path)
  with closing(sqlite3.connect(self.path)) as c:self.assertEqual(c.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0],'7')
  r,a=self.open();self.assertEqual(world,r.world_id);self.assertIsNotNone(r.backup_path);self.assertEqual(a.get_player('p')['cash'],5000)
