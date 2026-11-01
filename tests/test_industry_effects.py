import copy
from contextlib import closing
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
from starroute.rules import fingerprint
from starroute.industry_effects import values
from starroute.adapters.cli import CLI

ROOT=Path(__file__).resolve().parents[1]

def trial():
    return json.loads((ROOT/'examples/industry-effects-trial.json').read_text(encoding='utf-8'))

class IndustryEffectsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'world.db';self.clock=ManualClock(100)

    def open(self,data=None):
        r=SQLiteRepository(self.path,Catalog(data) if data else None,now=100)
        self.addCleanup(r.close)
        return r,Application(r,self.clock)

    def ready(self,data=None):
        r,a=self.open(data or trial());a.create_player('p','P');return r,a

    def row(self,a,good='grain'):
        return next(x for x in a.get_production('p')['entries'] if x['goods_id']==good)

    def state(self,r):
        return {t:[tuple(x) for x in r.connection.execute('SELECT * FROM '+t)] for t in
                ('markets','industry_periods','economy_clock','planet_development','investment_records','player_state')}

    def test_no_retroactive_output_and_partial_period_restart(self):
        r,a=self.ready();before=self.row(a)['available'];self.clock.advance(59)
        a.invest('p','primary',1000);a.invest('p','tertiary',500)
        self.assertEqual(self.row(a)['production_per_tick'],6)
        self.assertEqual(self.row(a)['market_capacity'],10000)
        r.close();r,a=self.open();self.clock.advance(1)
        row=self.row(a);self.assertEqual(row['available'],before+5)
        self.assertEqual((row['production_per_tick'],row['market_capacity']),(12,11000))
        self.clock.advance(60);self.assertEqual(self.row(a)['available'],before+16)

    def test_investment_at_boundary_uses_next_period(self):
        r,a=self.ready();self.clock.advance(60);a.invest('p','primary',1000)
        before=self.row(a)['available'];self.assertEqual(self.row(a)['production_per_tick'],6)
        self.clock.advance(60);self.assertEqual(self.row(a)['available'],before+5)
        self.clock.advance(60);self.assertEqual(self.row(a)['available'],before+16)

    def test_bulk_matches_periodic_including_saturation(self):
        snapshots=[]
        for name,steps in [('bulk',[60000]),('periodic',[60]*1000)]:
            self.path=Path(self.tmp.name)/(name+'.db');self.clock=ManualClock(100)
            r,a=self.ready();self.clock.advance(17);a.invest('p','primary',1000);a.invest('p','tertiary',500)
            for step in steps:self.clock.advance(step);a.get_production('p')
            snapshots.append(self.state(r));r.close()
        # Request identifiers are random, so compare the economic state only.
        for table in ('markets','industry_periods','economy_clock','planet_development','player_state'):
            self.assertEqual(snapshots[0][table],snapshots[1][table],table)

    def test_four_industries_and_planet_identity(self):
        c=Catalog(trial());progress={(p,i):100 for p in c.planets for i in ('primary','secondary','tertiary','quaternary')}
        self.assertEqual(values(c,progress,('aurora','grain')),(12,15000))
        self.assertEqual(values(c,progress,('forge','grain')),(3,15000))
        self.assertEqual(values(c,progress,('forge','alloy'))[0],8)
        self.assertEqual(values(c,progress,('haven','medicine'))[0],6)
        self.assertEqual(values(c,progress,('aurora','alloy'))[0],0)

    def test_imports_unchanged_nonproducer_remains_nonproducer(self):
        d=trial();d['starting']['planet_id']='haven';r,a=self.ready(d)
        before=self.row(a);a.invest('p','primary',1000);self.clock.advance(120)
        after=self.row(a);self.assertFalse(after['produces']);self.assertEqual(after['production_per_tick'],0)
        self.assertEqual(after['imports_per_tick'],before['imports_per_tick'])
        self.assertEqual(after['available']-before['available'],2)

    def test_initial_progress_applies_to_first_period(self):
        d=trial();row=next(p for p in d['development']['planets'] if p['planet_id']=='aurora')
        row['initial_progress']['primary']=100
        r,a=self.ready(d);before=self.row(a);self.assertEqual(before['production_per_tick'],12)
        self.clock.advance(60);self.assertEqual(self.row(a)['available']-before['available'],11)

    def test_expanded_capacity_used_for_sales_and_supply(self):
        d=trial()
        for row in d['economy']['markets']:row['stock_limit']=row['target_stock']
        r,a=self.ready(d);a.buy_goods('p','grain',1)
        self.clock.advance(60);self.assertEqual(self.row(a)['available'],200)
        with self.assertRaises(GameError) as e:a.sell_goods('p','grain',1)
        self.assertEqual(e.exception.code,'MARKET_FULL')
        a.invest('p','tertiary',500)
        with self.assertRaises(GameError):a.sell_goods('p','grain',1)
        self.clock.advance(60);self.assertEqual(self.row(a)['market_capacity'],220)
        a.sell_goods('p','grain',1);self.assertEqual(self.row(a)['available'],201)
        self.clock.advance(6000);self.assertEqual(self.row(a)['available'],220)

    def test_hidden_caps_remain_enforced_and_absent_from_dto(self):
        d=trial();d['starting']['cash']=20000;r,a=self.ready(d);before=self.state(r)
        with self.assertRaises(GameError) as e:a.invest('p','primary',10010)
        self.assertEqual(e.exception.code,'INVESTMENT_UNAVAILABLE');self.assertEqual(before,self.state(r))
        text=json.dumps([a.get_production('p'),a.get_development('p'),a.get_market('p'),a.investment_ledger('p')])
        for forbidden in ('private_caps','remaining_capacity','abundance','production_bps_per_unit'):
            self.assertNotIn(forbidden,text)

    def test_failed_investment_rolls_back_period_and_cash(self):
        r,a=self.ready();a.invest('p','primary',1000);before=self.state(r);self.clock.advance(120)
        with patch.object(r,'record_investment',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):a.invest('p','tertiary',500)
        self.assertEqual(before,self.state(r));self.row(a)
        self.assertEqual(self.row(a)['production_per_tick'],12)

    def test_retry_does_not_apply_investment_twice(self):
        r,a=self.ready();receipt=a.invest('p','primary',1000,request_id='one');self.clock.advance(120)
        self.assertEqual(receipt,a.invest('p','primary',1000,request_id='one'))
        self.assertEqual(len(a.investment_ledger('p')),1);self.assertEqual(a.get_player('p')['cash'],4000)
        self.assertEqual(self.row(a)['production_per_tick'],12)

    def test_hash_covers_parameters_not_runtime_progress(self):
        d=trial();base=fingerprint(Catalog(d));r,a=self.ready(d);a.invest('p','primary',1000);self.clock.advance(120);self.row(a)
        self.assertEqual(fingerprint(r.catalog),base)
        changed=copy.deepcopy(d);changed['industry_effects']['planets'][0]['market_bps_per_unit']+=1
        self.assertNotEqual(fingerprint(Catalog(changed)),base)
        changed=copy.deepcopy(d);changed['industry_effects']['planets'][0]['production_bps_per_unit']['primary']+=1
        self.assertNotEqual(fingerprint(Catalog(changed)),base)
        d['industry_effects']['planets'].reverse();self.assertEqual(fingerprint(Catalog(d)),base)

    def test_rejects_incomplete_unknown_fractional_and_overflow_rules(self):
        mutations=[lambda d:d['industry_effects']['planets'].pop(),
                   lambda d:d['industry_effects'].update(extra=1),
                   lambda d:d['industry_effects']['planets'][0].update(market_bps_per_unit=0.5),
                   lambda d:d['industry_effects']['planets'][0].update(market_bps_per_unit=True),
                   lambda d:d['industry_effects']['planets'][0].update(market_bps_per_unit=-1),
                   lambda d:d['economy']['markets'][0].update(stock_limit=MAX_VALUE),
                   lambda d:d.update(development={'mode':'disabled'})]
        for mutate in mutations:
            d=trial();mutate(d)
            with self.subTest(mutate=mutate),self.assertRaises((GameError,ValueError)):Catalog(d)

    def test_zero_coefficients_preserve_base(self):
        d=trial()
        for row in d['industry_effects']['planets']:
            row['market_bps_per_unit']=0;row['production_bps_per_unit']={k:0 for k in row['production_bps_per_unit']}
        r,a=self.ready(d);a.invest('p','primary',1000);a.invest('p','tertiary',500);self.clock.advance(120)
        self.assertEqual((self.row(a)['production_per_tick'],self.row(a)['market_capacity']),(6,10000))

    def test_concurrent_readers_cannot_duplicate_supply(self):
        r,a=self.ready();before=self.row(a)['available'];a.invest('p','primary',1000);r.close();errors=[]
        def access():
            try:
                repo=SQLiteRepository(self.path)
                try:Application(repo,ManualClock(220)).get_production('p')
                finally:repo.close()
            except Exception as e:errors.append(repr(e))
        threads=[threading.Thread(target=access) for _ in range(3)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(errors,[]);self.clock.value=220;r,a=self.open();self.assertEqual(self.row(a)['available'],before+16)

    def test_v8_backup_and_rows_preserved(self):
        d=trial();d.pop('industry_effects');r,a=self.ready(d);a.invest('p','primary',1000)
        before=self.state(r);world=r.world_id;r.connection.execute('DROP TABLE industry_periods')
        r.connection.execute("UPDATE metadata SET value='8' WHERE key='schema_version'");r.close()
        r,a=self.open();self.assertTrue(Path(r.backup_path).exists());self.assertEqual(world,r.world_id)
        self.assertEqual(before,self.state(r));self.assertNotIn('market_capacity',self.row(a))
        with closing(sqlite3.connect(r.backup_path)) as backup:self.assertEqual(backup.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0],'8')

    def test_migration_failure_rolls_back(self):
        d=trial();d.pop('industry_effects');r,a=self.ready(d);r.connection.execute('DROP TABLE industry_periods')
        r.connection.execute("UPDATE metadata SET value='8' WHERE key='schema_version'");r.close()
        original=SQLiteRepository._industry_tables
        def fail(repo):original(repo);raise RuntimeError('injected')
        with patch.object(SQLiteRepository,'_industry_tables',fail),self.assertRaises(RuntimeError):SQLiteRepository(self.path)
        with closing(sqlite3.connect(self.path)) as c:
            self.assertEqual(c.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0],'8')
            self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='industry_periods'").fetchone())

    def test_missing_snapshot_fails_closed(self):
        r,a=self.ready();r.connection.execute('DELETE FROM industry_periods')
        with self.assertRaises(GameError) as e:self.row(a)
        self.assertEqual(e.exception.code,'CONFIG_VERIFICATION_FAILED')

    def test_corrupt_period_values_are_rejected(self):
        r,a=self.ready();r.connection.execute('UPDATE industry_periods SET production_rate=999999')
        with self.assertRaises(GameError) as e:self.row(a)
        self.assertEqual(e.exception.code,'CONFIG_VERIFICATION_FAILED')

    def test_events_and_regional_prices_remain_active(self):
        d=trial();events=json.loads((ROOT/'examples/events-trial.json').read_text(encoding='utf-8'))['market_events']
        events['targets']=[dict(planet_id='aurora',goods_id='grain',surge_bps=10000,crash_bps=0,surge_credits=200,crash_credits=150)]
        d['market_events']=events;r,a=self.ready(d);a.invest('p','primary',1000);self.clock.advance(120)
        self.assertEqual(self.row(a)['production_per_tick'],12);self.assertEqual(len(a.get_events('p')),1)
        surge=a.quote_trade('p','grain',1,'buy')['total'];self.clock.advance(30)
        self.assertEqual(surge-a.quote_trade('p','grain',1,'buy')['total'],200)
        self.assertTrue(a.get_region('p')['enabled'])

    def test_ja_en_cli_reports_actual_period_values(self):
        r,a=self.ready();a.invest('p','primary',1000);self.clock.advance(60)
        for lang in ('ja','en'):
            output=[];cli=CLI(a,'p',language=lang,output=output.append)
            self.assertEqual(cli.safe_execute('production'),(True,0))
            self.assertIn('10,000','\n'.join(output));self.assertNotIn('private_caps','\n'.join(output))

if __name__=='__main__':unittest.main()
