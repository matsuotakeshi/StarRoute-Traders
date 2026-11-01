import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from starroute.catalog import Catalog
from starroute.rules import fingerprint, canonical_bytes, effective_rules, master_candidate
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.model import GameError
from test_navigation import trial_data

class RulesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'world.db'

    def open(self):
        r=SQLiteRepository(self.path);self.addCleanup(r.close)
        return r,Application(r,ManualClock(100))

    def test_key_and_set_order_independent(self):
        d=trial_data();expected=fingerprint(Catalog(d))
        d=dict(reversed(list(d.items())))
        for key in ('ships','goods','planets','routes','markets','ship_grades'):d[key].reverse()
        d['navigation']['plans'].reverse()
        for plan in d['navigation']['plans']:plan['warp_options'].reverse()
        self.assertEqual(fingerprint(Catalog(d)),expected)

    def test_rule_changes_hash(self):
        d=Catalog.load().data;before=fingerprint(Catalog(d))
        for mutate in (lambda v:v['starting'].update(cash=123),lambda v:v['goods'][0].update(volume=2),lambda v:v['markets'][0].update(price=121)):
            new=copy.deepcopy(d);mutate(new);self.assertNotEqual(before,fingerprint(Catalog(new)))

    def test_names_and_site_settings_excluded(self):
        d=Catalog.load().data;before=fingerprint(Catalog(d))
        for group in ('ships','goods','planets'):
            for row in d[group]:row['name']='Custom display'
        self.assertEqual(before,fingerprint(Catalog(d)))
        r,a=self.open();a.create_player('p','P');before=a.configuration_info()
        a.set_language('p','en')
        self.assertEqual(before,Application(r,ManualClock(100),'en').configuration_info())

    def test_numeric_canonicalization_is_strict(self):
        self.assertEqual(canonical_bytes({'b':-0,'a':1000}),b'{"a":1000,"b":0}')
        for value in (1.0,float('nan'),float('inf'),{1:'bad'}):
            with self.assertRaises(GameError):canonical_bytes(value)
        d=Catalog.load().data;d['starting']['cash']=5000.0
        with self.assertRaises(GameError):Catalog(d)

    def test_unknown_fields_not_silently_certified(self):
        for path in ('root','starting','goods'):
            d=Catalog.load().data
            target=d if path=='root' else d['starting'] if path=='starting' else d['goods'][0]
            target['future_rule']=42
            c=Catalog(d)  # Preserve old permissive catalog loading.
            with self.assertRaises(GameError):fingerprint(c)

    def test_effective_defaults_and_ignored_legacy_fields(self):
        d=Catalog.load().data;before=fingerprint(Catalog(d))
        d['navigation']=None;d['routes'][0]['fee']=100
        self.assertEqual(before,fingerprint(Catalog(d)))
        d=trial_data();before=fingerprint(Catalog(d))
        d['ships'][0]['speed']=999;d['routes'][0]['seconds']=999
        self.assertEqual(before,fingerprint(Catalog(d)))

    def test_detached_projection(self):
        c=Catalog.load();before=fingerprint(c);rules=effective_rules(c)
        rules['starting']['cash']=1
        self.assertEqual(before,fingerprint(c))

    def test_world_persists_and_distinct_worlds_share_rules(self):
        r,a=self.open();first=a.configuration_info();r.close()
        r,a=self.open();self.assertEqual(first,a.configuration_info())
        other=SQLiteRepository(':memory:');self.addCleanup(other.close)
        info=Application(other,ManualClock(100)).configuration_info()
        self.assertNotEqual(first['world_id'],info['world_id']);self.assertEqual(first['sha256'],info['sha256'])
        self.assertEqual(info['config_schema_version'],10)
        self.assertEqual(info['rules_version'],'phase3-complete-1')

    def test_account_world_namespace_and_no_merging(self):
        r,a=self.open();x=a.create_account('bbs_a','42','Same');y=a.create_account('bbs_b','42','Same')
        ix=a.account_identity('bbs_a','42');iy=a.account_identity('bbs_b','42')
        self.assertEqual(ix['world_id'],r.world_id);self.assertNotEqual(ix['player_id'],iy['player_id'])
        a.create_player('old','Old');self.assertEqual(a.account_identity('local','old')['player_id'],'old')

    def test_candidate_never_asserts_trust(self):
        r,a=self.open();candidate=a.reference_candidate()
        self.assertEqual(candidate['world_id'],r.world_id)
        self.assertEqual(candidate['verification']['status'],'unverified')
        self.assertIsNone(candidate['verification']['signature'])
        self.assertNotIn('game_rules',candidate)

    def test_trading_does_not_change_configuration_hash(self):
        r,a=self.open();a.create_player('p','P');before=a.configuration_info()
        a.buy_goods('p','grain',1,request_id='buy');a.dock('p')
        self.assertEqual(before,a.configuration_info())

    def test_existing_db_ignores_changed_file(self):
        r,a=self.open();before=a.configuration_info();r.close()
        p=Path(self.tmp.name)/'changed.json';d=Catalog.load().data;d['starting']['cash']=123;p.write_text(json.dumps(d))
        r=SQLiteRepository(self.path,default_catalog_path=p);self.addCleanup(r.close)
        self.assertEqual(before,Application(r,ManualClock(100)).configuration_info())

    def legacy_v4(self):
        r,a=self.open();a.create_player('p','P');a.buy_goods('p','grain',1,request_id='keep')
        r.connection.execute('DROP TABLE industry_periods');r.connection.execute('DROP TABLE market_event_history');r.connection.execute('DROP TABLE event_clock');r.connection.execute('DROP TABLE investment_records');r.connection.execute('DROP TABLE planet_development');r.connection.execute('DROP TABLE trade_ledger')
        r.connection.execute('DROP TABLE economy_clock')
        r.connection.execute('DROP TABLE world_identity')
        r.connection.execute("UPDATE metadata SET value='4' WHERE key='schema_version'")
        before={t:r.connection.execute('SELECT * FROM "'+t+'"').fetchall() for (t,) in r.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        before={k:[tuple(row) for row in v] for k,v in before.items()};r.close();return before

    def test_v4_backup_preserves_rows_and_retry_results(self):
        before=self.legacy_v4();r,a=self.open()
        self.assertIsNotNone(r.backup_path)
        with closing(sqlite3.connect(r.backup_path)) as backup:
            for table,rows in before.items():self.assertEqual(rows,backup.execute('SELECT * FROM "'+table+'"').fetchall())
        for table,rows in before.items():
            if table!='metadata':self.assertEqual(rows,[tuple(row) for row in r.connection.execute('SELECT * FROM "'+table+'"')])
        self.assertEqual(dict(before['metadata'])['catalog'],r.catalog.canonical())
        cash=a.get_player('p')['cash'];a.buy_goods('p','grain',1,request_id='keep');self.assertEqual(cash,a.get_player('p')['cash'])

    def test_migration_failure_atomic_and_retry(self):
        self.legacy_v4();original=SQLiteRepository._world_identity
        def fail(r):original(r);raise RuntimeError('injected')
        with patch.object(SQLiteRepository,'_world_identity',fail):
            with self.assertRaises(RuntimeError):SQLiteRepository(self.path)
        with closing(sqlite3.connect(self.path)) as c:
            self.assertEqual(c.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0],'4')
            self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='world_identity'").fetchone())
        r,a=self.open();world=r.world_id;r.close();r,a=self.open();self.assertEqual(world,r.world_id)

    def test_backup_restore_keeps_world_id(self):
        r,a=self.open();world=r.world_id;copy_path=Path(self.tmp.name)/'restore.db'
        with closing(sqlite3.connect(copy_path)) as target:r.connection.backup(target)
        restored=SQLiteRepository(copy_path);self.addCleanup(restored.close);self.assertEqual(world,restored.world_id)

    def test_site_projection_is_separate_and_detached(self):
        from starroute.settings import Settings
        settings=Settings.load();site=settings.site_settings()
        self.assertNotIn('game_file',site)
        self.assertNotIn('default_language',effective_rules(Catalog.load()))
        site['inter_bbs']['bbs_id']='different'
        self.assertIsNone(settings.inter_bbs['bbs_id'])

    def test_duplicate_game_key_rejected(self):
        p=Path(self.tmp.name)/'duplicate.json'
        p.write_text('{"format_version":1,"format_version":2}')
        with self.assertRaises(GameError):Catalog.load(p)

    def test_cli_config_info_does_not_advance_game_time(self):
        from starroute.adapters.cli import CLI
        r,a=self.open();a.create_player('p','P')
        before=list(r.connection.execute('SELECT * FROM seasons'))
        lines=[];CLI(a,'p',output=lines.append).execute('config-info')
        self.assertEqual(json.loads(lines[0]),a.configuration_info())
        self.assertEqual(before,list(r.connection.execute('SELECT * FROM seasons')))

    def test_rules_version_changes_fingerprint(self):
        c=Catalog.load();before=fingerprint(c)
        with patch('starroute.rules.RULES_VERSION','future-test'):
            self.assertNotEqual(before['sha256'],fingerprint(c)['sha256'])
