import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from starroute.operations import Manager,initialize
from starroute.catalog import Catalog
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.repository import SQLiteRepository
from starroute.universe_package import export_package
from starroute.phase4_db import policy,policy_hash
from starroute.statistics import calculate,read_scores
from starroute.distribution import fetch,verify,safe_path,run
from srt_universe_generator.levels import generate

ROOT=Path(__file__).resolve().parents[1]


class Phase4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        template=Catalog.load(ROOT/'examples/phase3-trial.json').data
        params=json.loads((ROOT/'examples/phase3-generator.json').read_text())
        levels=json.loads((ROOT/'examples/industry-levels-trial.json').read_text())
        cls.packages=[export_package(generate(template,params,levels,'phase4-'+str(n)),created_at='2026-11-02T00:00:00+00:00') for n in range(3)]

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'game.db';initialize(self.path,100)
        self.m=Manager(self.path,100);self.addCleanup(self.m.close)

    def register(self,n=0):
        uid=self.m.stage(json.dumps(self.packages[n]).encode());self.m.register(uid);return uid

    def active(self):
        uid=self.register();self.m.prepare(uid,1,100);self.m.activate(1,uid);return uid

    def app(self):
        r=SQLiteRepository(self.path);self.addCleanup(r.close);return Application(r,ManualClock(100))

    def test_registration_separation(self):
        uid=self.register();self.assertEqual(self.m.item(uid)['state'],'REGISTERED')
        self.assertFalse(self.m.c.execute('SELECT * FROM p4_rounds').fetchall())
        self.assertEqual([r['action'] for r in self.m.c.execute('SELECT * FROM p4_audit')],['STAGED','VALIDATED','REGISTERED'])

    def test_duplicate(self):
        self.register();self.register();self.assertEqual(self.m.c.execute('SELECT count(*) FROM p4_universes').fetchone()[0],1)

    def test_conflict(self):
        self.register();p=copy.deepcopy(self.packages[0]);p['metadata']['created_at']='2026-11-03T00:00:00+00:00'
        with self.assertRaises(ValueError):self.m.stage(json.dumps(p).encode())

    def test_invalid_package(self):
        p=copy.deepcopy(self.packages[0]);p['schema_version']=999
        uid=self.m.stage(json.dumps(p).encode())
        with self.assertRaises(ValueError):self.m.register(uid)
        self.assertEqual(self.m.item(uid)['state'],'STAGED')

    def test_current_universe_unaffected(self):
        uid=self.active();self.register(1)
        self.assertEqual(self.m.repo._load().season_id,1);self.assertEqual(self.m.item(uid)['state'],'ACTIVE')

    def test_prepare_id_conflict(self):
        uid=self.register();self.m.prepare(uid,1,100)
        self.assertEqual(self.m.prepare(uid,1,100),1)
        with self.assertRaises(ValueError):self.m.prepare(uid,1,101)

    def test_prepared_no_gameplay(self):
        uid=self.register();self.m.prepare(uid,1,100)
        with self.assertRaises(Exception):self.app().create_player('p','Pilot')

    def test_end_deadline(self):
        self.active();a=self.app();a.create_player('p','Pilot');a.clock.value=2592100
        with self.assertRaises(Exception):a.get_player('p')

    def test_close_idempotent_and_hall(self):
        uid=self.active();a=self.app()
        for n in range(4):a.create_player('p'+str(n),'Same')
        self.m.finish(1,uid);self.m.finish(1,uid)
        self.assertEqual(self.m.c.execute('SELECT count(*) FROM p4_hall').fetchone()[0],12)
        self.assertEqual(self.m.c.execute('SELECT count(*) FROM p4_rankings').fetchone()[0],16)
        self.assertEqual(self.m.c.execute('SELECT count(*) FROM p4_statistics').fetchone()[0],4)
        self.assertEqual(self.m.inspect()['foreign_keys'],[])
        with self.assertRaises(Exception):a.buy_goods('p0',next(iter(a.engine.catalog.goods)),1)

    def test_empty_round(self):
        uid=self.active();self.m.finish(1,uid)
        self.assertEqual(read_scores(self.m.c,1),[])

    def test_small_hall(self):
        uid=self.active();self.app().create_player('p','Pilot');self.m.finish(1,uid)
        self.assertEqual(self.m.c.execute('SELECT count(*) FROM p4_hall').fetchone()[0],4)

    def test_immutable_hall(self):
        uid=self.active();self.app().create_player('p','Pilot');self.m.finish(1,uid)
        with self.assertRaises(sqlite3.IntegrityError):self.m.c.execute('DELETE FROM p4_hall')

    def test_switch_and_identity_preservation(self):
        old=self.active();a=self.app();a.create_account('bbs1','user','Same');a.create_account('bbs2','user','Same')
        uid=self.register(1);self.m.prepare(uid,2,100);self.m.activate(2,uid,1,old)
        w=self.m.repo._load();self.assertEqual(w.season_id,2);self.assertEqual(len(w.players),2)
        self.assertTrue(all(p.cash==self.m.repo.catalog.data['starting']['cash'] and not p.cargo and not p.destination_id for p in w.players.values()))
        self.assertEqual(self.m.c.execute('SELECT count(*) FROM p4_hall').fetchone()[0],8)
        self.assertEqual(self.m.inspect()['integrity'],['ok']);self.assertEqual(self.m.inspect()['foreign_keys'],[])
        self.assertEqual(self.m.archive(1)['tables']['seasons'][0]['id'],1)
        with self.assertRaises(Exception):a.get_player(next(iter(w.players)))

    def test_explicit_previous_target(self):
        self.active();uid=self.register(1);self.m.prepare(uid,2,100)
        with self.assertRaises(ValueError):self.m.activate(2,uid)
        self.assertEqual(self.m.repo._load().season_id,1)

    def test_new_initial_levels(self):
        self.active();w=self.m.repo._load()
        for pid,row in self.m.repo.catalog.development_planets.items():
            for i,level in row['initial_progress'].items():self.assertEqual(w.developments[pid,i],level)

    def test_scores_and_ties(self):
        self.active();a=self.app();a.create_player('b','B');a.create_player('a','A')
        scores=read_scores(self.m.c,1)
        self.assertEqual([r['player_id'] for r in scores if r['category']=='trade'],['a','b'])
        self.assertEqual(scores,read_scores(self.m.c,1))
        self.assertTrue(all('not_victory' in r['evaluation'] for r in scores if r['category']=='exploration'))

    def test_fifo_trade(self):
        self.active();a=self.app();a.create_player('p','P')
        good=next(r['goods_id'] for r in a.get_market('p')['entries'] if r['stock']>=2)
        buy=a.buy_goods('p',good,2);sell=a.sell_goods('p',good,1)
        s=calculate(self.m.c,1)['p']
        self.assertEqual(s['trade_profit'],sell['total']-buy['total']//2)
        self.assertEqual(s['purchases'],buy['total']);self.assertEqual(s['exploration'],1)

    def test_policy_hash(self):
        p=policy();q=dict(reversed(list(p.items())))
        self.assertEqual(policy_hash(p),policy_hash(q));q['round_seconds']+=1
        self.assertNotEqual(policy_hash(p),policy_hash(q))

    def test_registration_fault(self):
        uid=self.m.stage(json.dumps(self.packages[0]).encode())
        self.m.failpoint=lambda name: (_ for _ in ()).throw(RuntimeError()) if name=='register' else None
        with self.assertRaises(RuntimeError):self.m.register(uid)
        self.assertEqual(self.m.item(uid)['state'],'VALIDATED')

    def test_finalize_faults(self):
        uid=self.active();self.app().create_player('p','P')
        for point in ('statistics','hall'):
            self.m.failpoint=lambda name: (_ for _ in ()).throw(RuntimeError()) if name==point else None
            with self.assertRaises(RuntimeError):self.m.finish(1,uid)
            self.assertEqual(self.m.item(uid)['state'],'ACTIVE')
            self.assertEqual(self.m.c.execute('SELECT count(*) FROM p4_hall').fetchone()[0],0)

    def test_activation_fault(self):
        old=self.active();a=self.app();a.create_player('p','P');uid=self.register(1);self.m.prepare(uid,2,100)
        self.m.failpoint=lambda name: (_ for _ in ()).throw(RuntimeError()) if name=='activate' else None
        with self.assertRaises(RuntimeError):self.m.activate(2,uid,1,old)
        self.assertEqual(a.get_player('p')['cash'],a.engine.catalog.data['starting']['cash'])
        self.assertEqual(self.m.repo._load().season_id,1);self.assertEqual(self.m.inspect()['foreign_keys'],[])

    def test_backups(self):
        self.active();files=list(Path(str(self.path)+'.backups').glob('*.sqlite3'));self.assertGreaterEqual(len(files),2)
        for f in files:
            c=sqlite3.connect(f)
            try:self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            finally:c.close()

    def test_recovery_copy_no_overwrite(self):
        from starroute.operations import restore_copy
        self.active();backup=self.m.backup('test');destination=Path(self.tmp.name)/'recovered.db'
        restore_copy(backup,destination)
        with self.assertRaises(FileExistsError):restore_copy(backup,self.path)
        r=Manager(destination,100)
        try:self.assertEqual(r.repo._load().season_id,1);self.assertEqual(r.inspect()['integrity'],['ok'])
        finally:r.close()

    def test_source_requires_signature(self):
        with self.assertRaises(ValueError):self.m.stage(json.dumps(self.packages[0]).encode(),{'source_type':'GitHub','verification':{'status':'unverified'}})

    def test_paths(self):
        for path in ('../x','/x','a/../x','a//b','-x','a\\x','a;sh'):
            with self.assertRaises(ValueError):safe_path(path)

    def test_pinned_commit_required(self):
        with self.assertRaises(ValueError):fetch('x','main','u.json',allowed_signers='x',identity='issuer')

    def test_fetch_failure_noninterference(self):
        self.active();a=self.app();a.create_player('p','P')
        with self.assertRaises(ValueError):fetch('https://invalid','0'*40,'u.json',allowed_signers='x',identity='issuer')
        self.assertEqual(a.get_player('p')['player_id'],'p')

    def test_player_records_languages_and_privacy(self):
        from starroute.adapters.cli import CLI
        uid=self.active();a=self.app();a.create_player('p','P');self.m.finish(1,uid)
        for lang in ('ja','en'):
            out=[];cli=CLI(a,'p',output=out.append,language=lang)
            for cmd in ('rankings 1 trade','score 1','hall','rounds','exploration 1'):cli.execute(cmd)
            text='\n'.join(out)
            for private in ('maximum_level','private_caps','reproduction','event_seed'):self.assertNotIn(private,text)
            self.assertIn('p',text)

    def test_pending_voyage_reset(self):
        old=self.active();a=self.app();a.create_player('p','P')
        route=next(r for r in a.get_routes('p') if r['is_open'])
        a.depart('p',route['destination_id'])
        uid=self.register(1);self.m.prepare(uid,2,100);self.m.activate(2,uid,1,old)
        self.assertIsNone(self.m.repo._load().players['p'].destination_id)
        archive=self.m.archive(1)
        self.assertIsNotNone(archive['tables']['player_state'][0]['destination_id'])
        self.assertEqual(self.m.c.execute('SELECT count(*) FROM p4_visits WHERE round_id=1').fetchone()[0],1)

    def test_crash_rollback_and_retry(self):
        old=self.active();self.app().create_player('p','P');uid=self.register(1);self.m.prepare(uid,2,100)
        script='''import os,sys
from starroute.operations import Manager
m=Manager(sys.argv[1],100,lambda name:os._exit(73) if name=='activate' else None)
m.activate(2,sys.argv[2],1,sys.argv[3])
'''
        r=subprocess.run([sys.executable,'-c',script,str(self.path),uid,old],capture_output=True)
        self.assertEqual(r.returncode,73,r.stderr)
        self.assertEqual(self.m.repo._load().season_id,1);self.assertEqual(self.m.inspect()['integrity'],['ok'])
        self.m.activate(2,uid,1,old);self.assertEqual(self.m.repo._load().season_id,2)
        self.assertEqual(self.m.c.execute('SELECT count(*) FROM p4_hall').fetchone()[0],4)

    def test_repeated_activation_preserves_new_transactions(self):
        uid=self.active();a=self.app();a.create_player('p','P')
        good=next(r['goods_id'] for r in a.get_market('p')['entries'] if r['stock'])
        a.buy_goods('p',good,1);before=a.get_player('p');self.m.activate(1,uid)
        self.assertEqual(a.get_player('p'),before)

    def test_schema10_additive_upgrade(self):
        self.m.c.execute("UPDATE metadata SET value='10' WHERE key='schema_version'")
        old=[tuple(r) for r in self.m.c.execute('SELECT * FROM markets')]
        r=SQLiteRepository(self.path)
        try:
            self.assertIsNotNone(r.backup_path)
            self.assertEqual(old,[tuple(r) for r in r.connection.execute('SELECT * FROM markets')])
            self.assertEqual(r.connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0],'11')
        finally:r.close()

    def test_arrival_exploration_persists(self):
        self.active();a=self.app();a.create_player('p','P')
        route=next(r for r in a.get_routes('p') if r['is_open']);receipt=a.depart('p',route['destination_id'])
        a.clock.value=receipt['arrival_at'];a.get_player('p')
        visits=a.records('exploration','p',1)
        self.assertEqual(len(visits),2);self.assertEqual(len(self.app().records('exploration','p',1)),2)

    def test_contribution_components(self):
        self.active();a=self.app();a.create_player('p','P');c=a.engine.catalog
        planet=next(p for p,d in c.development_planets.items() if d['private_caps']['primary']>=3)
        with a.repository.transaction() as w:
            w.players['p'].ship_id='engineering_1';w.players['p'].planet_id=planet;w.developments[planet,'primary']=0
        receipt=a.invest('p','primary',2*c.development['credits_per_unit']['primary'])
        with a.repository.transaction() as w:
            rid,r=next((rid,r) for rid,r in w.routes.items() if not r['is_open']);w.players['p'].planet_id=r['from']
        donation=a._call('donate','p',rid,10)
        s=calculate(self.m.c,1)['p']
        self.assertEqual(s['planet_paid'],receipt['paid_credits']);self.assertEqual(s['planet_effect'],receipt['effect_units'])
        self.assertEqual(s['planet_bonus'],receipt['effect_units']-2)
        self.assertEqual(s['route_paid'],10);self.assertEqual(s['route_bonus'],donation['effect_units']-10)
        self.assertEqual(s['trade_profit'],0)

    def test_insurance_claim_separate(self):
        from starroute.mechanics import apply_event
        self.active();a=self.app();a.create_player('p','P');premium=a._call('insure','p')['paid_credits']
        route=next(r for r in a.get_routes('p') if r['is_open']);a.depart('p',route['destination_id'])
        with a.repository.transaction() as w:apply_event(a.engine,w,'insured-wreck','wreck','p')
        s=calculate(self.m.c,1)['p']
        self.assertEqual(s['insurance_premium'],premium);self.assertGreater(s['insurance_claim'],0);self.assertEqual(s['trade_profit'],0)

    def test_concurrent_close(self):
        import concurrent.futures
        uid=self.active();self.app().create_player('p','P')
        def close_round():
            m=Manager(self.path,100)
            try:m.finish(1,uid)
            finally:m.close()
        with concurrent.futures.ThreadPoolExecutor(2) as pool:list(pool.map(lambda _:close_round(),range(2)))
        self.assertEqual(self.m.c.execute('SELECT count(*) FROM p4_hall').fetchone()[0],4)
