import copy,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from starroute.catalog import Catalog
from starroute.repository import SQLiteRepository
from starroute.engine import Engine
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.rules import fingerprint
from starroute.maintenance import backup,inspect,migrate_copy,advance

ROOT=Path(__file__).resolve().parents[1]

class TimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'game.db'
        self.data=json.loads((ROOT/'examples/long-duration-template.json').read_text(encoding='utf8'))
        self.data['phase3']['event_probabilities']={k:0 for k in self.data['phase3']['event_probabilities']}
    def repo(self,probability=100):
        self.data['phase3']['world_events']['probability_bps']=probability
        r=SQLiteRepository(self.path,Catalog(self.data),now=0);self.addCleanup(r.close);return r
    def test_miss_persisted_at_utc_boundary_and_restart(self):
        r=self.repo(0);advance(r,7199)
        self.assertFalse(r._load().phase3_state.get('world_checks'))
        advance(r,7200);r.close();r=SQLiteRepository(self.path);self.addCleanup(r.close)
        advance(r,21600);advance(r,21600)
        s=r._load().phase3_state
        self.assertEqual(len(s['world_checks']),3);self.assertFalse(s['events'])
        self.assertTrue(all(not c['occurred'] for c in s['world_checks'].values()))
    def test_one_global_disaster_per_slot_and_news_atomic(self):
        r=self.repo(10000);advance(r,21600);advance(r,21600)
        s=r._load().phase3_state
        events={k:v for k,v in s['events'].items() if k.startswith('world:')}
        self.assertEqual(len(events),3)
        self.assertTrue(all(k in s['news'] for k in events))
        self.assertEqual([x['scheduled_at'] for x in s['world_checks'].values()],[7200,14400,21600])
    def test_long_voyage_logout_restart_arrival(self):
        for plan in self.data['navigation']['plans']:
            plan['normal_seconds']*=10
            for option in plan['warp_options']:option['seconds']*=10
        r=self.repo(0);clock=ManualClock(0);a=Application(r,clock);a.create_player('p','Pilot')
        with r.transaction() as w:w.players['p'].ship_id='normal_2'
        q=a._call('quote_navigation','p','forge','normal',None)
        self.assertGreaterEqual(q['seconds'],7200)
        a._call('navigate','p','forge','normal',None)
        arrival=r._load().players['p'].arrival_at;r.close()
        r=SQLiteRepository(self.path);self.addCleanup(r.close);a=Application(r,clock)
        clock.value=arrival-1;a._call('get_player','p');self.assertEqual(r._load().players['p'].destination_id,'forge')
        clock.value=arrival;a._call('get_player','p');self.assertIsNone(r._load().players['p'].destination_id)
        self.assertEqual(r._load().players['p'].planet_id,'forge')
    def test_many_days_bounded_recovery_no_duplicate_slots(self):
        r=self.repo(0);advance(r,7*86400)
        s=r._load().phase3_state
        self.assertEqual(len(s['world_checks']),84)
        self.assertEqual(r._load().game_time,7*86400)
        advance(r,7*86400);self.assertEqual(len(r._load().phase3_state['world_checks']),84)
    def test_profile_generated_hours_and_hash(self):
        from srt_universe_generator.levels import generate
        params=json.loads((ROOT/'examples/phase3-generator.json').read_text())
        levels=json.loads((ROOT/'examples/industry-levels-trial.json').read_text())
        c=Catalog(generate(self.data,params,levels,'hours','00000000-0000-0000-0000-000000000020'))
        for (ship,route),p in c.navigation_plans.items():
            if c.ship_profiles[ship].ship_type=='normal':
                distance=next(r['distance'] for r in c.data['routes'] if r['id']==route)
                self.assertEqual(p['normal_seconds'],max(10,distance)*720)
        before=fingerprint(Catalog(self.data));self.data['phase3']['world_events']['probability_bps']+=1
        self.assertNotEqual(before['sha256'],fingerprint(Catalog(self.data))['sha256'])
    def test_production_market_period_not_world_event_interval(self):
        r=self.repo(0);before=r._load().economy_time;advance(r,3600)
        self.assertGreater(r._load().economy_time,before);self.assertFalse(r._load().phase3_state.get('world_checks'))
    def test_incremental_and_one_shot_replay_equal(self):
        r=self.repo(10000);advance(r,21600);expected=r._load().phase3_state
        other=Path(self.tmp.name)/'other.db';r2=SQLiteRepository(other,Catalog(self.data),now=0);self.addCleanup(r2.close)
        for t in (7100,7200,14000,14400,21000,21600):advance(r2,t)
        self.assertEqual(expected,r2._load().phase3_state)
    def test_rollback_of_event_and_news_on_save_failure(self):
        r=self.repo(10000)
        with patch.object(r,'_save',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):advance(r,7200)
        self.assertFalse(r._load().phase3_state.get('world_checks'));advance(r,7200)
        self.assertEqual(len(r._load().phase3_state['world_checks']),1)
    def test_invalid_event_policy_rejected(self):
        self.data['phase3']['world_events']['probability_bps']=10001
        with self.assertRaises(Exception):Catalog(self.data)
    def test_old_rules_have_identical_fingerprint(self):
        old=Catalog.load(ROOT/'examples/phase3-trial.json')
        self.assertEqual(fingerprint(old)['rules_version'],'phase3-complete-1')
        self.assertNotIn('world_events',old.phase3)
    def test_old_binary_rule_compatibility_guard(self):
        r=self.repo(0)
        with self.assertRaises(ValueError):inspect(self.path,11,['phase3-complete-1'])
        self.assertEqual(inspect(self.path,11,['world-time-1'])['rules_version'],'world-time-1')

class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.db=self.root/'game.db';r=SQLiteRepository(self.db);r.close()
    def test_backup_exclusive_and_integrity(self):
        dst=self.root/'backup.db';self.assertEqual(backup(self.db,dst)['schema'],11)
        with self.assertRaises(FileExistsError):backup(self.db,dst)
    def test_migration_copy_and_source_untouched(self):
        before=self.db.read_bytes();dst=self.root/'new.db'
        result=migrate_copy(self.db,dst,self.root/'backup.db')
        self.assertEqual(result['state'],'validated_copy');self.assertEqual(self.db.read_bytes(),before);self.assertEqual(inspect(dst)['schema'],11)
    def test_migration_failure_keeps_original_and_backup(self):
        before=self.db.read_bytes();dst=self.root/'new.db'
        def fail(step):raise RuntimeError(step)
        with self.assertRaises(RuntimeError):migrate_copy(self.db,dst,self.root/'backup.db',fail)
        self.assertFalse(dst.exists());self.assertEqual(self.db.read_bytes(),before)
        self.assertEqual(inspect(self.root/'backup.db')['integrity'],'ok')
        self.assertEqual(json.loads((self.root/'new.db.migration.json').read_text())['state'],'failed')
    def test_future_schema_refused_without_changes(self):
        c=sqlite3.connect(self.db);c.execute("UPDATE metadata SET value='99' WHERE key='schema_version'");c.commit();c.close()
        before=self.db.read_bytes()
        with self.assertRaises(ValueError):inspect(self.db)
        self.assertEqual(self.db.read_bytes(),before)
    def test_no_live_destination_overwrite(self):
        with self.assertRaises(FileExistsError):migrate_copy(self.db,self.db,self.root/'backup.db')

class DoorTimeTests(unittest.TestCase):
    def test_long_world_door_logout_and_new_gateway(self):
        import os
        from srt_universe_generator.levels import generate
        from starroute.universe_package import export_package
        from starroute.operations import initialize,Manager
        from starroute import network_security as sec
        from starroute.local_door import LocalDoor
        from starroute_bbs.client import save
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);db=root/'game.db';clock=ManualClock(100)
            template=json.loads((ROOT/'examples/long-duration-template.json').read_text(encoding='utf8'))
            template['phase3']['event_probabilities']={k:0 for k in template['phase3']['event_probabilities']}
            template['phase3']['world_events']['probability_bps']=0
            params=json.loads((ROOT/'examples/phase3-generator.json').read_text());params['initial_open_routes']=4
            data=generate(template,params,json.loads((ROOT/'examples/industry-levels-trial.json').read_text()),'long-door')
            initialize(db,100);m=Manager(db,100)
            uid=m.stage(json.dumps(export_package(data)).encode());m.register(uid);m.prepare(uid,1,100);m.activate(1,uid)
            key=os.urandom(32);(root/'key').write_bytes(key);sec.schema(m.c);sec.publish(m.repo,key)
            save(root/'profile',sec.provision(m.repo,key,'testbbs','Test BBS',100));m.close()
            config={'database':str(db),'reference_key':str(root/'key'),'profile':str(root/'profile')}
            door=LocalDoor(config,'1','Pilot',clock);door.connect();routes=door.call('routes');destination=next(r['destination_id'] for r in routes if r['is_open'])
            quote=door.call('quote_navigation',{'destination_id':destination,'mode':'normal','level':None})
            self.assertGreaterEqual(quote['seconds'],7200)
            door.call('navigate',{'destination_id':destination,'mode':'normal','level':None});door.logout()
            clock.value=100+quote['seconds']+7200
            second=LocalDoor(config,'1','Pilot',clock);second.connect();status=second.call('status')
            self.assertIsNone(status['destination_id']);self.assertEqual(status['planet_id'],destination);second.logout()
            r=SQLiteRepository(db)
            try:
                state=r._load().phase3_state;self.assertTrue(state['world_checks']);self.assertFalse(state['events'])
                self.assertEqual(r.connection.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            finally:r.close()

if __name__=='__main__':unittest.main()
