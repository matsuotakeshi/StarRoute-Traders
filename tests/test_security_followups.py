import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from starroute.exploration import archived_arrivals, index_archive_arrivals
from starroute.model import GameError
from starroute.network import Gateway
from starroute_bbs.client import Client, ClientError, cache_projection, save
from starroute_bbs.node import operator_lock
from starroute_bbs.terminal import Terminal


class SecurityFollowupTests(unittest.TestCase):
    def test_pending_journal_lock_preserves_existing_record(self):
        with tempfile.TemporaryDirectory() as temp:
            door = Client.__new__(Client)
            door.pending = Path(temp)/'pending.json'
            save(door.pending, {'request_id': 'first-request'})
            with operator_lock(door.pending):
                for invoke in (lambda: door.call('buy'), door.resolve, door.retry_pending):
                    with self.assertRaisesRegex(ClientError, 'OPERATION_UNCERTAIN'):
                        invoke()
            self.assertEqual(json.loads(door.pending.read_text())['request_id'], 'first-request')

    def test_offline_map_discards_discoverer_only_projection(self):
        visible = {'planet_id':'001','name':'Open','coordinates':{'x':1,'y':1}}
        private = {'planet_id':'hidden-001','name':'Private','coordinates':{'x':8,'y':8}}
        online = {'definition':{'projection_version':1,'universe_id':'world','round_id':1,
                  'planets':[visible,private],'routes':[]},'public_definition_hash':'personal'}
        offline = cache_projection('map',online)
        self.assertEqual(offline['definition']['planets'], [visible])
        self.assertNotIn('public_definition_hash',offline)
        self.assertEqual(online['definition']['planets'],[visible,private])
        self.assertIsNone(cache_projection('market', {'planet_id':'hidden-001','entries':[]}))

    def test_unauthenticated_request_skips_repository_initialization(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'master.db'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE p5_sites(credential_hash TEXT, state TEXT)')
            db.close()
            with patch('starroute.network.SQLiteRepository') as repository:
                with self.assertRaises(GameError) as denied:
                    Gateway(path,b'test').dispatch('connect','unknown',{})
                self.assertEqual(denied.exception.code,'AUTH_FAILED')
                repository.assert_not_called()

    def test_index_preserves_public_history_with_bounded_page(self):
        from starroute.repository import SQLiteRepository
        repo = SQLiteRepository(':memory:')
        self.addCleanup(repo.close)
        db = repo.connection
        for n in range(1,3):
            rows=[dict(player_id='p',display_name='Pilot',at=1,name=None,rank=rank,
                       round_id=n,universe_id='world',private='ignored') for rank in range(1,61)]
            index_archive_arrivals(db,n,{'phase3_state':[{'state_json':json.dumps({'exploration':{'arrivals':rows}})}]})
        first=archived_arrivals(repo)
        second=archived_arrivals(repo,(first[-1]['round_id'],first[-1]['rank']))
        self.assertEqual((len(first),len(second)),(100,20))
        self.assertNotIn('private',first[0])

    def test_terminal_startup_size_uses_live_bounds(self):
        terminal=Terminal(None,columns='invalid',rows='99')
        self.assertEqual((terminal.columns,terminal.rows),(80,24))
        terminal=Terminal(None,columns='9999',rows='1')
        self.assertEqual((terminal.columns,terminal.rows),(240,12))
        with patch('starroute_bbs.terminal.os.get_terminal_size',side_effect=OSError):
            terminal.resize(SimpleNamespace(fileno=lambda:0))
        self.assertEqual((terminal.columns,terminal.rows),(240,12))
