import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.model import GameError
from starroute.adapters.cli import CLI
from starroute.presentation import Presentation

class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name)/'world.db')
        self.clock = ManualClock(100)

    def open(self):
        r = SQLiteRepository(self.path,now=100)
        self.addCleanup(r.close)
        return r,Application(r,self.clock)

    def legacy(self):
        c=sqlite3.connect(self.path)
        c.executescript((Path(__file__).parent/'fixtures/v1.sql').read_text(encoding='utf-8'))
        c.close()

    def test_v1_migration_preserves_catalog_assets_deadline_and_backup(self):
        self.legacy()
        old=sqlite3.connect(self.path)
        tables=['metadata','players','player_state','cargo','markets','routes','seasons','ships','goods','planets']
        before={t:old.execute('SELECT * FROM '+t).fetchall() for t in tables};old.close()
        r,a=self.open()
        p=a.get_player('legacy')
        self.assertEqual((p['cash'],p['destination_id'],p['arrival_at']),(4400,'forge',102))
        self.assertEqual(p['cargo'][0]['quantity'],10)
        self.assertEqual(a.resolve_account('local','legacy'),'legacy')
        backup=sqlite3.connect(r.backup_path)
        for t in tables:self.assertEqual(before[t],backup.execute('SELECT * FROM '+t).fetchall())
        backup.close()
        for t in tables[1:]:self.assertEqual(before[t],[tuple(x) for x in r.connection.execute('SELECT * FROM '+t)])
        self.clock.advance(2)
        a.sell_goods('legacy','grain',10)
        self.assertEqual(a.get_player('legacy')['cash'],5600)

    def test_migration_failure_rolls_back_and_retains_backup(self):
        self.legacy()
        original=SQLiteRepository._foundation
        def fail(r):
            original(r)
            raise RuntimeError('injected migration failure')
        with patch.object(SQLiteRepository,'_foundation',fail):
            with self.assertRaises(RuntimeError):SQLiteRepository(self.path)
        c=sqlite3.connect(self.path)
        self.assertEqual(c.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0],'1')
        self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='bbs_accounts'").fetchone())
        self.assertEqual(c.execute('SELECT cash FROM player_state').fetchone()[0],4400);c.close()
        self.assertEqual(len(list(Path(self.tmp.name).glob('*.v1-backup-*.db'))),1)
        r,a=self.open();self.assertEqual(a.get_player('legacy')['cash'],4400)

    def test_same_external_id_and_name_are_independent_in_shared_market(self):
        r,a=self.open()
        x=a.create_account('bbs_a','42','Same')['player_id']
        y=a.create_account('bbs_b','42','Same')['player_id']
        self.assertNotEqual(x,y)
        self.assertEqual(a.resolve_account('bbs_a','42'),x)
        stock=a.get_market(y)['entries'][0]['stock']
        a.buy_goods(x,'grain',1)
        self.assertEqual(a.get_player(y)['cash'],5000)
        self.assertEqual(a.get_market(y)['entries'][0]['stock'],stock-1)
        self.assertEqual(r.connection.execute('SELECT count(*) FROM bbs_accounts').fetchone()[0],2)
        with self.assertRaises(GameError):a.create_account('bbs_a','42','Other')
        with self.assertRaises(GameError):a.create_account('local','42','Other')

    def test_external_account_registration_retry(self):
        r,a=self.open()
        first=a.create_account('bbs','42','Name',request_id='create')
        self.assertEqual(first,a.create_account('bbs','42','Name',request_id='create'))
        with self.assertRaises(GameError):a.create_account('bbs','42','Changed',request_id='create')
        self.assertEqual(r.connection.execute('SELECT count(*) FROM players').fetchone()[0],1)

    def test_legacy_new_local_registration_has_mapping(self):
        r,a=self.open();a.create_player('p','P')
        self.assertEqual(a.resolve_account('local','p'),'p')

    def test_retry_and_payload_conflict_and_restart(self):
        r,a=self.open();a.create_player('p','P')
        result=a.buy_goods('p','grain',2,request_id='buy1')
        r2=SQLiteRepository(self.path);self.addCleanup(r2.close)
        a2=Application(r2,self.clock)
        self.assertEqual(a2.buy_goods('p','grain',2,request_id='buy1'),result)
        with self.assertRaises(GameError) as cm:a2.buy_goods('p','grain',3,request_id='buy1')
        self.assertEqual(cm.exception.code,'REQUEST_CONFLICT')
        self.assertEqual(a2.get_player('p')['cash'],4880)
        self.assertEqual(r.connection.execute("SELECT count(*) FROM operation_history WHERE request_id='buy1'").fetchone()[0],1)

    def test_register_depart_sell_retry(self):
        r,a=self.open()
        x=a.create_player('p','P',request_id='reg')
        self.assertEqual(x,a.create_player('p','P',request_id='reg'))
        a.buy_goods('p','grain',10)
        x=a.depart('p','forge',request_id='go')
        self.clock.advance(2)
        self.assertEqual(x,a.depart('p','forge',request_id='go'))
        x=a.sell_goods('p','grain',10,request_id='sale')
        self.assertEqual(x,a.sell_goods('p','grain',10,request_id='sale'))
        self.assertEqual(a.get_player('p')['cash'],5600)

    def test_request_scope_is_actor_specific(self):
        r,a=self.open()
        for pid in ['p','q']:
            a.create_player(pid,pid)
            a.buy_goods(pid,'grain',1,request_id='same')
        self.assertEqual(r.connection.execute("SELECT count(*) FROM operation_history WHERE request_id='same'").fetchone()[0],2)

    def test_history_failure_rolls_back_game_changes(self):
        r,a=self.open();a.create_player('p','P')
        r.connection.execute("CREATE TRIGGER fail_history BEFORE INSERT ON operation_history BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):a.buy_goods('p','grain',2,request_id='x')
        self.assertEqual(a.get_player('p')['cash'],5000)
        self.assertEqual(a.get_player('p')['cargo'],[])
        r.connection.execute('DROP TRIGGER fail_history')
        a.buy_goods('p','grain',2,request_id='x')
        self.assertEqual(a.get_player('p')['cash'],4880)

    def test_failed_game_operation_does_not_consume_request(self):
        r,a=self.open();a.create_player('p','P')
        with self.assertRaises(GameError):a.buy_goods('p','grain',999,request_id='retry')
        self.assertIsNone(r.connection.execute("SELECT 1 FROM operation_history WHERE request_id='retry'").fetchone())
        a.buy_goods('p','grain',1,request_id='retry')

    def test_concurrent_retry_executes_once(self):
        r,a=self.open();a.create_player('p','P')
        barrier=threading.Barrier(2);results=[];errors=[]
        def worker():
            rr=None
            try:
                rr=SQLiteRepository(self.path);aa=Application(rr,ManualClock(100))
                barrier.wait(timeout=5)
                results.append(aa.buy_goods('p','grain',10,request_id='race'))
            except BaseException as e:errors.append(e)
            finally:
                if rr:rr.close()
        threads=[threading.Thread(target=worker) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join(15)
        self.assertFalse(any(t.is_alive() for t in threads));self.assertEqual(errors,[])
        self.assertEqual(len(results),2);self.assertEqual(results[0],results[1])
        self.assertEqual(a.get_player('p')['cash'],4400)

    def test_language_only_changes_preference_and_persists(self):
        r,a=self.open();a.create_player('p','P');a.buy_goods('p','grain',1)
        before='\n'.join(r.connection.iterdump())
        lines=[];cli=CLI(a,'p',lines.append)
        cli.execute('language en');cli.execute('status');cli.execute('market')
        self.assertTrue(any('Star Grain' in line for line in lines))
        self.assertTrue(any('Cr' in line for line in lines))
        self.assertEqual(CLI(a,'p').view.language,'en')
        r.connection.execute('DELETE FROM preferences')
        self.assertEqual(before,'\n'.join(r.connection.iterdump()))
        with self.assertRaises(GameError):a.set_language('p','xx')

    def test_translation_keys_placeholders_and_no_rule_dependency(self):
        import string
        ja,en=Presentation('ja'),Presentation('en')
        self.assertEqual(set(ja.data['messages']),set(en.data['messages']))
        self.assertEqual(set(ja.data['errors']),set(en.data['errors']))
        def fields(s):return {f for _,f,_,_ in string.Formatter().parse(s) if f}
        for k,v in ja.data['messages'].items():self.assertEqual(fields(v),fields(en.data['messages'][k]))
        self.assertEqual(en.name('goods','custom','Custom name'),'Custom name')
        self.assertEqual(en.name('goods','grain','Custom grain'),'Custom grain')

    def test_cli_request_replay(self):
        r,a=self.open();lines=[];cli=CLI(a,'p',lines.append,language='en')
        self.assertEqual(cli.safe_execute('request reg register P')[1],0)
        self.assertEqual(cli.safe_execute('request buy1 buy grain 2')[1],0)
        self.assertEqual(cli.safe_execute('request buy1 buy grain 2')[1],0)
        self.assertEqual(cli.safe_execute('request buy1 buy grain 3')[1],1)
        self.assertEqual(a.get_player('p')['cash'],4880)

if __name__=='__main__':unittest.main()
