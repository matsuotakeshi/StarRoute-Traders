import copy
import json
from pathlib import Path
import tempfile
import unittest
from dataclasses import asdict
from starroute.catalog import Catalog
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.model import GameError, MAX_VALUE
from starroute.rules import fingerprint

ROOT=Path(__file__).resolve().parents[1]
POLICY=dict(mode='recovering_v1',status='provisional',capacity=4,initial=4,recovery_units=2,interval_seconds=60)


class BuybackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'game.db';self.clock=ManualClock(100)
        self.data=json.loads((ROOT/'examples/phase3c-trial.json').read_text(encoding='utf-8'))
        self.data['market_buyback']=dict(POLICY)
        self.repo=SQLiteRepository(self.path,Catalog(self.data),now=100)
        self.addCleanup(lambda:self.repo.close())
        self.app=Application(self.repo,self.clock);self.app.create_player('p','P')

    def market(self):return self.app.get_market('p')['entries'][0]
    def world(self):return asdict(self.repo._load())

    def test_full_resale_shelf_can_buy_and_budget_recovers(self):
        self.app.buy_goods('p','grain',4)
        with self.repo.transaction() as w:
            w.markets['aurora','grain'].stock=self.repo.catalog.economy_markets['aurora','grain']['stock_limit']
        self.app.sell_goods('p','grain',4)
        self.assertEqual(self.market()['buyback_available'],0)
        self.assertLessEqual(self.market()['stock'],self.repo.catalog.economy_markets['aurora','grain']['stock_limit'])
        self.clock.advance(59);self.assertEqual(self.market()['buyback_available'],0)
        self.repo.close();self.repo=SQLiteRepository(self.path);self.app=Application(self.repo,self.clock)
        self.clock.advance(1);self.assertEqual(self.market()['buyback_available'],2)
        self.assertEqual(self.market()['buyback_available'],2)
        self.clock.advance(60);self.assertEqual(self.market()['buyback_available'],4)

    def test_failed_sale_rolls_back_all_state(self):
        self.app.buy_goods('p','grain',5);before=self.world()
        with self.assertRaisesRegex(GameError,'INSUFFICIENT_BUYBACK'):self.app.sell_goods('p','grain',5)
        self.assertEqual(self.world(),before)

    def test_invalid_numbers_and_failures_no_mutation(self):
        self.market();before=self.world()
        for qty in (0,-1,True,'1',MAX_VALUE+1):
            for call in (self.app.buy_goods,self.app.sell_goods):
                with self.assertRaises(GameError):call('p','grain',qty)
                self.assertEqual(self.world(),before)
        with self.assertRaises(GameError):self.app.sell_goods('p','grain',1)
        self.assertEqual(self.world(),before)

    def test_shared_quota_and_idempotent_sale(self):
        self.app.create_player('q','Q')
        self.app.buy_goods('p','grain',4)
        result=self.app.sell_goods('p','grain',2,request_id='once')
        self.assertEqual(result,self.app.sell_goods('p','grain',2,request_id='once'))
        self.assertEqual(self.app.get_market('q')['entries'][0]['buyback_available'],2)

    def test_limits_consider_volume_funds_and_own_cargo(self):
        row=self.market();self.assertGreater(row['max_buy'],0)
        self.app.buy_goods('p','grain',row['max_buy'])
        self.assertEqual(self.market()['max_buy'],0)
        self.assertEqual(self.market()['max_sell'],min(4,row['max_buy']))

    def test_immediate_roundtrip_does_not_profit(self):
        cash=self.app.get_player('p')['cash']
        for _ in range(4):
            self.app.buy_goods('p','grain',1);self.app.sell_goods('p','grain',1)
        self.assertEqual(self.app.get_player('p')['cash'],cash)
        self.assertEqual(self.market()['buyback_available'],0)

    def test_offline_equals_incremental_and_clock_backwards(self):
        self.app.buy_goods('p','grain',4);self.app.sell_goods('p','grain',4)
        self.clock.advance(30);self.market();self.clock.advance(30);self.market()
        self.clock.advance(30);self.market();self.clock.advance(30)
        self.assertEqual(self.market()['buyback_available'],4)
        self.clock.value=110;self.assertEqual(self.market()['buyback_available'],4)
        self.repo.close();self.repo=SQLiteRepository(self.path);self.app=Application(self.repo,self.clock)
        self.clock.value=10000;self.assertEqual(self.market()['buyback_available'],4)

    def test_configuration_hash_and_no_dynamic_state_in_hash(self):
        old=copy.deepcopy(self.data);old.pop('market_buyback')
        original=fingerprint(Catalog(old));enabled=fingerprint(self.repo.catalog)
        self.assertNotEqual(original['sha256'],enabled['sha256'])
        changed=copy.deepcopy(self.data);changed['market_buyback']['recovery_units']=3
        self.assertNotEqual(enabled['sha256'],fingerprint(Catalog(changed))['sha256'])
        self.app.buy_goods('p','grain',1);self.app.sell_goods('p','grain',1)
        self.assertEqual(enabled,fingerprint(self.repo.catalog))

    def test_invalid_policy_rejected(self):
        for field,value in [('capacity',0),('initial',5),('interval_seconds',0),('recovery_units',True)]:
            data=copy.deepcopy(self.data);data['market_buyback'][field]=value
            with self.assertRaises(GameError):Catalog(data)


class TradeUITests(unittest.TestCase):
    def menu(self):
        from tests.test_bbs_ui import Backend
        from starroute_bbs.menu import Menu
        from starroute_bbs.terminal import Terminal
        return Menu(Terminal(Backend()))

    def test_language_and_echo_preserve_actual_arguments(self):
        m=self.menu()
        self.assertEqual(m.echo('buy grain 1'),'BUY GRAIN 1')
        m.state='FREE_TEXT';self.assertEqual(m.echo('My Star'),'My Star')
        m.open('language');self.assertIn('[2] English / 英語',m.panel())

    def test_insurance_success_has_no_duplicate_navigation(self):
        m=self.menu();m.refresh();m.open('insure');m.commit()
        self.assertEqual(m.notice,'保険に加入しました。')

    def test_quantity_has_all_market_fields(self):
        m=self.menu();m.refresh();m.open('buy');m.handle('1')
        panel='\n'.join(m.panel())
        for label in ('販売在庫','買取可能数','現在保有数','積載残量','購入上限'):self.assertIn(label,panel)


if __name__=='__main__':unittest.main()
