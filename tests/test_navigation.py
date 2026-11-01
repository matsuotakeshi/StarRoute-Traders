"""Phase 3B: provisional timetables are fixtures, never final economic rules."""
import copy
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from starroute.catalog import Catalog
from starroute.repository import SQLiteRepository, SCHEMA_VERSION
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.model import GameError, MAX_VALUE
from starroute.adapters.cli import CLI
from test_ships import test_catalog_data


def trial_data():
    d=test_catalog_data()
    plans=[]
    for ship in d['ships']:
        p=ship['profile'];engineering=p['ship_type']=='engineering'
        options=[]
        if engineering:
            options.append(dict(level='fast',speed=10,seconds=4,fuel_cost=12))
            if p['max_warp_speed']>=20:options.append(dict(level='faster',speed=20,seconds=2,fuel_cost=24))
        else:
            options.append(dict(level='fast',speed=20,seconds=2,fuel_cost=20))
            if p['max_warp_speed']>=40:options.append(dict(level='faster',speed=40,seconds=1,fuel_cost=60))
        for route in d['routes']:
            plans.append(dict(ship_id=ship['id'],route_id=route['id'],normal_seconds=8 if engineering else 4,warp_options=copy.deepcopy(options)))
    d['navigation']=dict(status='provisional',plans=plans)
    return d


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/'world.db');self.clock=ManualClock(100)

    def open(self,data=None):
        r=SQLiteRepository(self.path,Catalog(data) if data else None,now=100);self.addCleanup(r.close)
        return r,Application(r,self.clock)

    def ready(self,data=None):
        r,a=self.open(data or trial_data());a.create_player('p','P');return r,a

    def test_normal_is_free_even_with_nonzero_saved_route_fee(self):
        d=trial_data();d['routes'][0]['fee']=6000;r,a=self.ready(d)
        q=a.quote_navigation('p','forge');self.assertEqual((q['seconds'],q['fuel_cost']),(4,0))
        a.depart('p','forge');self.assertEqual(a.get_player('p')['cash'],5000)
        self.assertEqual(r.connection.execute("SELECT fee FROM routes WHERE id='aurora-forge'").fetchone()[0],6000)

    def test_normal_time_same_across_grade_armed_and_engineering_slower(self):
        d=trial_data();c=Catalog(d)
        for ship in c.ships:
            local=SQLiteRepository(':memory:',c,now=100)
            try:
                a=Application(local,self.clock);a.create_player('p','P')
                with local.transaction() as world:world.players['p'].ship_id=ship
                q=a.quote_navigation('p','forge')
                self.assertEqual(q['seconds'],8 if ship.startswith('engineering') else 4)
                self.assertEqual(q['fuel_cost'],0)
            finally:local.close()

    def test_quote_warp_confirm_and_persist(self):
        r,a=self.ready();q=a.quote_navigation('p','forge','warp','fast')
        self.assertEqual((q['seconds'],q['fuel_cost'],q['policy_status']),(2,20,'provisional'))
        self.assertEqual(a.get_player('p')['cash'],5000)
        receipt=a.navigate('p','forge','warp','fast',q['quote_id'],request_id='trip')
        self.assertEqual(receipt['arrival_at'],102);self.assertEqual(a.get_player('p')['cash'],4980)
        r2=SQLiteRepository(self.path);self.addCleanup(r2.close);aa=Application(r2,self.clock)
        self.assertEqual(aa.navigate('p','forge','warp','fast',q['quote_id'],request_id='trip'),receipt)
        self.assertEqual(aa.latest_voyage('p')['fuel_cost'],20)
        self.assertEqual(r2.connection.execute('SELECT count(*) FROM voyages').fetchone()[0],1)
        self.clock.advance(2);self.assertEqual(aa.get_player('p')['planet_id'],'forge')
        self.assertTrue(aa.latest_voyage('p')['arrived']);self.assertEqual(aa.get_player('p')['cash'],4980)

    def test_warp_requires_quote_and_rejects_changed_or_other_player_quote(self):
        r,a=self.ready();q=a.quote_navigation('p','forge','warp','fast')
        with self.assertRaises(GameError):a.navigate('p','forge','warp','fast')
        with self.assertRaises(GameError):a.navigate('p','forge','warp','fast','bad')
        a.create_player('other','Other')
        with self.assertRaises(GameError):a.navigate('other','forge','warp','fast',q['quote_id'])
        q2=a.quote_navigation('p','haven','warp','fast')
        with self.assertRaises(GameError):a.navigate('p','forge','warp','fast',q2['quote_id'])
        self.assertEqual(a.get_player('p')['cash'],5000)

    def test_insufficient_fuel_funds_roll_back_and_request_reusable(self):
        r,a=self.ready()
        with r.transaction() as world:world.players['p'].cash=19
        q=a.quote_navigation('p','forge','warp','fast')
        with self.assertRaises(GameError) as cm:a.navigate('p','forge','warp','fast',q['quote_id'],request_id='trip')
        self.assertEqual(cm.exception.code,'INSUFFICIENT_FUNDS')
        self.assertEqual((a.get_player('p')['cash'],a.get_player('p')['destination_id']),(19,None))
        self.assertIsNone(a.latest_voyage('p'))
        with r.transaction() as world:world.players['p'].cash=20
        a.navigate('p','forge','warp','fast',q['quote_id'],request_id='trip')
        self.assertEqual(a.get_player('p')['cash'],0)

    def test_dock_free_repeated_and_during_travel_rejected(self):
        r,a=self.ready();before=a.get_player('p')
        for _ in range(4):self.assertEqual(a.dock('p')['fee'],0)
        self.clock.advance(10000);a.dock('p');self.assertEqual(a.get_player('p')['cash'],before['cash'])
        a.depart('p','forge')
        with self.assertRaises(GameError):a.dock('p')
        self.clock.advance(4);self.assertEqual(a.dock('p')['planet_id'],'forge')
        self.assertEqual(a.get_player('p')['cash'],before['cash'])

    def test_all_planets_and_ships_have_free_docking(self):
        r,a=self.ready()
        for ship in r.catalog.ships:
            for planet in r.catalog.planets:
                with r.transaction() as world:
                    world.players['p'].ship_id=ship;world.players['p'].planet_id=planet
                self.assertEqual(a.dock('p')['fee'],0)
        self.assertEqual(a.get_player('p')['cash'],5000)

    def test_speed_limit_and_faster_warp_tradeoff(self):
        d=trial_data();d['starting']['ship_id']='normal_2';r,a=self.ready(d)
        slow=a.quote_navigation('p','forge','warp','fast');fast=a.quote_navigation('p','forge','warp','faster')
        self.assertGreater(fast['fuel_cost'],slow['fuel_cost']);self.assertLess(fast['seconds'],slow['seconds'])
        with r.transaction() as world:world.players['p'].ship_id='engineering_1'
        with self.assertRaises(GameError):a.quote_navigation('p','forge','warp','faster')

    def test_quote_rechecks_route_and_range_at_confirmation(self):
        r,a=self.ready();q=a.quote_navigation('p','forge','warp','fast')
        with r.transaction() as world:world.routes['aurora-forge']['is_open']=False
        with self.assertRaises(GameError):a.navigate('p','forge','warp','fast',q['quote_id'])
        self.assertEqual(a.get_player('p')['cash'],5000)
        r.connection.execute("UPDATE routes SET is_open=1,distance=100 WHERE id='aurora-forge'")
        with self.assertRaises(GameError):a.navigate('p','forge','warp','fast',q['quote_id'])

    def test_arrival_overflow_does_not_charge(self):
        r,a=self.ready();q=a.quote_navigation('p','forge','warp','fast');self.clock.advance(MAX_VALUE-101)
        with self.assertRaises(GameError):a.navigate('p','forge','warp','fast',q['quote_id'])
        self.assertEqual(a.get_player('p')['cash'],5000)

    def test_depart_after_unobserved_arrival_records_correct_origin(self):
        r,a=self.ready();a.depart('p','forge');self.clock.advance(4)
        a.depart('p','aurora')
        self.assertEqual(a.latest_voyage('p')['origin_id'],'forge')
        self.assertEqual(a.latest_voyage('p')['destination_id'],'aurora')

    def test_voyage_write_failure_rolls_back_cost_and_operation_history(self):
        r,a=self.ready();q=a.quote_navigation('p','forge','warp','fast')
        r.connection.execute("CREATE TRIGGER no_voyage BEFORE INSERT ON voyages BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):a.navigate('p','forge','warp','fast',q['quote_id'],request_id='trip')
        self.assertEqual(a.get_player('p')['cash'],5000)
        self.assertIsNone(r.connection.execute("SELECT 1 FROM operation_history WHERE request_id='trip'").fetchone())

    def test_concurrent_warp_retry_charges_once(self):
        r,a=self.ready();q=a.quote_navigation('p','forge','warp','fast');barrier=threading.Barrier(2);results=[];errors=[]
        def worker():
            rr=None
            try:
                rr=SQLiteRepository(self.path);aa=Application(rr,ManualClock(100));barrier.wait(5)
                results.append(aa.navigate('p','forge','warp','fast',q['quote_id'],request_id='race'))
            except BaseException as e:errors.append(e)
            finally:
                if rr:rr.close()
        threads=[threading.Thread(target=worker) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join(15)
        self.assertFalse(any(t.is_alive() for t in threads));self.assertEqual(errors,[])
        self.assertEqual(len(results),2);self.assertEqual(results[0],results[1]);self.assertEqual(a.get_player('p')['cash'],4980)

    def test_v3_migration_preserves_pending_and_old_paid_receipt(self):
        c=sqlite3.connect(self.path);c.executescript((Path(__file__).parent/'fixtures/v3.sql').read_text(encoding='utf-8'))
        payload=json.loads(c.execute("SELECT result FROM operation_history WHERE request_id='go'").fetchone()[0]);payload['fee']=35
        c.execute("UPDATE operation_history SET result=? WHERE request_id='go'",(json.dumps(payload),));c.execute("UPDATE player_state SET cash=4365")
        c.commit();tables=[x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'")];old={t:c.execute('SELECT * FROM '+t).fetchall() for t in tables};c.close()
        r,a=self.open()
        for t in tables:
            if t!='metadata':self.assertEqual(old[t],[tuple(x) for x in r.connection.execute('SELECT * FROM '+t)])
        self.assertIn('.v3-backup-',r.backup_path)
        self.assertEqual(a.depart('legacy','forge',request_id='go')['fee'],35)
        self.assertEqual(a.get_player('legacy')['arrival_at'],102);self.assertEqual(a.get_player('legacy')['cash'],4365)
        self.assertIsNone(a.latest_voyage('legacy')['fuel_cost'])
        self.clock.advance(2);self.assertEqual(a.dock('legacy')['fee'],0)
        a.depart('legacy','aurora');self.assertEqual(a.get_player('legacy')['cash'],4365)

    def test_migration_failure_rolls_back_v3(self):
        c=sqlite3.connect(self.path);c.executescript((Path(__file__).parent/'fixtures/v3.sql').read_text(encoding='utf-8'));c.close()
        original=SQLiteRepository._navigation
        def fail(r):original(r);raise RuntimeError('injected')
        with patch.object(SQLiteRepository,'_navigation',fail):
            with self.assertRaises(RuntimeError):SQLiteRepository(self.path)
        c=sqlite3.connect(self.path)
        self.assertEqual(c.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0],'3')
        self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='voyages'").fetchone());c.close()

    def test_unconfigured_legacy_warp_is_not_silently_priced(self):
        r,a=self.open();a.create_player('p','P')
        with self.assertRaises(GameError) as cm:a.quote_navigation('p','forge','warp','fast')
        self.assertEqual(cm.exception.code,'WARP_NOT_CONFIGURED');self.assertEqual(a.quote_navigation('p','forge')['seconds'],2)

    def test_invalid_plans_rejected(self):
        for key,value in [('fuel_cost',0),('fuel_cost',-1),('speed',1000),('seconds',4),('seconds',True)]:
            d=trial_data();d['navigation']['plans'][0]['warp_options'][0][key]=value
            with self.subTest(key=key,value=value):
                with self.assertRaises(GameError):Catalog(d)
        d=trial_data();d['navigation']['plans'].pop()
        with self.assertRaises(GameError):Catalog(d)
        d=trial_data();d['navigation']['plans'][0]['normal_seconds']=3
        with self.assertRaises(GameError):Catalog(d)
        d=trial_data();d['navigation']['plans'][9]['warp_options'][1]['fuel_cost']=1
        with self.assertRaises(GameError):Catalog(d)

    def test_navigation_policy_tamper_rejected(self):
        r,a=self.ready();r.connection.execute("UPDATE navigation_policy SET policy='null'")
        with self.assertRaises(GameError) as cm:SQLiteRepository(self.path)
        self.assertEqual(cm.exception.code,'NAVIGATION_POLICY_MISMATCH')

    def test_cli_quote_confirmation_and_free_dock_both_languages(self):
        r,a=self.ready()
        for lang in ('ja','en'):
            output=[];cli=CLI(a,'p',output.append,language=lang)
            self.assertEqual(cli.safe_execute('warp forge fast')[1],1)
            self.assertEqual(cli.safe_execute('quote forge warp fast')[1],0)
            self.assertTrue(any('20 Cr' in line for line in output))
            self.assertEqual(cli.safe_execute('dock')[1],0)
        self.assertEqual(cli.safe_execute('request t warp forge fast')[1],0)
        self.assertEqual(cli.safe_execute('request t warp forge fast')[1],0)
        self.assertEqual(a.get_player('p')['cash'],4980)

if __name__=='__main__':unittest.main()
