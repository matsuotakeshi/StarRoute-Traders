import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from starroute.catalog import Catalog
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.model import GameError
from starroute.rules import fingerprint
from starroute.adapters.cli import CLI
ROOT=Path(__file__).resolve().parents[1]
def trial():
    d=json.loads((ROOT/'examples/production-trial.json').read_text(encoding='utf-8'))
    for row in d['economy']['markets']:row['demand_per_tick']=0
    return d
class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'world.db';self.clock=ManualClock(100)
    def open(self,data=None):
        r=SQLiteRepository(self.path,Catalog(data) if data else None,now=100);self.addCleanup(r.close)
        return r,Application(r,self.clock)
    def ready(self,data=None):
        r,a=self.open(data or trial());a.create_player('p','P');return r,a
    def stocks(self,r):return {(x['planet_id'],x['goods_id']):x['stock'] for x in r.connection.execute('SELECT * FROM markets')}
    def test_different_goods_and_capacities(self):
        r,a=self.ready();sources=r.catalog.production_sources
        self.assertNotIn(('aurora','alloy'),sources)
        self.assertIn(('forge','alloy'),sources)
        old=self.stocks(r);self.clock.advance(60);a.get_production('p');new=self.stocks(r)
        self.assertEqual(new['aurora','grain']-old['aurora','grain'],6)
        self.assertEqual(new['forge','grain']-old['forge','grain'],2)
        self.assertEqual(new['aurora','alloy'],old['aurora','alloy'])
    def test_import_is_not_production(self):
        r,a=self.ready();old=self.stocks(r);self.clock.advance(60);a.get_production('p');new=self.stocks(r)
        self.assertNotIn(('haven','grain'),r.catalog.production_sources)
        self.assertEqual(new['haven','grain']-old['haven','grain'],2)
    def test_nonproducer_can_sell_imported_cargo(self):
        r,a=self.ready();a.buy_goods('p','grain',2);a.depart('p','haven');self.clock.advance(4)
        old=a.get_market('p')['entries'][0]['stock'];a.sell_goods('p','grain',2)
        self.assertEqual(a.get_market('p')['entries'][0]['stock'],old+2)
    def test_no_free_refill_or_unlimited_purchase(self):
        d=trial()
        for m in d['markets']:
            if m['planet_id']=='aurora' and m['goods_id']=='alloy':m['stock']=1
        r,a=self.ready(d);a.buy_goods('p','alloy',1)
        for _ in range(3):
            with self.assertRaises(GameError):a.buy_goods('p','alloy',1)
            a.get_production('p')
        self.clock.advance(600);a.get_production('p')
        self.assertEqual(self.stocks(r)['aurora','alloy'],0)
        self.assertEqual(len(a.trade_ledger('p')),1)
    def test_finite_time_production_budget(self):
        d=trial()
        for m in d['markets']:
            if m['planet_id']=='aurora' and m['goods_id']=='grain':m['stock']=0
        r,a=self.ready(d);self.clock.advance(60);a.buy_goods('p','grain',6)
        with self.assertRaises(GameError):a.buy_goods('p','grain',1)
        self.assertEqual(self.stocks(r)['aurora','grain'],0)
    def test_stock_cap_and_demand(self):
        d=trial()
        for m in d['economy']['markets']:m['stock_limit']=m['target_stock'];m['demand_per_tick']=1
        r,a=self.ready(d);old=self.stocks(r);self.clock.advance(6000);a.get_production('p');new=self.stocks(r)
        self.assertEqual(new['aurora','grain'],old['aurora','grain'])
        self.assertEqual(new['aurora','alloy'],max(0,old['aurora','alloy']-100))
    def test_tick_remainder_restart_and_backward_clock(self):
        r,a=self.ready();old=self.stocks(r);self.clock.advance(59);a.get_production('p');self.assertEqual(old,self.stocks(r));r.close()
        r,a=self.open();self.clock.advance(1);a.get_production('p');new=self.stocks(r)
        self.assertEqual(new['aurora','grain']-old['aurora','grain'],6)
        self.clock.value=100;a.get_production('p');self.assertEqual(new,self.stocks(r))
    def test_bulk_and_periodic_updates_match(self):
        r,a=self.ready();self.clock.advance(600);a.get_production('p');bulk=self.stocks(r);r.close()
        self.path=Path(self.tmp.name)/'periodic.db';self.clock=ManualClock(100);r,a=self.ready()
        for _ in range(10):self.clock.advance(60);a.get_production('p')
        self.assertEqual(bulk,self.stocks(r))
    def test_retry_does_not_refill(self):
        r,a=self.ready();receipt=a.buy_goods('p','grain',1,request_id='r');old=self.stocks(r);self.clock.advance(60)
        self.assertEqual(receipt,a.buy_goods('p','grain',1,request_id='r'))
        self.assertEqual(old,self.stocks(r));self.assertEqual(len(a.trade_ledger('p')),1)
    def test_failed_trade_rolls_back_production_clock(self):
        r,a=self.ready();old=self.stocks(r);self.clock.advance(60)
        with patch.object(r,'record_trade',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):a.buy_goods('p','grain',1)
        self.assertEqual(old,self.stocks(r));self.assertEqual(r.connection.execute('SELECT updated_at FROM economy_clock').fetchone()[0],100)
    def test_no_double_supply_with_concurrent_readers(self):
        r,a=self.ready();old=self.stocks(r);r.close();errors=[]
        def access():
            repo=SQLiteRepository(self.path)
            try:Application(repo,ManualClock(160)).get_production('p')
            except Exception as e:errors.append(type(e).__name__)
            finally:repo.close()
        threads=[threading.Thread(target=access) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(errors,[]);r,a=self.open()
        self.assertEqual(self.stocks(r)['aurora','grain']-old['aurora','grain'],6)
    def test_rules_hash_changes_only_for_definitions(self):
        d=trial();before=fingerprint(Catalog(d))
        for group,key,value in [('sources','units_per_tick',7),('sources','industry','secondary'),('imports','units_per_tick',3)]:
            new=copy.deepcopy(d);new['production'][group][0][key]=value
            self.assertNotEqual(before,fingerprint(Catalog(new)))
        d['production']['sources'].reverse();self.assertEqual(before,fingerprint(Catalog(d)))
        r,a=self.ready();before=a.configuration_info();a.invest('p','primary',100);a.buy_goods('p','grain',1);self.clock.advance(60);a.get_production('p')
        self.assertEqual(before,a.configuration_info())
    def test_invalid_or_duplicate_definitions(self):
        mutations=[lambda d:d['production']['sources'].append(d['production']['sources'][0]),
            lambda d:d['production']['sources'][0].update(goods_id='unknown'),
            lambda d:d['production']['sources'][0].update(industry='fifth'),
            lambda d:d['production']['sources'][0].update(units_per_tick=0),
            lambda d:d['production']['sources'][0].update(units_per_tick=True),
            lambda d:d['economy']['markets'][0].update(supply_per_tick=100),
            lambda d:d.pop('production')]
        for mutate in mutations:
            d=trial();mutate(d)
            with self.assertRaises(GameError):Catalog(d)
    def test_no_production_enabled_on_legacy_mode(self):
        d=trial();d['economy']={'mode':'fixed'}
        with self.assertRaises(GameError):Catalog(d)
        r,a=self.open();a.create_player('p','P');self.assertFalse(a.get_production('p')['enabled'])
    def test_no_silent_reclassification_of_old_supply(self):
        d=json.loads((ROOT/'examples/phase3c-trial.json').read_text(encoding='utf-8'));r,a=self.ready(d);old=self.stocks(r)
        self.clock.advance(60);self.assertFalse(a.get_production('p')['enabled'])
        self.assertEqual(self.stocks(r)['aurora','grain']-old['aurora','grain'],2)
    def test_public_view_no_private_development_fields(self):
        r,a=self.ready();text=json.dumps(a.get_production('p'))
        for k in ('private_caps','abundance','rare','initial_progress'):self.assertNotIn(k,text)
        a.invest('p','primary',100)
        self.assertEqual(a.get_production('p')['entries'][0]['production_per_tick'],6)
    def test_cli_ja_en_and_saved_state(self):
        r,a=self.ready();world=r.world_id
        for lang in ('ja','en'):
            out=[];self.assertEqual(CLI(a,'p',output=out.append,language=lang).safe_execute('production'),(True,0))
            self.assertTrue(any('grain' in x and '6' in x for x in out))
        a.invest('p','primary',100);self.clock.advance(60);a.get_production('p');stocks=self.stocks(r);r.close()
        r,a=self.open();self.assertEqual(r.world_id,world);self.assertIsNone(r.backup_path)
        self.assertEqual(stocks,self.stocks(r));self.assertEqual(a.get_development('p')['industries'][0]['progress'],10)
    def test_optional_imports_default(self):
        d=trial();d['production'].pop('imports');before=fingerprint(Catalog(d));d['production']['imports']=[]
        self.assertEqual(before,fingerprint(Catalog(d)))
