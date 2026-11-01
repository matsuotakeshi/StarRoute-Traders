import copy
import json
import tempfile
import unittest
from pathlib import Path
from starroute.catalog import Catalog
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.model import GameError
from starroute.rules import effective_rules,fingerprint
from starroute.adapters.cli import CLI
ROOT=Path(__file__).resolve().parents[1]
FUELS=('fusion_fuel','dense_warp_fuel')
def trial():return json.loads((ROOT/'examples/fuel-commodities-trial.json').read_text(encoding='utf-8'))
class FuelCommodityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'world.db';self.clock=ManualClock(100)
    def ready(self,data=None):
        r=SQLiteRepository(self.path,Catalog(data or trial()),now=100);self.addCleanup(r.close)
        a=Application(r,self.clock);a.create_player('p','P');return r,a
    def warp(self,a):
        q=a.quote_navigation('p','forge','warp','fast')
        return a.navigate('p','forge','warp','fast',q['quote_id'],request_id='trip')
    def test_normal_goods_buy_hold_sell_and_volume(self):
        r,a=self.ready()
        for good in FUELS:a.buy_goods('p',good,1)
        self.assertEqual(a.get_player('p')['used_capacity'],3)
        self.assertEqual(a.get_player('p')['cash'],3498)
        a.sell_goods('p','dense_warp_fuel',1);a.sell_goods('p','fusion_fuel',1)
        self.assertEqual(a.get_player('p')['cash'],5000)
        self.assertEqual(len(a.trade_ledger('p')),4)
    def test_capacity_and_stock_constraints_apply(self):
        r,a=self.ready()
        with r.transaction() as w:
            w.players['p'].cash=100000;w.players['p'].cargo['grain']=39
        with self.assertRaises(GameError) as cm:a.buy_goods('p','dense_warp_fuel',1)
        self.assertEqual(cm.exception.code,'INSUFFICIENT_CAPACITY')
        with self.assertRaises(GameError):a.buy_goods('p','fusion_fuel',11)
        self.assertEqual(a.trade_ledger('p'),[])
    def test_zero_stock_no_fuel_cargo_warp_succeeds(self):
        r,a=self.ready()
        with r.transaction() as w:
            for (planet,good),market in w.markets.items():
                if good in FUELS:market.stock=0
        result=self.warp(a)
        self.assertEqual(result['fuel_cost'],20);self.assertEqual(a.get_player('p')['cash'],4980)
        self.assertEqual(a.get_player('p')['cargo'],[])
    def test_warp_preserves_cargo_and_deducts_credits_only(self):
        r,a=self.ready()
        for good in FUELS:a.buy_goods('p',good,1)
        before=a.get_player('p');self.warp(a);after=a.get_player('p')
        self.assertEqual(before['cargo'],after['cargo']);self.assertEqual(before['cash']-after['cash'],20)
        self.clock.advance(2)
        for good in FUELS:a.sell_goods('p',good,1)
        self.assertEqual(a.get_player('p')['cash'],5978)
    def test_fuel_cannot_substitute_for_missing_credits(self):
        r,a=self.ready()
        with r.transaction() as w:w.players['p'].cash=19;w.players['p'].cargo={'fusion_fuel':20}
        with self.assertRaises(GameError) as cm:self.warp(a)
        self.assertEqual(cm.exception.code,'INSUFFICIENT_FUNDS')
        p=a.get_player('p');self.assertEqual(p['cash'],19);self.assertEqual(p['cargo'][0]['quantity'],20)
        self.assertIsNone(p['destination_id'])
    def test_market_crash_surge_and_stock_dont_change_quote_or_fee(self):
        r,a=self.ready();before=a.quote_navigation('p','forge','warp','fast')
        for price,stock in [(1,0),(999999,100)]:
            with r.transaction() as w:
                for (planet,good),market in w.markets.items():
                    if good in FUELS:market.price=price;market.stock=stock
            self.assertEqual(before,a.quote_navigation('p','forge','warp','fast'))
        self.assertEqual(self.warp(a)['fuel_cost'],20)
    def test_cargo_quantity_does_not_discount_fee(self):
        r,a=self.ready()
        for quantity in (0,1,20):
            with r.transaction() as w:w.players['p'].cargo={'fusion_fuel':quantity} if quantity else {}
            self.assertEqual(a.quote_navigation('p','forge','warp','fast')['fuel_cost'],20)
    def test_planet_production_and_price_curve_apply(self):
        r,a=self.ready();self.assertEqual(a.quote_trade('p','fusion_fuel',2,'buy')['total'],603)
        self.clock.advance(60);a.get_production('p')
        stocks={(row['planet_id'],row['goods_id']):row['stock'] for row in r.connection.execute('SELECT * FROM markets')}
        self.assertEqual((stocks['aurora','fusion_fuel'],stocks['forge','fusion_fuel'],stocks['haven','fusion_fuel']),(13,11,10))
        self.assertEqual((stocks['aurora','dense_warp_fuel'],stocks['haven','dense_warp_fuel']),(4,5))
        self.assertLess(a.quote_trade('p','fusion_fuel',1,'buy')['total'],301)
    def test_normal_and_docking_free_with_fuel_cargo(self):
        r,a=self.ready();a.buy_goods('p','fusion_fuel',1);before=a.get_player('p')
        self.assertEqual(a.dock('p')['fee'],0);self.assertEqual(a.depart('p','forge')['fee'],0)
        self.clock.advance(4);self.assertEqual(a.dock('p')['fee'],0)
        after=a.get_player('p');self.assertEqual(before['cash'],after['cash']);self.assertEqual(before['cargo'],after['cargo'])
    def test_config_sections_independent_and_hashed(self):
        d=trial();before=effective_rules(Catalog(d));h=fingerprint(Catalog(d))
        for m in d['markets']:
            if m['goods_id'] in FUELS:m['price']*=3
        after=effective_rules(Catalog(d))
        self.assertEqual(before['navigation'],after['navigation']);self.assertNotEqual(h,fingerprint(Catalog(d)))
        r,a=self.ready(d);self.assertEqual(a.quote_navigation('p','forge','warp','fast')['fuel_cost'],20)
    def test_replay_and_restart_preserve_fuel_cargo(self):
        r,a=self.ready();a.buy_goods('p','dense_warp_fuel',1);q=a.quote_navigation('p','forge','warp','fast');result=self.warp(a);r.close()
        r=SQLiteRepository(self.path);self.addCleanup(r.close);a=Application(r,self.clock)
        self.assertEqual(a.navigate('p','forge','warp','fast',q['quote_id'],request_id='trip'),result)
        self.assertEqual(a.get_player('p')['cash'],3779)
        self.assertEqual(a.get_player('p')['cargo'][0]['quantity'],1)
        self.assertEqual(r.connection.execute('SELECT count(*) FROM voyages').fetchone()[0],1)
    def test_ja_en_names_and_no_refuel_command(self):
        r,a=self.ready()
        for lang,expected in [('ja','核融合燃料'),('en','Fusion Fuel')]:
            out=[];cli=CLI(a,'p',output=out.append,language=lang);cli.execute('market')
            self.assertTrue(any(expected in line for line in out))
            self.assertEqual(cli.safe_execute('refuel'),(True,1))
