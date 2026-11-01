from contextlib import closing
import copy
import json
import re
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from starroute.catalog import Catalog
from starroute.clock import ManualClock
from starroute.application import Application
from starroute.repository import SQLiteRepository
from starroute.model import GameError
from starroute.mechanics import apply_event,player_state,coordinates
from starroute.starmap import render
from starroute.universe_package import export_package,to_catalog
from starroute.import_local import initialize
from starroute.rules import fingerprint
from starroute.adapters.cli import CLI
from srt_universe_generator.levels import generate

ROOT=Path(__file__).resolve().parents[1]


class Phase3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        t=Catalog.load(ROOT/'examples/phase3-trial.json').data
        params=json.loads((ROOT/'examples/phase3-generator.json').read_text())
        levels=json.loads((ROOT/'examples/industry-levels-trial.json').read_text())
        cls.data=generate(t,params,levels,'phase3-acceptance','00000000-0000-0000-0000-000000000016')

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'game.db';self.clock=ManualClock(100)
        self.r=SQLiteRepository(self.path,Catalog(self.data),now=100);self.addCleanup(lambda:self.r.close())
        self.a=Application(self.r,self.clock);self.a.create_player('p','Pilot')
        self.engine=self.a.engine

    def call(self,method,*args,request_id=None):return self.a._call(method,'p',*args,request_id=request_id)

    def event(self,kind,target=None,event_id='test-event'):
        with self.r.transaction() as w:
            self.engine.update(w,self.clock.now())
            return apply_event(self.engine,w,event_id,kind,target or 'p')

    def ready_ship(self,sid):
        with self.r.transaction() as w:
            p=w.players['p'];p.ship_id=sid;p.cash=20000
            for i in ('primary','secondary','tertiary','quaternary'):w.developments[p.planet_id,i]=1

    def travel(self,sid='normal_2'):
        self.ready_ship(sid)
        route=next(r for r in self.a.get_routes('p') if r['is_open'])
        return self.a.depart('p',route['destination_id'])

    def test_48_30_coordinates_and_package(self):
        c=self.engine.catalog;self.assertEqual(len(c.planets),48);self.assertEqual(len(c.goods),30)
        coords=list(coordinates(c).values());self.assertEqual(len({tuple(p) for p in coords}),48)
        self.assertTrue(all(0<=x<240 and 0<=y<120 for x,y in coords))
        package=export_package(self.data);self.assertEqual(to_catalog(package).canonical(),c.canonical())
        for row in c.development_planets.values():
            for i,v in row['initial_progress'].items():self.assertLessEqual(v,row['private_caps'][i]);self.assertGreaterEqual(v,0);self.assertGreaterEqual(row['private_caps'][i],1)

    def test_local_import_exclusive_preserves_world(self):
        package=Path(self.tmp.name)/'universe.json';package.write_text(json.dumps(export_package(self.data)),encoding='utf8')
        with self.assertRaises(FileExistsError):initialize(package,self.path,100)
        self.assertEqual(self.a.get_player('p')['cash'],5000)
        other=Path(self.tmp.name)/'new.db';initialize(package,other,100)
        with closing(sqlite3.connect(other)) as c:self.assertEqual(c.execute('SELECT count(*) FROM planets').fetchone()[0],48)

    def test_ship_purchase_all_types_replay_and_capacity(self):
        for idx,sid in enumerate(('normal_1','armed_cruiser_1','engineering_1','normal_2','armed_cruiser_2','engineering_2')):
            self.ready_ship('normal_2' if sid!='normal_2' else 'normal_1')
            result=self.call('buy_ship',sid,request_id='buy'+str(idx));cash=self.a.get_player('p')['cash']
            self.assertEqual(self.call('buy_ship',sid,request_id='buy'+str(idx)),result)
            self.assertEqual(self.a.get_player('p')['cash'],cash)
        with self.r.transaction() as w:w.players['p'].cargo={'grain':30}
        with self.assertRaisesRegex(GameError,'INSUFFICIENT_CAPACITY'):self.call('buy_ship','normal_1')

    def test_sales_development_requirement_and_funds(self):
        with self.r.transaction() as w:
            p=w.players['p'];p.ship_id='normal_1';w.developments[p.planet_id,'secondary']=0
        with self.assertRaisesRegex(GameError,'SHIP_UNAVAILABLE'):self.call('buy_ship','armed_cruiser_2')
        with self.r.transaction() as w:w.developments[w.players['p'].planet_id,'secondary']=1;w.players['p'].cash=0
        with self.assertRaisesRegex(GameError,'INSUFFICIENT_FUNDS'):self.call('buy_ship','armed_cruiser_2')

    def test_donation_open_shared_jackpot_once(self):
        with self.r.transaction() as w:
            rid=next(k for k,r in w.routes.items() if not r['is_open']);w.players['p'].planet_id=w.routes[rid]['from'];distance=w.routes[rid]['distance'];w.players['p'].cash=20000
        result=self.call('donate',rid,distance*10,request_id='donation')
        self.assertTrue(result['opened']);self.assertGreater(result['jackpot'],0)
        cash=self.a.get_player('p')['cash'];self.assertEqual(self.call('donate',rid,distance*10,request_id='donation'),result)
        with self.assertRaisesRegex(GameError,'ROUTE_ALREADY_OPEN'):self.call('donate',rid,1)
        self.assertEqual(self.a.get_player('p')['cash'],cash)
        self.assertTrue(next(r for r in self.a.get_routes('p') if r['route_id']==rid)['is_open'])
        self.assertEqual(len([n for n in self.call('news') if n['kind']=='route_open']),1)

    def test_concurrent_last_donation_only_one_reward(self):
        self.a.create_player('q','Other')
        with self.r.transaction() as w:
            rid=next(k for k,r in w.routes.items() if not r['is_open']);amount=w.routes[rid]['distance']*10
            for p in w.players.values():p.planet_id=w.routes[rid]['from'];p.cash=20000
        barrier=threading.Barrier(2);results=[]
        def run(pid):
            r=SQLiteRepository(self.path);a=Application(r,self.clock)
            try:
                barrier.wait()
                try:results.append(a._call('donate',pid,rid,amount,request_id='same'))
                except GameError as e:results.append(e.code)
            finally:r.close()
        threads=[threading.Thread(target=run,args=(p,)) for p in ('p','q')]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(sum(isinstance(r,dict) for r in results),1)
        self.assertIn('ROUTE_ALREADY_OPEN',results)

    def test_engineering_fraction_is_saved(self):
        with self.r.transaction() as w:w.players['p'].planet_id=next(pid for pid,row in self.engine.catalog.development_planets.items() if row['private_caps']['primary']==5)
        self.ready_ship('engineering_1')
        with self.r.transaction() as w:w.developments[w.players['p'].planet_id,'primary']=0
        effects=[self.a.invest('p','primary',100)['effect_units'] for _ in range(4)]
        self.assertEqual(effects,[1,1,1,2])
        with self.assertRaisesRegex(GameError,'INVESTMENT_UNAVAILABLE'):self.a.invest('p','primary',100)

    def test_disaster_level_floor_maximum_news_and_replay(self):
        with self.r.transaction() as w:
            pid=w.players['p'].planet_id;w.developments[pid,'secondary']=1
        caps=copy.deepcopy(self.engine.catalog.development_planets[pid]['private_caps'])
        receipt=self.event('factory_accident',pid)
        self.assertEqual(receipt['changes'][0]['after'],0)
        self.assertEqual(self.event('factory_accident',pid),receipt)
        self.event('factory_accident',pid,'second')
        with self.r.transaction() as w:self.assertEqual(w.developments[pid,'secondary'],0)
        self.assertEqual(self.engine.catalog.development_planets[pid]['private_caps'],caps)
        self.assertEqual(len([n for n in self.call('news') if n['kind']=='factory_accident']),2)
        self.assertNotIn('private_caps',json.dumps(self.call('news')))

    def test_damage_supply_price_and_reopen(self):
        key=next(k for k,r in self.engine.catalog.production_sources.items() if r['industry']=='secondary')
        with self.r.transaction() as w:
            w.developments[key[0],'secondary']=1;w.players['p'].planet_id=key[0]
            from starroute.industry_effects import values
            for k,m in w.markets.items():m.production_rate,m.capacity=values(self.engine.catalog,w.developments,k)
            rate=w.markets[key].production_rate
        self.event('factory_accident',key[0]);self.r.close();self.r=SQLiteRepository(self.path);self.a=Application(self.r,self.clock);self.engine=self.a.engine
        self.clock.advance(self.engine.catalog.economy['tick_seconds']);self.a.update()
        with self.r.transaction() as w:self.assertLess(w.markets[key].production_rate,rate)
        # Reduced supply produces lower future stock / higher price than an undamaged control.
        from starroute.economy import price_at,base_price
        with self.r.transaction() as w:
            row=self.engine.catalog.economy_markets[key];m=w.markets[key];base=base_price(self.engine.catalog,m,*key)
            self.assertGreaterEqual(price_at(base,max(0,m.stock-1),row),price_at(base,m.stock+rate,row))

    def test_patrol_capacity_and_pirate_immunity(self):
        self.travel('armed_cruiser_2')
        with self.r.transaction() as w:w.players['p'].cargo={'grain':39}
        self.assertEqual(self.event('patrol')['quantity'],0)
        with self.assertRaisesRegex(GameError,'EVENT_NOT_ELIGIBLE'):self.event('pirate',event_id='attack')
        with self.r.transaction() as w:w.players['p'].cargo={}
        self.assertGreater(self.event('patrol',event_id='second')['quantity'],0)

    def test_mineral_zero_industry_and_no_dock_farming(self):
        self.ready_ship('engineering_1')
        with self.r.transaction() as w:w.developments[w.players['p'].planet_id,'primary']=0
        for _ in range(10):self.a.dock('p')
        self.assertFalse(self.call('news'))
        with patch('starroute.mechanics.draw',side_effect=lambda cfg,*keys:0 if str(keys[0]).startswith('mineral:') else 9999):
            self.clock.advance(300);self.a.update()
        minerals=[n for n in self.call('news') if n['kind']=='mineral'];self.assertEqual(len(minerals),1)
        self.assertEqual(minerals[0]['values']['goods_id'],'rare_metals')
        for _ in range(10):self.a.dock('p')
        self.assertEqual(len([n for n in self.call('news') if n['kind']=='mineral']),1)

    def test_insurance_and_wreck_once(self):
        self.ready_ship('normal_2');self.call('insure',request_id='insurance');cash=self.a.get_player('p')['cash']
        self.call('insure',request_id='insurance');self.assertEqual(self.a.get_player('p')['cash'],cash)
        route=next(r for r in self.a.get_routes('p') if r['is_open']);self.a.depart('p',route['destination_id'])
        receipt=self.event('wreck');self.assertTrue(receipt['insured_rescue']);self.assertEqual(receipt['ship_id'],'normal_2')
        self.assertEqual(self.event('wreck'),receipt)

    def test_bankruptcy_fixed_start_grade_and_repeat(self):
        for sid in ('normal_1','engineering_2','armed_cruiser_2'):
            self.ready_ship(sid)
            with self.r.transaction() as w:w.players['p'].cargo={'grain':10}
            receipt=self.call('bankrupt');self.assertEqual(receipt['ship_id'],'normal_1');self.assertEqual(receipt['cash'],1000)
            self.assertFalse(self.a.get_player('p')['cargo'])
        self.assertEqual(self.call('bankrupt')['cash'],1000)

    def test_flight_position_and_forbidden_commands(self):
        receipt=self.travel();before=self.call('flight');self.clock.advance(max(1,(receipt['arrival_at']-100)//2));mid=self.call('flight')
        self.assertNotEqual(before['position'],mid['position']);self.assertGreater(mid['remaining_seconds'],0)
        for method,args in [('buy_ship',('normal_1',)),('donate',('no',1)),('insure',()),('bankrupt',()),('invest',('primary',100)),('get_market',()),('get_ship',())]:
            with self.assertRaisesRegex(GameError,'IN_TRANSIT'):self.call(method,*args)
        self.assertIsInstance(self.call('news'),list)
        self.r.close();self.r=SQLiteRepository(self.path);self.a=Application(self.r,self.clock);self.engine=self.a.engine
        self.assertEqual(mid,self.call('flight'))

    def test_map_ascii_labels_viewport_and_color(self):
        planets=[dict(planet_id='a',position=[0,0],name_en='Alvera'),dict(planet_id='b',position=[239,119],name_en='Selnoa')]
        plain=render(planets,[0,0],width=20,height=5,names=True,color=False,docked_id='a')
        self.assertIn('*',plain);self.assertIn('+',plain);self.assertIn('Alvera',plain);self.assertNotIn('Selnoa',plain)
        self.assertEqual([len(r) for r in plain.splitlines()],[20]*5);self.assertTrue(plain.isascii())
        self.assertNotIn('Alvera',render(planets,[0,0],names=False,color=False))
        self.assertIn('Selnoa',render(planets,[239,119],width=30,height=6,names=True,color=False))
        self.assertIn('\x1b[32m',render(planets,[0,0],docked_id='a'))

    def test_cli_commands_and_locales(self):
        for lang in ('ja','en'):
            output=[];cli=CLI(self.a,'p',output.append,language=lang)
            for command in ('map 40 10','map-names on','map-names off','shipyard','news','status'):
                self.assertEqual(cli.safe_execute(command)[1],0,output)
            self.assertIn('ETA:', '\n'.join(output))

    def test_rule_hash_dynamic_state_excluded(self):
        before=fingerprint(self.engine.catalog)
        pid=self.a.get_player('p')['planet_id'];self.event('cyclone',pid)
        self.assertEqual(fingerprint(self.engine.catalog),before)
        d=copy.deepcopy(self.data);d.pop('universe');d['phase3']['restart_cash']+=1
        changed=Catalog(d);original=copy.deepcopy(d);original['phase3']['restart_cash']-=1
        self.assertNotEqual(fingerprint(changed),fingerprint(Catalog(original)))

    def test_migration_v9_backup_and_data_preserved(self):
        before=self.a.get_player('p');self.r.connection.execute('DROP TABLE phase3_state')
        self.r.connection.execute("UPDATE metadata SET value='9' WHERE key='schema_version'");self.r.close()
        self.r=SQLiteRepository(self.path);self.a=Application(self.r,self.clock)
        self.assertTrue(Path(self.r.backup_path).exists());self.assertEqual(before,self.a.get_player('p'))

    def test_failed_operation_rolls_back_all_state(self):
        before=self.r.connection.execute('SELECT state_json FROM phase3_state').fetchone()[0]
        with self.assertRaises(GameError):self.call('buy_ship','missing')
        self.assertEqual(before,self.r.connection.execute('SELECT state_json FROM phase3_state').fetchone()[0])

    def test_disaster_has_real_supply_and_price_effect_against_control(self):
        from starroute.industry_effects import values
        from starroute.economy import price_at,base_price
        with self.r.transaction() as w:
            key=next(k for k,row in self.engine.catalog.production_sources.items() if row['industry']=='secondary')
            w.developments[key[0],'secondary']=1
            for k,m in w.markets.items():m.production_rate,m.capacity=values(self.engine.catalog,w.developments,k)
            w.markets[key].stock=0
            damaged=copy.deepcopy(w);control=copy.deepcopy(w)
        apply_event(self.engine,damaged,'damage','factory_accident',key[0])
        tick=self.engine.catalog.economy['tick_seconds']
        # Finish the current period, then run the reduced-capacity period.
        for world in (control,damaged):self.engine.update(world,world.game_time+tick*2)
        self.assertLess(damaged.markets[key].stock,control.markets[key].stock)
        c=self.engine.catalog;row=c.economy_markets[key]
        def price(world):
            m=world.markets[key];return price_at(base_price(c,m,*key),max(0,m.stock-1),row)
        self.assertGreater(price(damaged),price(control))
        unaffected=next(k for k in damaged.markets if k[0]!=key[0])
        self.assertEqual(damaged.markets[unaffected],control.markets[unaffected])

    def test_large_and_small_time_updates_match(self):
        self.ready_ship('engineering_1')
        with self.r.transaction() as w:one=copy.deepcopy(w);many=copy.deepcopy(w)
        self.engine.update(one,1300)
        for t in range(110,1301,10):self.engine.update(many,t)
        self.assertEqual(one.players,many.players)
        self.assertEqual(one.markets,many.markets)
        self.assertEqual(one.developments,many.developments)
        self.assertEqual(one.phase3_state,many.phase3_state)

    def test_storm_no_backward_jump_and_replay(self):
        trip=self.travel();self.clock.advance((trip['arrival_at']-100)//3)
        before=self.call('flight');result=self.event('storm')
        after=self.call('flight');self.assertEqual(after['position'],before['position'])
        self.assertGreater(after['arrival_at'],before['arrival_at'])
        self.assertEqual(self.event('storm'),result)

    def test_pirate_failure_and_uninsured_wreck(self):
        self.travel();before=self.a.get_player('p')['cash']
        attack=self.event('pirate');self.assertEqual(self.a.get_player('p')['cash'],before-attack['loss'])
        self.event('failure',event_id='failure');wreck=self.event('wreck',event_id='wreck')
        self.assertFalse(wreck['insured_rescue']);self.assertEqual(wreck['ship_id'],'normal_1')
        self.assertEqual(wreck['cash'],1000);self.assertIsNone(self.a.get_player('p')['destination_id'])

    def test_route_engineering_bonus_and_invalid_request_rollback(self):
        self.ready_ship('engineering_1')
        with self.r.transaction() as w:
            rid=next(k for k,r in w.routes.items() if not r['is_open']);w.players['p'].planet_id=w.routes[rid]['from']
        result=self.call('donate',rid,4,request_id='bonus')
        self.assertEqual(result['effect_units'],5);self.assertEqual(result['paid_credits'],4)
        with self.assertRaisesRegex(GameError,'REQUEST_CONFLICT'):self.call('donate',rid,8,request_id='bonus')

    def test_master_new_operations_and_disclosure(self):
        from starroute.master import MasterService,ServerContext,Visibility,target_for
        a=self.a;a.create_account('bbs','user','Remote',request_id='register')
        pid=a.resolve_account('bbs','user')
        with self.r.transaction() as w:target=target_for(self.r,w);planet=w.players[pid].planet_id
        svc=MasterService(a);ctx=ServerContext(target,'bbs','user',Visibility(frozenset([planet]),frozenset([planet]),frozenset()))
        self.assertTrue(svc.execute(ctx,'shipyard',{}))
        sale=svc.execute(ctx,'buy_ship',{'ship_id':'engineering_1'},request_id='ship')
        self.assertEqual(sale['ship_id'],'engineering_1')
        self.assertEqual(svc.execute(ctx,'buy_ship',{'ship_id':'engineering_1'},request_id='ship'),sale)
        hidden=next(p for p in self.engine.catalog.planets if p!=planet)
        self.event('cyclone',hidden,'hidden-disaster')
        self.assertNotIn('hidden-disaster',json.dumps(svc.execute(ctx,'news',{})))
        empty=ServerContext(target,'bbs','user',Visibility())
        with self.assertRaisesRegex(GameError,'DISCLOSURE_DENIED'):svc.execute(empty,'flight',{})
        with self.assertRaisesRegex(GameError,'MASTER_REQUEST_INVALID'):svc.execute(ctx,'disaster',{})
        with self.assertRaisesRegex(GameError,'MASTER_REQUEST_INVALID'):svc.execute(ctx,'buy_ship',{'ship_id':'normal_1','price':0},request_id='tamper')

    def test_map_resizing_and_transit_toggle_rejected(self):
        from unittest.mock import patch
        import os
        output=[];cli=CLI(self.a,'p',output.append,language='ja')
        with patch('shutil.get_terminal_size',return_value=os.terminal_size((32,12))):cli.show_map()
        clean=re.sub(r'\x1b\[[0-9;]*m','',output[-1]);self.assertEqual(len(clean.splitlines()),7)
        self.assertTrue(all(len(line)==30 for line in clean.splitlines()))
        self.travel();self.assertEqual(cli.safe_execute('map-names on')[1],1)
        self.assertEqual(cli.safe_execute('news')[1],0)

    def test_updated_policy_values_change_hash(self):
        raw=copy.deepcopy(self.data);raw.pop('universe');before=fingerprint(Catalog(raw))
        for field in ('route_cost_per_distance','restart_cash','storm_delay','disaster_damage','loot_quantity'):
            d=copy.deepcopy(raw);d['phase3'][field]+=1
            self.assertNotEqual(before,fingerprint(Catalog(d)),field)

    def test_legacy_grid_height_128_remains_accepted(self):
        from starroute.generation_contract import parameters
        old=json.loads((ROOT/'examples/universe-generator-trial.json').read_text())
        old['height']=128
        self.assertEqual(parameters(old)['height'],128)
        modern=json.loads((ROOT/'examples/phase3-generator.json').read_text());modern['height']=128
        levels=json.loads((ROOT/'examples/industry-levels-trial.json').read_text())
        with self.assertRaises(ValueError):generate(Catalog.load(ROOT/'examples/phase3-trial.json').data,modern,levels,'bad-grid')

    def test_invalid_import_does_not_create_database(self):
        p=Path(self.tmp.name)/'bad.json';d=export_package(self.data);d['world']['planets'][0]['industries']['primary']['maximum_level']=0
        p.write_text(json.dumps(d),encoding='utf8');db=Path(self.tmp.name)/'bad.db'
        with self.assertRaises((GameError,ValueError)):initialize(p,db,100)
        self.assertFalse(db.exists())


if __name__=='__main__':unittest.main()
