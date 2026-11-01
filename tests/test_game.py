import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from starroute.application import Application
from starroute.catalog import Catalog
from starroute.clock import ManualClock
from starroute.engine import Engine
from starroute.model import GameError, Market, World, MAX_VALUE
from starroute.repository import SQLiteRepository
from starroute.adapters.cli import CLI


def fresh_world(catalog):
    return World(1, 100, {},
                 {(m['planet_id'], m['goods_id']): Market(m['price'], m['stock'])
                  for m in catalog.data['markets']},
                 {r['id']: copy.deepcopy(r) for r in catalog.data['routes']})


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog.load()
        self.engine = Engine(self.catalog)
        self.world = fresh_world(self.catalog)
        self.engine.create_player(self.world, 'alice', 'Alice')
        self.player = self.world.players['alice']

    def error(self, code, method, *args):
        before = copy.deepcopy(self.world)
        with self.assertRaises(GameError) as cm:
            getattr(self.engine, method)(self.world, *args)
        self.assertEqual(code, cm.exception.code)
        self.assertEqual(before, self.world, 'failure must not mutate domain state')

    def test_trade_and_profit_without_ui_or_database(self):
        self.engine.buy_goods(self.world, 'alice', 'grain', 10)
        self.assertEqual((4400, 190), (self.player.cash, self.world.markets['aurora','grain'].stock))
        self.engine.depart(self.world, 'alice', 'forge')
        self.engine.update(self.world, 102)
        self.engine.sell_goods(self.world, 'alice', 'grain', 10)
        self.assertEqual(5600, self.player.cash)
        self.assertEqual({}, self.player.cargo)
        self.assertEqual(80, self.world.markets['forge','grain'].stock)

    def test_insufficient_cash(self):
        self.player.cash = 59
        self.error('INSUFFICIENT_FUNDS', 'buy_goods', 'alice', 'grain', 1)

    def test_volume_not_just_item_count(self):
        self.engine.buy_goods(self.world, 'alice', 'alloy', 10)
        self.error('INSUFFICIENT_CAPACITY', 'buy_goods', 'alice', 'grain', 1)

    def test_insufficient_stock(self):
        self.world.markets['aurora','grain'].stock = 1
        self.error('INSUFFICIENT_STOCK', 'buy_goods', 'alice', 'grain', 2)

    def test_insufficient_cargo(self):
        self.error('INSUFFICIENT_CARGO', 'sell_goods', 'alice', 'grain', 1)

    def test_invalid_quantities(self):
        for value in [0, -1, True, 1.5, '2', None, MAX_VALUE + 1]:
            for operation in ['buy_goods', 'sell_goods']:
                with self.subTest(value=value, operation=operation):
                    self.error('INVALID_NUMBER', operation, 'alice', 'grain', value)

    def test_unknown_ids(self):
        self.error('PLAYER_NOT_FOUND', 'get_player', 'nobody')
        self.error('GOODS_NOT_FOUND', 'buy_goods', 'alice', 'unknown', 1)
        self.error('PLANET_NOT_FOUND', 'depart', 'alice', 'unknown')

    def test_unknown_player_cannot_trade(self):
        self.error('PLAYER_NOT_FOUND', 'buy_goods', 'nobody', 'grain', 1)

    def test_duplicate_registration(self):
        self.error('PLAYER_EXISTS', 'create_player', 'alice', 'Other')

    def test_control_characters_rejected(self):
        for name in ['\x1b[31mBad', 'A\nB', '', 'A\x7f']:
            self.error('INVALID_NAME', 'create_player', 'new', name)

    def test_unsafe_identifier_rejected(self):
        self.error('INVALID_ID', 'create_player', '../captain', 'Captain')

    def test_same_market_round_trip_has_no_profit(self):
        self.engine.buy_goods(self.world, 'alice', 'grain', 10)
        self.engine.sell_goods(self.world, 'alice', 'grain', 10)
        self.assertEqual(5000, self.player.cash)

    def test_partial_sale_keeps_remainder(self):
        self.engine.buy_goods(self.world, 'alice', 'grain', 10)
        self.engine.sell_goods(self.world, 'alice', 'grain', 3)
        self.assertEqual(7, self.player.cargo['grain'])

    def test_in_transit_restrictions_and_arrival_boundary(self):
        self.engine.depart(self.world, 'alice', 'forge')
        for op, args in [('buy_goods', ('grain', 1)), ('sell_goods', ('grain', 1)),
                         ('get_market', ()), ('depart', ('haven',))]:
            self.error('IN_TRANSIT', op, 'alice', *args)
        self.engine.update(self.world, 101)
        self.assertEqual('aurora', self.player.planet_id)
        self.engine.update(self.world, 102)
        self.assertEqual('forge', self.player.planet_id)
        self.assertIsNone(self.player.destination_id)
        self.engine.update(self.world, 1000)
        self.assertEqual('forge', self.player.planet_id)

    def test_clock_does_not_move_backwards(self):
        self.engine.update(self.world, 10)
        self.assertEqual(100, self.world.game_time)

    def test_closed_route(self):
        self.world.routes['aurora-forge']['is_open'] = False
        self.error('ROUTE_CLOSED', 'depart', 'alice', 'forge')

    def test_missing_route(self):
        del self.world.routes['aurora-forge']
        self.error('NO_ROUTE', 'depart', 'alice', 'forge')

    def test_out_of_range(self):
        self.world.routes['aurora-forge']['distance'] = 11
        self.error('OUT_OF_RANGE', 'depart', 'alice', 'forge')

    def test_normal_navigation_is_free_despite_legacy_route_fee(self):
        self.world.routes['aurora-forge']['fee'] = 6000
        result = self.engine.depart(self.world, 'alice', 'forge')
        self.assertEqual(result['fee'], 0)
        self.assertEqual(5000, self.player.cash)
        self.assertEqual(self.world.routes['aurora-forge']['fee'], 6000)

    def test_reverse_route(self):
        self.engine.depart(self.world, 'alice', 'forge')
        self.engine.update(self.world, 102)
        self.engine.depart(self.world, 'alice', 'aurora')
        self.engine.update(self.world, 104)
        self.assertEqual('aurora', self.player.planet_id)

    def test_remote_market_not_leaked(self):
        self.error('REMOTE_MARKET_UNAVAILABLE', 'get_market', 'alice', 'forge')

    def test_money_overflow_rejected_before_sale(self):
        self.player.cash = MAX_VALUE
        self.player.cargo['grain'] = 1
        self.error('INVALID_NUMBER', 'sell_goods', 'alice', 'grain', 1)

    def test_market_stock_overflow_rejected_before_sale(self):
        self.player.cargo['grain'] = 1
        self.world.markets['aurora','grain'].stock = MAX_VALUE
        self.error('INVALID_NUMBER', 'sell_goods', 'alice', 'grain', 1)

    def test_speed_rounding(self):
        data = copy.deepcopy(self.catalog.data)
        data['ships'][0]['speed'] = 2
        engine = Engine(Catalog(data))
        route = next(r for r in engine.get_routes(self.world, 'alice') if r['destination_id']=='forge')
        self.assertEqual(1, route['seconds'])

    def test_dtos_do_not_expose_mutable_domain_objects(self):
        self.engine.buy_goods(self.world, 'alice', 'grain', 1)
        result = self.engine.get_player(self.world, 'alice')
        result['cargo'][0]['quantity'] = 99
        self.assertEqual(1, self.player.cargo['grain'])
        json.dumps(result, ensure_ascii=False)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / 'world.db')
        self.clock = ManualClock(100)
        self.repository = SQLiteRepository(self.path, now=100)
        self.app = Application(self.repository, self.clock)
        self.app.create_player('alice', 'Alice')

    def tearDown(self):
        self.repository.close()
        self.directory.cleanup()

    def test_restart_with_cargo_and_pending_travel(self):
        self.app.buy_goods('alice', 'grain', 10)
        self.app.depart('alice', 'forge')
        self.repository.close()
        self.repository = SQLiteRepository(self.path)
        self.app = Application(self.repository, self.clock)
        self.assertEqual('forge', self.app.get_player('alice')['destination_id'])
        self.clock.advance(2)
        self.app.sell_goods('alice', 'grain', 10)
        self.assertEqual(5600, self.app.get_player('alice')['cash'])

    def test_shared_world_between_connections(self):
        other = SQLiteRepository(self.path)
        try:
            app2 = Application(other, self.clock)
            app2.create_player('bob', 'Bob')
            self.app.buy_goods('alice', 'grain', 10)
            row = app2.get_market('bob')['entries'][0]
            self.assertEqual(190, row['stock'])
            self.assertEqual(5000, app2.get_player('bob')['cash'])
        finally:
            other.close()

    def test_application_failure_rolls_back_all(self):
        before = self.app.get_player('alice')
        with self.assertRaises(GameError):
            self.app.buy_goods('alice', 'grain', 21)
        self.assertEqual(before, self.app.get_player('alice'))
        self.assertEqual(200, self.app.get_market('alice')['entries'][0]['stock'])

    def test_repository_exception_rolls_back_partial_work(self):
        with self.assertRaises(RuntimeError):
            with self.repository.transaction() as world:
                world.players['alice'].cash = 1
                raise RuntimeError('injected failure')
        self.assertEqual(5000, self.app.get_player('alice')['cash'])

    def test_database_failure_rolls_back_earlier_writes(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.repository.transaction() as world:
                world.players['alice'].cash = 42
                world.markets['aurora','grain'].stock = -1
        self.assertEqual(5000, self.app.get_player('alice')['cash'])

    def test_competing_buyers_cannot_double_spend_last_stock(self):
        self.app.create_player('bob', 'Bob')
        with self.repository.transaction() as world:
            world.markets['aurora','grain'].stock = 1
        def buy(player_id):
            repo = SQLiteRepository(self.path)
            try:
                try:
                    Application(repo, self.clock).buy_goods(player_id, 'grain', 1)
                    return 'ok'
                except GameError as exc:
                    return exc.code
            finally:
                repo.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(buy, ['alice', 'bob']))
        self.assertCountEqual(['ok', 'INSUFFICIENT_STOCK'], results)
        states = [self.app.get_player(p) for p in ['alice','bob']]
        self.assertEqual(9940, sum(p['cash'] for p in states))
        self.assertEqual(1, sum(item['quantity'] for p in states for item in p['cargo']))
        self.assertEqual(0, self.app.get_market('alice')['entries'][0]['stock'])

    def test_custom_catalog_is_persisted(self):
        data = copy.deepcopy(self.repository.catalog.data)
        data['starting']['cash'] = 1234
        path = str(Path(self.directory.name) / 'custom.db')
        custom = SQLiteRepository(path, Catalog(data))
        custom.close()
        custom = SQLiteRepository(path)
        try:
            app = Application(custom, self.clock)
            self.assertEqual(1234, app.create_player('new', 'New')['cash'])
        finally:
            custom.close()

    def test_changed_config_rejected(self):
        data = copy.deepcopy(self.repository.catalog.data)
        data['starting']['cash'] += 1
        with self.assertRaises(GameError) as cm:
            SQLiteRepository(self.path, Catalog(data))
        self.assertEqual('CONFIG_MISMATCH', cm.exception.code)
        self.assertEqual(5000, self.app.get_player('alice')['cash'])

    def test_unsupported_schema_rejected(self):
        self.repository.connection.execute("UPDATE metadata SET value='999' WHERE key='schema_version'")
        with self.assertRaises(GameError) as cm:
            SQLiteRepository(self.path)
        self.assertEqual('UNSUPPORTED_SCHEMA', cm.exception.code)

    def test_cli_adapter_calls_shared_application(self):
        out = []
        cli = CLI(self.app, 'alice', out.append)
        self.assertEqual((True, 0), cli.safe_execute('buy grain 10'))
        cli.execute('go forge')
        self.clock.advance(2)
        cli.execute('sell grain 10')
        cli.execute('status')
        self.assertTrue(any('5,600' in line for line in out))

    def test_invalid_cli_command_leaves_state_unchanged(self):
        out = []
        cli = CLI(self.app, 'alice', out.append)
        for line in ['buy grain no', 'buy grain', 'go "', 'sell grain -1']:
            self.assertEqual((True, 1), cli.safe_execute(line))
        self.assertEqual(5000, self.app.get_player('alice')['cash'])

    def test_cli_entrypoint_across_processes(self):
        def command(text):
            return subprocess.run([sys.executable, '-m', 'starroute', '--db', self.path,
                                   '--player', 'alice', '--command', text],
                                  capture_output=True, text=True, timeout=15)
        self.assertEqual(0, command('buy grain 10').returncode)
        self.assertEqual(0, command('go forge').returncode)
        # The CLI uses real time. Complete with a future test clock, without sleeping.
        self.clock.value = 10**12
        self.app.update()
        self.assertEqual(0, command('sell grain 10').returncode)
        result = command('status')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('5,600', result.stdout)
        self.assertEqual(1, command('buy grain -1').returncode)

    def test_sql_foreign_keys_are_enabled(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.connection.execute("INSERT INTO cargo VALUES (1,'ghost','grain',1)")


class CatalogTests(unittest.TestCase):
    def test_invalid_definition_variants(self):
        original = Catalog.load().data
        variants = []
        data = copy.deepcopy(original); data['markets'].pop(); variants.append(data)
        data = copy.deepcopy(original); data['goods'][0]['volume'] = 0; variants.append(data)
        data = copy.deepcopy(original); data['routes'][0]['to'] = 'missing'; variants.append(data)
        data = copy.deepcopy(original); data['goods'].append(data['goods'][0]); variants.append(data)
        data = copy.deepcopy(original); data['starting']['cash'] = -1; variants.append(data)
        for data in variants:
            with self.subTest(data=data):
                with self.assertRaises(GameError) as cm:
                    Catalog(data)
                self.assertEqual('INVALID_CONFIG', cm.exception.code)

    def test_catalog_owns_snapshot(self):
        source = Catalog.load().data
        catalog = Catalog(source)
        source['starting']['cash'] = 1
        self.assertEqual(5000, catalog.data['starting']['cash'])


if __name__ == '__main__':
    unittest.main()
