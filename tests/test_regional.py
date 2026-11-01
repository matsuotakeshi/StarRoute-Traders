import copy,json,tempfile,unittest
from pathlib import Path
from starroute.catalog import Catalog
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.model import GameError,MAX_VALUE
from starroute.rules import fingerprint,effective_rules
from starroute.adapters.cli import CLI
ROOT=Path(__file__).resolve().parents[1]
def trial():return json.loads((ROOT/'examples/regional-trial.json').read_text(encoding='utf-8'))
class RegionalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'world.db';self.clock=ManualClock(100)
    def ready(self,data=None):
        r=SQLiteRepository(self.path,Catalog(data or trial()),now=100);self.addCleanup(r.close);a=Application(r,self.clock);a.create_player('p','P');return r,a
    def test_single_source_near_far_baseline(self):
        d=trial();d['production']['sources']=[s for s in d['production']['sources'] if not (s['goods_id']=='grain' and s['planet_id']=='forge')]
        c=Catalog(d)
        self.assertEqual([c.regional_anchors[p,'grain']['distance'] for p in ('aurora','forge','haven')],[0,3,6])
        self.assertEqual([c.regional_anchors[p,'grain']['base_price'] for p in ('aurora','forge','haven')],[100,160,220])
    def test_multiple_sources_use_nearest_not_imports(self):
        c=Catalog(trial());self.assertEqual(c.regional_anchors['haven','grain']['distance'],4)
        self.assertEqual(c.regional_anchors['forge','grain']['distance'],0)
    def test_indirect_path_shorter_than_direct(self):
        d=trial();next(r for r in d['routes'] if r['id']=='haven-aurora')['distance']=20
        c=Catalog(d);self.assertEqual(c.regional_anchors['aurora','dense_warp_fuel']['distance'],7)
    def test_closed_routes_part_of_configured_geography(self):
        d=trial();before=Catalog(d).regional_anchors
        for r in d['routes']:r['is_open']=False
        self.assertEqual(before,Catalog(d).regional_anchors)
    def test_no_source_and_unreachable_alternative_prices(self):
        d=trial();d['production']['sources']=[s for s in d['production']['sources'] if s['goods_id']!='medicine']
        c=Catalog(d);self.assertEqual(c.regional_anchors['aurora','medicine']['basis'],'no_source')
        self.assertEqual(c.regional_anchors['aurora','medicine']['base_price'],600)
        d=trial();d['navigation']=None;d['routes']=[d['routes'][0]]
        c=Catalog(d);self.assertEqual(c.regional_anchors['aurora','dense_warp_fuel']['basis'],'unreachable')
        self.assertEqual(c.regional_anchors['aurora','dense_warp_fuel']['base_price'],2400)
    def test_oversupply_reverses_geographical_tendency(self):
        r,a=self.ready()
        with r.transaction() as w:
            w.markets['haven','grain'].stock=500
            w.markets['aurora','grain'].stock=150
        near=a.quote_trade('p','grain',1,'buy')['total']
        with r.transaction() as w:w.players['p'].planet_id='haven'
        far=a.quote_trade('p','grain',1,'buy')['total']
        self.assertLess(far,near);self.assertEqual(far,1)
        receipt=a.buy_goods('p','grain',1);self.assertEqual(receipt['total'],far)
    def test_scarcity_and_price_bounds(self):
        d=trial()
        for row in d['economy']['markets']:row['min_price']=10;row['max_price']=120
        r,a=self.ready(d)
        with r.transaction() as w:w.markets['aurora','grain'].stock=1
        self.assertEqual(a.quote_trade('p','grain',1,'buy')['total'],120)
    def test_quantity_split_and_immediate_roundtrip(self):
        r,a=self.ready();quote=a.quote_trade('p','grain',3,'buy')['total']
        self.assertEqual(quote,306)
        paid=sum(a.buy_goods('p','grain',1)['total'] for _ in range(3));self.assertEqual(paid,quote)
        self.assertEqual(a.sell_goods('p','grain',3)['total'],paid);self.assertEqual(a.get_player('p')['cash'],5000)
    def test_market_display_matches_next_unit_quote(self):
        r,a=self.ready()
        for row in a.get_market('p')['entries']:
            self.assertEqual(row['price'],a.quote_trade('p',row['goods_id'],1,'buy')['total'])
    def test_dynamic_state_not_in_hash(self):
        r,a=self.ready();before=a.configuration_info();a.buy_goods('p','grain',1);a.invest('p','primary',100);self.clock.advance(60);a.get_market('p')
        self.assertEqual(before,a.configuration_info())
    def test_config_parameters_and_distance_change_hash(self):
        d=trial();before=fingerprint(Catalog(d))
        for field in ('origin_price','price_per_distance','unreachable_price'):
            new=copy.deepcopy(d);new['regional_prices']['goods'][0][field]+=1
            self.assertNotEqual(before,fingerprint(Catalog(new)))
        new=copy.deepcopy(d);new['routes'][0]['distance']+=1;self.assertNotEqual(before,fingerprint(Catalog(new)))
        d['regional_prices']['goods'].reverse();d['routes'].reverse();self.assertEqual(before,fingerprint(Catalog(d)))
    def test_overridden_market_anchor_not_effective(self):
        d=trial();before=fingerprint(Catalog(d));anchors=Catalog(d).regional_anchors
        for m in d['markets']:m['price']=9999
        self.assertEqual(before,fingerprint(Catalog(d)));self.assertEqual(anchors,Catalog(d).regional_anchors)
    def test_invalid_policy_and_overflow_rejected(self):
        mutations=[lambda d:d['regional_prices'].update(metric='unknown'),lambda d:d['regional_prices']['goods'].pop(),
            lambda d:d['regional_prices']['goods'].append(d['regional_prices']['goods'][0]),
            lambda d:d['regional_prices']['goods'][0].update(price_per_distance=-1),
            lambda d:d['regional_prices']['goods'][0].update(price_per_distance=MAX_VALUE)]
        for mutate in mutations:
            d=trial();mutate(d)
            with self.assertRaises(GameError):Catalog(d)
    def test_legacy_price_and_disabled_normalization(self):
        d=json.loads((ROOT/'examples/production-trial.json').read_text(encoding='utf-8'));before=fingerprint(Catalog(d));d['regional_prices']={'mode':'disabled'}
        self.assertEqual(before,fingerprint(Catalog(d)));r,a=self.ready(d)
        self.assertEqual(a.quote_trade('p','grain',1,'buy')['total'],61);self.assertFalse(a.get_region('p')['enabled'])
    def test_warp_fee_independent_of_regional_fuel_prices(self):
        r,a=self.ready();a.buy_goods('p','fusion_fuel',1);before=a.get_player('p')
        q=a.quote_navigation('p','forge','warp','fast');self.assertEqual(q['fuel_cost'],20)
        a.navigate('p','forge','warp','fast',q['quote_id']);after=a.get_player('p')
        self.assertEqual(before['cargo'],after['cargo']);self.assertEqual(before['cash']-after['cash'],20)
    def test_reopen_preserves_state_receipts_and_public_bounds(self):
        r,a=self.ready();receipt=a.buy_goods('p','grain',3,request_id='once');a.invest('p','primary',100);before=a.get_player('p');world=r.world_id;region=a.get_region('p');r.close()
        r=SQLiteRepository(self.path);self.addCleanup(r.close);a=Application(r,self.clock)
        self.assertEqual(r.world_id,world);self.assertIsNone(r.backup_path);self.assertEqual(before,a.get_player('p'))
        self.assertEqual(receipt,a.buy_goods('p','grain',3,request_id='once'));self.assertEqual(region,a.get_region('p'))
        self.assertNotIn('private_caps',json.dumps(region))
    def test_ja_en_region_cli(self):
        r,a=self.ready()
        for lang in ('ja','en'):
            out=[];cli=CLI(a,'p',output=out.append,language=lang)
            self.assertEqual(cli.safe_execute('region'),(True,0));self.assertTrue(any('grain' in s and '100' in s for s in out))
