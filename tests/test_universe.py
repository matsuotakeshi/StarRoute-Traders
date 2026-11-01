import copy
import json
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout,redirect_stderr
from io import StringIO
from starroute.catalog import Catalog
from starroute.universe import generate,normal_planets,public_info
from starroute.rules import fingerprint
from starroute.repository import SQLiteRepository,SCHEMA_VERSION
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.model import GameError
from starroute.presentation import Presentation
from starroute.generate import main

ROOT=Path(__file__).resolve().parents[1]

class UniverseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template=Catalog.load(ROOT/'examples/industry-effects-trial.json').data
        cls.params=json.loads((ROOT/'examples/universe-generator-trial.json').read_text())
        cls.data=generate(cls.template,cls.params,'acceptance-001')

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'world.db';self.clock=ManualClock(100)

    def open(self,data=None):
        r=SQLiteRepository(self.path,Catalog(data) if data else None,now=100);self.addCleanup(r.close)
        return r,Application(r,self.clock)

    def test_formal_48_names_ids_and_localization(self):
        rows=normal_planets();self.assertEqual(len(rows),48)
        self.assertEqual(rows[0],dict(id='001',ja='アルヴェラ',en='Alvera'))
        self.assertEqual(rows[-1],dict(id='048',ja='ヴォルテナ',en='Voltena'))
        self.assertEqual({p['id'] for p in self.data['planets']},{r['id'] for r in rows})
        for lang in ('ja','en'):
            view=Presentation(lang)
            for row in rows:
                self.assertTrue(row['en'].isascii())
                self.assertEqual(view.name('planets',row['id'],row['en']),row[lang])
        self.assertNotIn('Eldorado',json.dumps(rows));self.assertNotIn('Arcadia',json.dumps(rows))

    def test_same_seed_same_definition_independent_identity(self):
        second=generate(self.template,self.params,'acceptance-001')
        self.assertNotEqual(second['universe']['universe_id'],self.data['universe']['universe_id'])
        self.assertEqual(second['universe']['definition_hash'],self.data['universe']['definition_hash'])
        self.assertEqual(second['universe']['coordinates'],self.data['universe']['coordinates'])
        self.assertEqual(second['production'],self.data['production'])

    def test_different_seed_different_world_same_rules(self):
        other=generate(self.template,self.params,'acceptance-002')
        for field in ('coordinates','definition_hash'):
            self.assertNotEqual(other['universe'][field],self.data['universe'][field])
        self.assertNotEqual(other['production'],self.data['production'])
        self.assertEqual(fingerprint(Catalog(other)),fingerprint(Catalog(self.data)))
        self.assertEqual(other['planets'],self.data['planets'])

    def test_unique_coordinates_and_connected_candidate_graph(self):
        d=self.data;coords={(p['x'],p['y']) for p in d['universe']['coordinates']};self.assertEqual(len(coords),48)
        self.assertTrue(all(0<=x<self.params['width'] and 0<=y<self.params['height'] for x,y in coords))
        seen={d['starting']['planet_id']}
        while True:
            before=len(seen)
            for r in d['routes']:
                if r['from'] in seen or r['to'] in seen:seen.update((r['from'],r['to']))
            if before==len(seen):break
        self.assertEqual(len(seen),48)
        self.assertEqual(sum(r['is_open'] for r in d['routes']),self.params['initial_open_routes'])
        self.assertTrue(any(not r['is_open'] for r in d['routes']))
        self.assertTrue(all(r['distance']<=min(s['max_distance'] for s in d['ships']) for r in d['routes']))

    def test_sources_supply_capacity_and_market_coverage(self):
        d=self.data;goods={r['id'] for r in d['goods']};self.assertEqual(len(d['markets']),48*len(goods))
        compositions={tuple(sorted(s['goods_id'] for s in d['production']['sources'] if s['planet_id']==p['id'])) for p in d['planets']}
        self.assertGreater(len(compositions),1)
        for good in goods:
            sources=[s for s in d['production']['sources'] if s['goods_id']==good]
            self.assertGreater(len(sources),1);self.assertGreater(len({s['units_per_tick'] for s in sources}),1)
        self.assertEqual(d['goods'],self.template['goods'])

    def test_regional_price_tendencies_use_generated_sources(self):
        c=Catalog(self.data)
        for good in c.goods:
            anchors=[v for (p,g),v in c.regional_anchors.items() if g==good]
            near=[a for a in anchors if a['distance']==0];far=[a for a in anchors if a['distance']>0]
            self.assertTrue(near and far)
            self.assertLess(near[0]['base_price'],max(a['base_price'] for a in far))

    def test_changed_seed_cannot_replace_saved_world(self):
        r,a=self.open(self.data);a.create_player('p','P');before=r.catalog.canonical();r.close()
        other=generate(self.template,self.params,'replacement')
        with self.assertRaises(GameError) as e:SQLiteRepository(self.path,Catalog(other))
        self.assertEqual(e.exception.code,'CONFIG_MISMATCH')
        r,a=self.open();self.assertEqual(before,r.catalog.canonical())

    def test_seed_sweep_preserves_generation_constraints(self):
        for n in range(12):
            with self.subTest(seed=n):
                d=generate(self.template,self.params,f'sweep-{n}')
                self.assertEqual(len(d['planets']),48)
                self.assertEqual(len({(r['x'],r['y']) for r in d['universe']['coordinates']}),48)
                self.assertTrue(any(r['is_open'] and d['starting']['planet_id'] in (r['from'],r['to']) for r in d['routes']))

    def test_save_reload_trade_invest_and_time(self):
        r,a=self.open(self.data);a.create_player('p','Captain');info=a.configuration_info();before=r.catalog.canonical()
        market=a.get_market('p');cargo=next(x for x in market['entries'] if x['stock'] and x['price']<=1000)
        a.buy_goods('p',cargo['goods_id'],1);a.sell_goods('p',cargo['goods_id'],1)
        a.invest('p','primary',100);self.clock.advance(120);a.get_production('p')
        stocks=[tuple(x) for x in r.connection.execute('SELECT * FROM markets')]
        progress=a.get_development('p');r.close();r,a=self.open()
        self.assertEqual(before,r.catalog.canonical());self.assertEqual(info,a.configuration_info())
        self.assertEqual(progress,a.get_development('p'))
        self.assertEqual(stocks,[tuple(x) for x in r.connection.execute('SELECT * FROM markets')])
        self.assertEqual(r.connection.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_start_trade_and_navigation_are_possible(self):
        r,a=self.open(self.data);a.create_player('p','P')
        available=[x for x in a.get_market('p')['entries'] if x['stock'] and x['price']<=a.get_player('p')['cash']]
        self.assertTrue(available);good=available[0]['goods_id'];a.buy_goods('p',good,1)
        route=next(r for r in a.get_routes('p') if r['is_open'])
        a.depart('p',route['destination_id']);self.clock.advance(route['seconds']);a.sell_goods('p',good,1)
        self.assertEqual(a.get_player('p')['planet_id'],route['destination_id'])
        self.assertEqual(a.dock('p')['fee'],0)

    def test_closed_routes_refused_without_world_mutation(self):
        r,a=self.open(self.data);a.create_player('p','P')
        route=next(x for x in self.data['routes'] if not x['is_open'])
        r.connection.execute('UPDATE player_state SET planet_id=?',(route['from'],))
        with self.assertRaises(GameError) as e:a.depart('p',route['to'])
        self.assertEqual(e.exception.code,'ROUTE_CLOSED')
        self.assertIsNone(a.get_player('p')['destination_id'])

    def test_universe_hash_and_rules_ignore_dynamic_state_and_language(self):
        r,a=self.open(self.data);a.create_player('p','P');before=a.configuration_info()
        a.invest('p','tertiary',100);self.clock.advance(180);a.get_production('p');a.set_language('p','en')
        self.assertEqual(before,a.configuration_info())
        info=json.dumps(before)
        for hidden in ('seed','template','coordinates','private_caps','resources'):
            self.assertNotIn('"'+hidden+'"',info)

    def test_parameters_and_effective_template_change_rules_hash(self):
        p=copy.deepcopy(self.params);p['production_percent_max']+=1
        other=generate(self.template,p,'acceptance-001')
        self.assertNotEqual(fingerprint(Catalog(other)),fingerprint(Catalog(self.data)))
        t=copy.deepcopy(self.template);t['industry_effects']['planets'][0]['market_bps_per_unit']+=1
        other=generate(t,self.params,'acceptance-001')
        self.assertNotEqual(fingerprint(Catalog(other)),fingerprint(Catalog(self.data)))

    def test_display_names_do_not_change_hash_or_identity(self):
        d=copy.deepcopy(self.data);d['planets'][0]['name']='Display name override'
        c=Catalog(d);self.assertEqual(fingerprint(c),fingerprint(Catalog(self.data)))
        self.assertEqual(public_info(c),public_info(Catalog(self.data)))

    def test_field_order_normalization(self):
        d=json.loads(json.dumps(self.data,sort_keys=True));d['universe']['coordinates'].reverse();d['markets'].reverse()
        c=Catalog(d);self.assertEqual(fingerprint(c),fingerprint(Catalog(self.data)))
        self.assertEqual(public_info(c),public_info(Catalog(self.data)))

    def test_claimed_hash_does_not_certify_different_engine_inputs(self):
        mutations=[lambda d:d['universe']['coordinates'][0].update(x=127),
                   lambda d:d['production']['sources'][0].update(units_per_tick=999),
                   lambda d:d['routes'][0].update(is_open=not d['routes'][0]['is_open']),
                   lambda d:d['universe'].update(seed='modified'),
                   lambda d:d['universe'].update(universe_id=123),
                   lambda d:d['universe'].update(definition_hash='0'*64),
                   lambda d:d['universe'].update(generator_version='unsupported')]
        for change in mutations:
            d=copy.deepcopy(self.data);change(d)
            with self.subTest(change=change),self.assertRaises(GameError):Catalog(d)

    def test_invalid_or_impossible_generation_rejected(self):
        for update in (dict(width=2,height=2),dict(width=True),dict(extra=1),dict(initial_open_routes=0),dict(production_percent_min=0),dict(max_attempts=0)):
            with self.subTest(update=update),self.assertRaises((ValueError,GameError)):
                generate(self.template,{**self.params,**update},'bad')
        t=copy.deepcopy(self.template);t['starting']['cash']=0
        with self.assertRaisesRegex(ValueError,'constraints unsatisfied'):generate(t,{**self.params,'max_attempts':1},'bad')

    def test_admin_output_no_overwrite_or_silent_regeneration(self):
        target=Path(self.tmp.name)/'universe.json'
        args=['--template',str(ROOT/'examples/industry-effects-trial.json'),'--parameters',str(ROOT/'examples/universe-generator-trial.json'),'--seed','cli','--output',str(target)]
        with redirect_stdout(StringIO()),redirect_stderr(StringIO()):
            self.assertEqual(main(args),0);before=target.read_bytes();self.assertEqual(main(args),1)
        self.assertEqual(target.read_bytes(),before);self.assertEqual(len(Catalog.load(target).planets),48)

    def test_old_three_planet_world_is_preserved(self):
        old=Catalog.load();r,a=self.open(old.data);a.create_player('p','P');before=r.catalog.canonical();world=r.world_id;r.close()
        r,a=self.open();self.assertEqual(r.catalog.canonical(),before);self.assertEqual(r.world_id,world)
        self.assertEqual(len(r.catalog.planets),3);self.assertNotIn('universe',a.configuration_info())
        with self.assertRaises(GameError):SQLiteRepository(self.path,Catalog(self.data))

    def test_events_and_fuel_cost_independence(self):
        t=copy.deepcopy(self.template);t['market_events']=Catalog.load(ROOT/'examples/events-trial.json').data['market_events']
        for row in t['market_events']['targets']:row.update(surge_bps=10000,crash_bps=0)
        d=generate(t,self.params,'events');r,a=self.open(d);a.create_player('p','P')
        route=next(row for row in a.get_routes('p') if row['is_open']);dest=route['destination_id']
        before=a.quote_navigation('p',dest,'warp','fast')['fuel_cost'];self.clock.advance(60)
        self.assertTrue(a.get_events('p'));self.assertEqual(before,a.quote_navigation('p',dest,'warp','fast')['fuel_cost'])

if __name__=='__main__':unittest.main()
