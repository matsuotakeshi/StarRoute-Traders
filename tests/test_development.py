import copy
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from starroute.catalog import Catalog
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.model import GameError
from starroute.rules import fingerprint, effective_rules
from starroute.development import INDUSTRIES
from starroute.adapters.cli import CLI

ROOT=Path(__file__).resolve().parents[1]
def trial():return json.loads((ROOT/'examples/phase3d-trial.json').read_text(encoding='utf-8'))

class DevelopmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'world.db';self.clock=ManualClock(100)

    def open(self,data=None):
        r=SQLiteRepository(self.path,Catalog(data) if data else None,now=100);self.addCleanup(r.close)
        return r,Application(r,self.clock)

    def ready(self,data=None):
        r,a=self.open(data or trial());a.create_player('p','P');return r,a

    def test_four_industries_and_separate_payments_effects(self):
        r,a=self.ready()
        for industry,effect in zip(INDUSTRIES,(10,5,4,2)):
            result=a.invest('p',industry,100)
            self.assertEqual((result['paid_credits'],result['effect_units'],result['progress']),(100,effect,effect))
        self.assertEqual(a.get_player('p')['cash'],4600)
        self.assertEqual(len(a.investment_ledger('p')),4)
        self.assertEqual([i['progress'] for i in a.get_development('p')['industries']],[10,5,4,2])

    def test_engineering_bonus_changes_effect_only(self):
        d=trial();d['starting']['ship_id']='engineering_2';r,a=self.ready(d)
        result=a.invest('p','primary',400)
        self.assertEqual((result['paid_credits'],result['effect_units']),(400,50))
        self.assertEqual(a.get_player('p')['cash'],4600)

    def test_engineering_rounding_explicit(self):
        d=trial();d['starting']['ship_id']='engineering_1';r,a=self.ready(d)
        self.assertEqual(a.invest('p','primary',100)['effect_units'],12)

    def test_cap_boundary_no_partial_charge(self):
        d=trial();d['development']['planets'][0]['private_caps']['primary']=10
        r,a=self.ready(d);a.invest('p','primary',100)
        before=a.get_player('p')['cash']
        with self.assertRaises(GameError) as cm:a.invest('p','primary',10)
        self.assertEqual(cm.exception.code,'INVESTMENT_UNAVAILABLE')
        self.assertEqual(before,a.get_player('p')['cash']);self.assertEqual(len(a.investment_ledger('p')),1)

    def test_excess_investment_wholly_rejected(self):
        d=trial();d['development']['planets'][0]['private_caps']['primary']=10
        r,a=self.ready(d)
        with self.assertRaises(GameError):a.invest('p','primary',110)
        self.assertEqual(a.get_player('p')['cash'],5000)
        self.assertEqual(a.get_development('p')['industries'][0]['progress'],0)
        self.assertEqual(a.investment_ledger('p'),[])

    def test_invalid_industry_amount_and_funds(self):
        r,a=self.ready()
        for industry,amount in [('fifth',100),('primary',0),('primary',True),('primary',11),('primary',6000)]:
            with self.assertRaises(GameError):a.invest('p',industry,amount)
        self.assertEqual(a.get_player('p')['cash'],5000);self.assertEqual(a.investment_ledger('p'),[])

    def test_in_transit_not_allowed(self):
        r,a=self.ready();a.depart('p','forge')
        with self.assertRaises(GameError):a.invest('p','primary',100)
        with self.assertRaises(GameError):a.get_development('p')
        self.assertEqual(a.investment_ledger('p'),[])

    def test_shared_bbs_progress_separate_assets(self):
        r,a=self.ready();pid=a.create_account('bbs_b','p','P')['player_id']
        a.invest('p','primary',100)
        self.assertEqual(a.get_development(pid)['industries'][0]['progress'],10)
        self.assertEqual(a.get_player(pid)['cash'],5000)
        self.assertEqual(a.investment_ledger(pid),[])

    def test_planet_progress_is_independent(self):
        r,a=self.ready();a.invest('p','primary',100);a.depart('p','forge');self.clock.advance(4)
        self.assertEqual(a.get_development('p')['industries'][0]['progress'],0)
        a.invest('p','secondary',100)
        self.assertEqual(a.get_development('p')['industries'][1]['progress'],5)

    def test_retry_persists_and_conflict(self):
        r,a=self.ready();receipt=a.invest('p','primary',100,request_id='invest1');r.close();r,a=self.open()
        self.assertEqual(receipt,a.invest('p','primary',100,request_id='invest1'))
        self.assertEqual(a.get_player('p')['cash'],4900);self.assertEqual(len(a.investment_ledger('p')),1)
        with self.assertRaises(GameError):a.invest('p','secondary',100,request_id='invest1')

    def test_ledger_failure_rolls_back_everything(self):
        r,a=self.ready();self.clock.advance(60)
        with patch.object(r,'record_investment',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):a.invest('p','primary',100,request_id='retry')
        self.assertEqual(r.connection.execute('SELECT updated_at FROM economy_clock').fetchone()[0],100)
        self.assertEqual(a.get_player('p')['cash'],5000)
        self.assertEqual(a.get_development('p')['industries'][0]['progress'],0)
        self.assertEqual(a.investment_ledger('p'),[])
        a.invest('p','primary',100,request_id='retry');self.assertEqual(len(a.investment_ledger('p')),1)

    def test_public_projection_and_errors_never_include_limits(self):
        d=trial()
        for p in d['development']['planets']:
            p['private_caps']=dict.fromkeys(INDUSTRIES,87654321)
            p['resources'][0]['abundance']=9876
        r,a=self.ready(d);a.invest('p','primary',100)
        payload=[a.get_development('p'),a.investment_ledger('p'),a.get_player('p'),a.get_market('p'),a.get_ship('p')]
        text=json.dumps(payload)
        for secret in ('private_caps','87654321','abundance','9876','remaining_capacity','saturated'):
            self.assertNotIn(secret,text)
        self.assertIn('87654321',json.dumps(effective_rules(r.catalog)))
        view=a.get_development('p');view['industries'][0]['progress']=99
        self.assertEqual(a.get_development('p')['industries'][0]['progress'],10)

    def test_cap_failure_cli_ja_en_no_limit_disclosure(self):
        d=trial();d['development']['planets'][0]['private_caps']['primary']=7
        r,a=self.ready(d)
        for lang in ('ja','en'):
            out=[];cli=CLI(a,'p',output=out.append,language=lang)
            self.assertEqual(cli.safe_execute('invest primary 100'),(True,1))
            self.assertNotIn('7',out[-1]);self.assertNotIn('cap',out[-1])

    def test_resources_preserved_at_zero_development(self):
        r,a=self.ready();view=a.get_development('p')
        self.assertTrue(all(x['progress']==0 for x in view['industries']))
        self.assertIn({'resource_id':'trace_minerals'},view['resources'])
        self.assertTrue(any(x['rare'] for x in r.catalog.development_planets['aurora']['resources']))

    def test_hash_includes_caps_rates_resources_but_not_progress(self):
        d=trial();before=fingerprint(Catalog(d))
        mutations=[lambda x:x['credits_per_unit'].update(primary=11),lambda x:x.update(engineering_bonus_bps=3000),
            lambda x:x['planets'][0]['private_caps'].update(primary=1001),lambda x:x['planets'][0]['initial_progress'].update(primary=1),
            lambda x:x['planets'][0]['resources'][0].update(abundance=7501),lambda x:x['planets'][0]['resources'][0].update(rare=True)]
        for mutate in mutations:
            changed=copy.deepcopy(d);mutate(changed['development']);self.assertNotEqual(before,fingerprint(Catalog(changed)))
        r,a=self.ready();info=a.configuration_info();a.invest('p','primary',100);self.assertEqual(info,a.configuration_info())

    def test_order_and_disabled_normalization(self):
        d=trial();before=fingerprint(Catalog(d));d['development']['planets'].reverse()
        for p in d['development']['planets']:p['resources'].reverse()
        self.assertEqual(before,fingerprint(Catalog(d)))
        d=Catalog.load().data;before=fingerprint(Catalog(d));d['development']={'mode':'disabled'}
        self.assertEqual(before,fingerprint(Catalog(d)))

    def test_invalid_policies(self):
        for mutate in (lambda d:d.update(status='confirmed'),lambda d:d['credits_per_unit'].update(primary=0),
                       lambda d:d['planets'].pop(),lambda d:d['planets'][0]['private_caps'].pop('primary'),
                       lambda d:d['planets'][0]['initial_progress'].update(primary=100000),
                       lambda d:d['planets'][0]['resources'][0].update(abundance=-1)):
            data=trial();mutate(data['development'])
            with self.assertRaises(GameError):Catalog(data)

    def test_legacy_disabled_and_no_catalog_overwrite(self):
        r,a=self.open();a.create_player('p','P');before=r.catalog.canonical()
        self.assertFalse(a.get_development('p')['enabled'])
        with self.assertRaises(GameError):a.invest('p','primary',100)
        with self.assertRaises(GameError):SQLiteRepository(self.path,Catalog(trial()))
        self.assertEqual(before,r.catalog.canonical());self.assertEqual(a.get_player('p')['cash'],5000)

    def old_v6(self):
        r,a=self.open();a.create_player('p','P');a.buy_goods('p','grain',1,request_id='trade')
        world=r.world_id;r.connection.execute('DROP TABLE industry_periods');r.connection.execute('DROP TABLE market_event_history');r.connection.execute('DROP TABLE event_clock');r.connection.execute('DROP TABLE investment_records');r.connection.execute('DROP TABLE planet_development')
        r.connection.execute("UPDATE metadata SET value='6' WHERE key='schema_version'")
        before={t:[tuple(row) for row in r.connection.execute('SELECT * FROM "'+t+'"')] for (t,) in r.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        r.close();return world,before

    def test_v6_migration_preserves_all_old_rows(self):
        world,before=self.old_v6();r,a=self.open();self.assertEqual(world,r.world_id)
        with closing(sqlite3.connect(r.backup_path)) as backup:
            for t,rows in before.items():self.assertEqual(rows,backup.execute('SELECT * FROM "'+t+'"').fetchall())
        for t,rows in before.items():
            if t!='metadata':self.assertEqual(rows,[tuple(x) for x in r.connection.execute('SELECT * FROM "'+t+'"')])
        a.buy_goods('p','grain',1,request_id='trade');self.assertEqual(len(a.trade_ledger('p')),1)
        self.assertEqual(a.investment_ledger('p'),[])

    def test_migration_failure_and_retry(self):
        self.old_v6();original=SQLiteRepository._development_tables
        def fail(r):original(r);raise RuntimeError('injected')
        with patch.object(SQLiteRepository,'_development_tables',fail):
            with self.assertRaises(RuntimeError):SQLiteRepository(self.path)
        with closing(sqlite3.connect(self.path)) as c:
            self.assertEqual(c.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0],'6')
            self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='planet_development'").fetchone())
        r,a=self.open();self.assertEqual(a.get_player('p')['cash'],4940)

    def test_concurrent_last_capacity_one_investment(self):
        d=trial();d['development']['planets'][0]['private_caps']['primary']=10
        r,a=self.ready(d);a.create_player('q','Q');r.close();results=[]
        def invest(pid):
            repo=SQLiteRepository(self.path)
            try:
                Application(repo,ManualClock(100)).invest(pid,'primary',100,request_id='last');results.append('ok')
            except GameError as e:results.append(e.code)
            finally:repo.close()
        threads=[threading.Thread(target=invest,args=(pid,)) for pid in ('p','q')]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(sorted(results),['INVESTMENT_UNAVAILABLE','ok'])
        r,a=self.open();self.assertEqual(sum(a.get_player(p)['cash'] for p in ('p','q')),9900)
        self.assertEqual(r.connection.execute('SELECT count(*) FROM investment_records').fetchone()[0],1)

    def test_cli_success_and_history_pagination(self):
        r,a=self.ready()
        for lang in ('ja','en'):
            out=[];cli=CLI(a,'p',output=out.append,language=lang)
            for command in ('development','invest primary 100','investments'):
                self.assertEqual(cli.safe_execute(command),(True,0))
            self.assertTrue(any('100' in x for x in out))
        first=a.investment_ledger('p',limit=1)
        self.assertEqual(len(a.investment_ledger('p',after=first[0]['sequence'])),1)
        self.assertEqual(a.investment_ledger('other'),[])

    def test_corrupt_saved_progress_rejected_without_repair(self):
        r,a=self.ready();r.connection.execute("UPDATE planet_development SET progress=999999 WHERE planet_id='aurora' AND industry='primary'");r.close()
        with self.assertRaises(GameError):SQLiteRepository(self.path)

    def test_investment_preserves_cargo_ship_and_trade_ledger(self):
        r,a=self.ready();a.buy_goods('p','grain',2);before=a.get_player('p');trades=a.trade_ledger('p')
        a.invest('p','primary',100);after=a.get_player('p')
        self.assertEqual(before['cargo'],after['cargo']);self.assertEqual(before['ship_id'],after['ship_id'])
        self.assertEqual(trades,a.trade_ledger('p'))

    def test_resource_translations_are_site_only(self):
        r,a=self.ready();before=a.configuration_info()
        ja=[];en=[]
        CLI(a,'p',output=ja.append,language='ja').execute('development')
        CLI(a,'p',output=en.append,language='en').execute('development')
        self.assertNotEqual(ja[-1],en[-1]);self.assertIn('Agricultural',en[-1])
        self.assertEqual(before,a.configuration_info())
