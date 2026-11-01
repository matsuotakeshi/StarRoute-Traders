import copy
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from starroute.catalog import Catalog
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.model import GameError, MAX_VALUE
from starroute.rules import fingerprint
from starroute.economy import price_at, price_sum
from starroute.adapters.cli import CLI

ROOT=Path(__file__).resolve().parents[1]
def trial():return json.loads((ROOT/'examples/phase3c-trial.json').read_text(encoding='utf-8'))

class EconomyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'world.db';self.clock=ManualClock(100)

    def open(self,data=None):
        r=SQLiteRepository(self.path,Catalog(data) if data else None,now=100);self.addCleanup(r.close)
        return r,Application(r,self.clock)

    def ready(self,data=None):
        r,a=self.open(data or trial());a.create_player('p','P');return r,a

    def test_quantity_quote_and_ledger(self):
        r,a=self.ready();q=a.quote_trade('p','grain',3,'buy')
        self.assertEqual(q['total'],61+62+63)
        result=a.buy_goods('p','grain',3,request_id='b')
        self.assertEqual(q,result)
        row=a.trade_ledger('p')[0]
        self.assertEqual((row['total'],row['cash_before']-row['cash_after']),(186,186))
        self.assertEqual(row['stock_before']-row['stock_after'],3)
        self.assertEqual(row['rules_hash'],a.configuration_info()['sha256'])

    def test_split_trade_same_cost_and_no_roundtrip_profit(self):
        r,a=self.ready();q=a.quote_trade('p','grain',5,'buy')['total']
        paid=sum(a.buy_goods('p','grain',1)['total'] for _ in range(5))
        self.assertEqual(q,paid)
        received=a.sell_goods('p','grain',5)['total'];self.assertEqual(paid,received)
        self.assertEqual(a.get_player('p')['cash'],5000)

    def test_sum_clamps_matches_reference(self):
        row={'step_price':3,'target_stock':20,'min_price':4,'max_price':40}
        for lo in range(0,40,3):
            for count in range(1,25,4):
                self.assertEqual(price_sum(15,lo,count,row),sum(price_at(15,s,row) for s in range(lo,lo+count)))
        self.assertEqual(price_sum(15,MAX_VALUE,1,row),4)
        with self.assertRaises(GameError):price_sum(15,MAX_VALUE,MAX_VALUE,row)

    def test_tick_remainder_restart_and_clock_reversal(self):
        r,a=self.ready();stock=a.get_market('p')['entries'][0]['stock']
        self.clock.advance(59);self.assertEqual(a.get_market('p')['entries'][0]['stock'],stock)
        r.close();r,a=self.open();self.clock.advance(1)
        self.assertEqual(a.get_market('p')['entries'][0]['stock'],stock+2)
        self.assertEqual(a.get_market('p')['entries'][0]['stock'],stock+2)
        self.clock.value=1
        self.assertEqual(a.get_market('p')['entries'][0]['stock'],stock+2)

    def test_long_gap_equals_incremental_updates_and_bounds(self):
        d=trial()
        for row in d['economy']['markets']:row['stock_limit']=max(row['target_stock'],1000)
        r,a=self.ready(d);self.clock.advance(600000)
        first=a.get_market('p');self.assertEqual(first['entries'][0]['stock'],1000)
        # Net demand drains to zero without negative inventory.
        r.close();self.path=Path(self.tmp.name)/'demand.db'
        for row in d['economy']['markets']:row.update(supply_per_tick=0,demand_per_tick=100)
        r,a=self.ready(d);self.clock.advance(600000)
        self.assertEqual(a.get_market('p')['entries'][0]['stock'],0)

    def test_market_recovery_changes_price(self):
        r,a=self.ready();a.buy_goods('p','grain',4)
        before=a.quote_trade('p','grain',1,'buy')['total'];self.clock.advance(120)
        self.assertEqual(a.quote_trade('p','grain',1,'buy')['total'],before-4)

    def test_duplicate_request_and_conflict(self):
        r,a=self.ready();result=a.buy_goods('p','grain',2,request_id='once')
        self.clock.advance(600)
        self.assertEqual(result,a.buy_goods('p','grain',2,request_id='once'))
        self.assertEqual(len(a.trade_ledger('p')),1)
        with self.assertRaises(GameError):a.buy_goods('p','grain',3,request_id='once')

    def test_ledger_failure_rolls_back_market_clock_and_history(self):
        r,a=self.ready();stock=a.get_market('p')['entries'][0]['stock'];self.clock.advance(60)
        with patch.object(r,'record_trade',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):a.buy_goods('p','grain',1,request_id='fail')
        self.assertEqual(r.connection.execute('SELECT updated_at FROM economy_clock').fetchone()[0],100)
        self.assertEqual(r.connection.execute("SELECT stock FROM markets WHERE planet_id='aurora' AND goods_id='grain'").fetchone()[0],stock)
        self.assertEqual(len(a.trade_ledger('p')),0)
        a.buy_goods('p','grain',1,request_id='fail');self.assertEqual(len(a.trade_ledger('p')),1)

    def test_failed_trade_has_no_ledger(self):
        r,a=self.ready()
        with self.assertRaises(GameError):a.sell_goods('p','grain',1)
        with self.assertRaises(GameError):a.buy_goods('p','grain',MAX_VALUE)
        self.assertEqual(a.trade_ledger('p'),[])

    def test_market_stock_limit_rejects_sale_atomically(self):
        d=trial()
        for row in d['economy']['markets']:row['stock_limit']=row['target_stock']
        r,a=self.ready(d);a.buy_goods('p','grain',1);self.clock.advance(60);a.get_market('p')
        with self.assertRaises(GameError):a.sell_goods('p','grain',1)
        self.assertEqual(a.get_player('p')['cargo'][0]['quantity'],1)
        self.assertEqual(len(a.trade_ledger('p')),1)

    def test_ledger_player_filter_and_cursor(self):
        r,a=self.ready();a.create_player('q','Q')
        for _ in range(3):a.buy_goods('p','grain',1)
        a.buy_goods('q','grain',1)
        first=a.trade_ledger('p',limit=2);rest=a.trade_ledger('p',after=first[-1]['sequence'])
        self.assertEqual((len(first),len(rest)),(2,1))
        self.assertTrue(all(row['player_id']=='p' for row in first+rest))
        with self.assertRaises(GameError):a.trade_ledger('p',limit=101)

    def test_all_economy_parameters_in_hash(self):
        d=trial();before=fingerprint(Catalog(d))
        for key in ('target_stock','step_price','min_price','max_price','stock_limit','supply_per_tick','demand_per_tick'):
            modified=copy.deepcopy(d);modified['economy']['markets'][0][key]+=1
            self.assertNotEqual(before,fingerprint(Catalog(modified)),key)
        d['economy']['markets'].reverse();self.assertEqual(before,fingerprint(Catalog(d)))
        d['economy']['tick_seconds']+=1;self.assertNotEqual(before,fingerprint(Catalog(d)))

    def test_invalid_policy_rejected(self):
        for key,value in [('tick_seconds',0),('status','confirmed'),('mode','unknown')]:
            d=trial();d['economy'][key]=value
            with self.assertRaises(GameError):Catalog(d)
        d=trial();d['economy']['markets'].pop()
        with self.assertRaises(GameError):Catalog(d)

    def test_legacy_fixed_policy_and_quote_compatibility(self):
        r,a=self.open();a.create_player('p','P');before=a.quote_navigation('p','forge')
        result=a.buy_goods('p','grain',2);self.assertEqual(result['total'],120)
        self.clock.advance(1000000);self.assertEqual(a.get_market('p')['entries'][0]['price'],60)
        self.assertEqual(a.trade_ledger('p')[0]['pricing_mode'],'fixed')
        d=Catalog.load().data;original=fingerprint(Catalog(d));d['economy']={'mode':'fixed'}
        self.assertEqual(original,fingerprint(Catalog(d)))

    def test_cli_ja_en_quotes_and_ledger(self):
        r,a=self.ready()
        for lang in ('ja','en'):
            out=[];cli=CLI(a,'p',output=out.append,language=lang)
            self.assertEqual(cli.safe_execute('trade-quote buy grain 3'),(True,0))
            self.assertIn('186',out[-1])
        a.buy_goods('p','grain',3)
        for lang in ('ja','en'):
            out=[];CLI(a,'p',output=out.append,language=lang).execute('ledger')
            self.assertIn('186',out[-1])

    def old_v5(self):
        r,a=self.open();a.create_player('p','P');a.buy_goods('p','grain',1,request_id='old')
        world=r.world_id;r.connection.execute('DROP TABLE industry_periods');r.connection.execute('DROP TABLE market_event_history');r.connection.execute('DROP TABLE event_clock');r.connection.execute('DROP TABLE investment_records');r.connection.execute('DROP TABLE planet_development');r.connection.execute('DROP TABLE trade_ledger');r.connection.execute('DROP TABLE economy_clock')
        r.connection.execute("UPDATE metadata SET value='5' WHERE key='schema_version'");r.close();return world

    def test_v5_migration_keeps_identity_and_old_replay(self):
        world=self.old_v5();r,a=self.open();self.assertEqual(world,r.world_id)
        self.assertIsNotNone(r.backup_path);self.assertEqual(a.trade_ledger('p'),[])
        a.buy_goods('p','grain',1,request_id='old');self.assertEqual(a.trade_ledger('p'),[])
        self.assertEqual(a.get_player('p')['cash'],4940)
        a.buy_goods('p','grain',1,request_id='new');self.assertEqual(len(a.trade_ledger('p')),1)

    def test_v5_migration_failure_rolls_back(self):
        self.old_v5();original=SQLiteRepository._economy_tables
        def fail(r):original(r);raise RuntimeError('injected')
        with patch.object(SQLiteRepository,'_economy_tables',fail):
            with self.assertRaises(RuntimeError):SQLiteRepository(self.path)
        with closing(sqlite3.connect(self.path)) as c:
            self.assertEqual(c.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0],'5')
            self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='trade_ledger'").fetchone())
        r,a=self.open();self.assertEqual(a.get_player('p')['cash'],4940)

    def test_shared_market_concurrent_buyers(self):
        d=trial()
        for m in d['markets']:
            if (m['planet_id'],m['goods_id'])==('aurora','grain'):m['stock']=1
        r,a=self.ready(d);a.create_player('q','Q');r.close();results=[]
        def buy(pid):
            repo=SQLiteRepository(self.path)
            try:
                app=Application(repo,ManualClock(100));app.buy_goods(pid,'grain',1,request_id='last');results.append('ok')
            except GameError as e:results.append(e.code)
            finally:repo.close()
        threads=[threading.Thread(target=buy,args=(p,)) for p in ('p','q')]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(sorted(results),['INSUFFICIENT_STOCK','ok'])
        r,a=self.open();self.assertEqual(r.connection.execute('SELECT count(*) FROM trade_ledger').fetchone()[0],1)

    def test_batched_ticks_equal_periodic_access(self):
        r,a=self.ready();self.clock.advance(600);whole=a.get_market('p')
        r.close();self.path=Path(self.tmp.name)/'periodic.db';self.clock=ManualClock(100)
        r,a=self.ready()
        for _ in range(10):self.clock.advance(60);periodic=a.get_market('p')
        self.assertEqual(whole,periodic)

    def test_quote_is_indicative_and_transaction_reprices(self):
        r,a=self.ready();a.create_player('q','Q');old=a.quote_trade('p','grain',1,'buy')['total']
        a.buy_goods('q','grain',1)
        self.assertEqual(a.buy_goods('p','grain',1)['total'],old+1)

    def test_market_ticks_do_not_change_rules_hash(self):
        r,a=self.ready();before=a.configuration_info()
        a.buy_goods('p','grain',3);self.clock.advance(600);a.get_market('p')
        self.assertEqual(before,a.configuration_info())
