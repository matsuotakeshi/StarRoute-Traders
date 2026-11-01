"""Phase 3A tests. All grade IDs and numeric ship profiles below are fixtures only."""
import copy
import json
import sqlite3
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch
from starroute.application import Application
from starroute.catalog import Catalog
from starroute.clock import ManualClock
from starroute.model import GameError
from starroute.repository import SQLiteRepository, SCHEMA_VERSION
from starroute.adapters.cli import CLI


def test_catalog_data():
    d=copy.deepcopy(Catalog.load().data)
    d['format_version']=2
    d['ship_grades']=[{'id':'test_low','rank':1},{'id':'test_high','rank':2}]
    d['ships']=[]
    for tier in (1,2):
        grade='test_low' if tier==1 else 'test_high'
        for kind in ('normal','armed_cruiser','engineering'):
            d['ships'].append(dict(id=f'{kind}_{tier}',name=f'Test {kind} {tier}',capacity=20*tier,max_distance=10,speed=1,
                profile=dict(ship_type=kind,grade_id=grade,normal_speed=10 if kind!='engineering' else 5,
                    max_warp_speed=20*tier if kind!='engineering' else 10*tier,
                    purchase_price=1000*tier if kind=='normal' else 1500*tier,
                    insurance_premium=100*tier if kind!='armed_cruiser' else 50*tier,
                    specification_status='provisional')))
    d['starting']['ship_id']='normal_1'
    return d


class ShipModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/'world.db');self.clock=ManualClock(100)

    def open(self,catalog=None):
        r=SQLiteRepository(self.path,catalog,now=100);self.addCleanup(r.close)
        return r,Application(r,self.clock)

    def fixture(self,version=2):
        c=sqlite3.connect(self.path)
        c.executescript((Path(__file__).parent/f'fixtures/v{version}.sql').read_text(encoding='utf-8'));c.close()

    def assert_invalid(self,d):
        with self.assertRaises(GameError) as cm:Catalog(d)
        self.assertEqual(cm.exception.code,'INVALID_CONFIG')

    def test_legacy_profile_does_not_invent_decisions(self):
        c=Catalog.load();original=c.canonical()
        p=c.ship_profiles['sparrow']
        self.assertEqual(p.specification_status,'legacy')
        for k in ('ship_type','grade_id','normal_speed','max_warp_speed','purchase_price','insurance_premium'):
            self.assertIsNone(getattr(p,k))
        self.assertEqual(c.ship_grades,{})
        self.assertEqual(c.canonical(),original)

    def test_type_and_grade_are_independent_with_three_families(self):
        c=Catalog(test_catalog_data())
        self.assertEqual(len(c.ship_profiles),6)
        for kind in ('normal','armed_cruiser','engineering'):
            self.assertEqual([c.ship_profiles[f'{kind}_{tier}'].grade_id for tier in (1,2)],['test_low','test_high'])
        with self.assertRaises(FrozenInstanceError):c.ship_profiles['normal_1'].grade_id='changed'

    def test_unknown_type_unknown_grade_and_rank_validation(self):
        cases=[('ship_type','fighter'),('grade_id','missing')]
        for key,value in cases:
            with self.subTest(key=key):
                d=test_catalog_data();d['ships'][0]['profile'][key]=value;self.assert_invalid(d)
        for rank in (0,-1,True,1.5,'2'):
            with self.subTest(rank=rank):
                d=test_catalog_data();d['ship_grades'][0]['rank']=rank;self.assert_invalid(d)
        for key in ('id','rank'):
            d=test_catalog_data();d['ship_grades'][1][key]=d['ship_grades'][0][key];self.assert_invalid(d)

    def test_extension_requires_explicit_format_and_profile(self):
        d=test_catalog_data();d['format_version']=1;self.assert_invalid(d)
        d=test_catalog_data();del d['ships'][0]['profile'];self.assert_invalid(d)
        d=test_catalog_data();d['ships'][0]['profile']['extra_type']='fighter';self.assert_invalid(d)
        d=test_catalog_data();d['format_version']=True;self.assert_invalid(d)

    def test_provisional_unknown_values_and_confirmed_completeness(self):
        d=test_catalog_data()
        for ship in d['ships']:
            for key in ('grade_id','normal_speed','max_warp_speed','purchase_price','insurance_premium'):ship['profile'][key]=None
        c=Catalog(d);self.assertIsNone(c.ship_profiles['normal_1'].purchase_price)
        d['ships'][0]['profile']['specification_status']='confirmed';self.assert_invalid(d)
        d=test_catalog_data();d['ships'][0]['profile']['specification_status']='confirmed'
        self.assertEqual(Catalog(d).ship_profiles['normal_1'].specification_status,'confirmed')

    def test_profile_numeric_validation(self):
        for key in ('normal_speed','max_warp_speed','purchase_price','insurance_premium'):
            for value in (-1,True,1.5,10**16):
                with self.subTest(key=key,value=value):
                    d=test_catalog_data();d['ships'][0]['profile'][key]=value;self.assert_invalid(d)
        for key in ('normal_speed','max_warp_speed'):
            d=test_catalog_data();d['ships'][0]['profile'][key]=0;self.assert_invalid(d)

    def test_normal_grade_constraints(self):
        for key,value in [('normal_speed',11),('max_warp_speed',20),('purchase_price',1000),('insurance_premium',100)]:
            with self.subTest(key=key):
                d=test_catalog_data();d['ships'][3]['profile'][key]=value;self.assert_invalid(d)
        d=test_catalog_data();d['ships'][3]['capacity']=20;self.assert_invalid(d)

    def test_armed_same_grade_constraints(self):
        for key,value in [('normal_speed',11),('max_warp_speed',21),('purchase_price',1000),('insurance_premium',100)]:
            with self.subTest(key=key):
                d=test_catalog_data();d['ships'][1]['profile'][key]=value;self.assert_invalid(d)
        d=test_catalog_data();d['ships'][1]['capacity']=21;self.assert_invalid(d)

    def test_engineering_constraints_without_inventing_insurance_rule(self):
        for key,value in [('normal_speed',10),('max_warp_speed',20),('purchase_price',1000)]:
            with self.subTest(key=key):
                d=test_catalog_data();d['ships'][2]['profile'][key]=value;self.assert_invalid(d)
        for premium in (0,1,10000):
            d=test_catalog_data();d['ships'][2]['profile']['insurance_premium']=premium;Catalog(d)
        d=test_catalog_data();d['ships'][2]['capacity']=21;self.assert_invalid(d)

    def test_new_profile_persists_and_dto_is_detached(self):
        c=Catalog(test_catalog_data());r,a=self.open(c);a.create_player('p','P')
        p=a.get_ship('p');p['grade_id']='bad'
        self.assertEqual(a.get_ship('p')['grade_id'],'test_low')
        r2=SQLiteRepository(self.path);self.addCleanup(r2.close)
        self.assertEqual(r2.catalog.canonical(),c.canonical())
        self.assertEqual(r2.connection.execute('SELECT count(*) FROM ship_profiles').fetchone()[0],6)
        self.assertEqual(Application(r2,self.clock).get_ship('p'),a.get_ship('p'))

    def test_v2_migration_preserves_all_legacy_tables_and_retry_results(self):
        self.fixture();c=sqlite3.connect(self.path)
        tables=[x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        old={t:c.execute('SELECT * FROM '+t).fetchall() for t in tables};c.close()
        r,a=self.open()
        for t in tables:
            actual=[tuple(row) for row in r.connection.execute('SELECT * FROM '+t)]
            if t=='metadata':
                self.assertEqual(dict(actual)['catalog'],dict(old[t])['catalog'])
                self.assertEqual(dict(actual)['schema_version'],str(SCHEMA_VERSION))
            else:self.assertEqual(actual,old[t],t)
        backup=sqlite3.connect(r.backup_path)
        for t in tables:self.assertEqual(backup.execute('SELECT * FROM '+t).fetchall(),old[t])
        backup.close();self.assertIn('.v2-backup-',r.backup_path)
        p=a.get_player('legacy');self.assertEqual((p['cash'],p['arrival_at']),(4400,102))
        self.assertEqual(a.get_language('legacy'),'en')
        receipt=a.buy_goods('legacy','grain',10,request_id='buy')
        self.assertEqual(receipt['total'],600)
        self.assertEqual(a.get_player('legacy')['cash'],4400)
        self.assertIsNone(a.get_ship('legacy')['grade_id'])
        self.clock.advance(2);a.sell_goods('legacy','grain',10)
        self.assertEqual(a.get_player('legacy')['cash'],5600)

    def test_v2_migration_failure_rolls_back_ddl_and_keeps_backup(self):
        self.fixture();original=SQLiteRepository._ship_models
        def fail(r):
            original(r);raise RuntimeError('injected')
        with patch.object(SQLiteRepository,'_ship_models',fail):
            with self.assertRaises(RuntimeError):SQLiteRepository(self.path)
        c=sqlite3.connect(self.path)
        self.assertEqual(c.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0],'2')
        self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='ship_profiles'").fetchone())
        self.assertEqual(c.execute('SELECT count(*) FROM operation_history').fetchone()[0],4);c.close()
        self.assertEqual(len(list(Path(self.tmp.name).glob('*.v2-backup-*.db'))),1)
        r,a=self.open();self.assertEqual(a.get_player('legacy')['arrival_at'],102)

    def test_backup_failure_prevents_any_migration(self):
        self.fixture()
        with patch.object(SQLiteRepository,'_backup',side_effect=OSError('injected backup failure')):
            with self.assertRaises(OSError):SQLiteRepository(self.path)
        c=sqlite3.connect(self.path)
        self.assertEqual(c.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0],'2');c.close()

    def test_inconsistent_saved_profile_rejected(self):
        r,a=self.open();r.connection.execute("UPDATE ship_profiles SET purchase_price=1")
        with self.assertRaises(GameError) as cm:SQLiteRepository(self.path)
        self.assertEqual(cm.exception.code,'SHIP_MODEL_MISMATCH')

    def test_foreign_key_and_type_constraints(self):
        r,a=self.open()
        with self.assertRaises(sqlite3.IntegrityError):r.connection.execute("UPDATE ship_profiles SET ship_type='fighter'")
        with self.assertRaises(sqlite3.IntegrityError):r.connection.execute("UPDATE ship_profiles SET grade_id='missing'")

    def test_profile_inspection_does_not_change_navigation(self):
        r,a=self.open(Catalog(test_catalog_data()));a.create_player('p','P')
        before=a.get_routes('p');a.get_ship('p')
        self.assertEqual(before,a.get_routes('p'))
        a.depart('p','forge');self.assertEqual(a.get_player('p')['arrival_at'],102)
        self.assertEqual(a.get_ship('p')['normal_speed'],10) # metadata, not legacy multiplier

    def test_ship_cli_ja_en_and_unassigned_legacy(self):
        r,a=self.open();a.create_player('p','P');before=a.get_player('p')
        ja=[];en=[]
        self.assertEqual(CLI(a,'p',ja.append,language='ja').safe_execute('ship')[1],0)
        self.assertEqual(CLI(a,'p',en.append,language='en').safe_execute('ship')[1],0)
        self.assertIn('未確定',ja[0]);self.assertIn('unassigned',en[0])
        self.assertEqual(a.get_player('p'),before)

if __name__=='__main__':unittest.main()
