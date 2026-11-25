import copy
import itertools
import json
import statistics
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from srt_universe_generator.levels import generate
from starroute.application import Application
from starroute.catalog import Catalog
from starroute.clock import ManualClock
from starroute.generation_contract import separation, void_columns
from starroute.master import public_definition, Visibility, WorldTarget
from starroute.model import GameError
from starroute.operations import initialize, Manager
from starroute.repository import SQLiteRepository
from starroute.universe import seal_manifest
from starroute.universe_package import export_package, to_catalog
from tests.test_connected_universe import reachable


def example(name):
    path = Path(__file__).resolve().parents[1] / 'examples' / (name + '.json')
    return json.loads(path.read_text(encoding='utf8'))


def points(data):
    return {r['planet_id']: (r['x'], r['y']) for r in data['universe']['coordinates']}


def nearest_mean(coords):
    return statistics.mean(min(separation(a, b) for b in coords if a != b) for a in coords)


class ClusteredUniverseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = example('release-world')
        cls.levels = example('industry-levels-trial')
        cls.policy = example('clustered-universe-trial')
        cls.seed = 'cluster-comparison-0'
        cls.data = generate(cls.template, cls.policy, cls.levels, cls.seed)

    def test_spatial_and_hidden_invariants_across_seeds(self):
        for index in range(4):
            with self.subTest(seed=index):
                data = self.data if index == 0 else generate(
                    self.template, self.policy, self.levels, f'cluster-comparison-{index}')
                coords = points(data)
                self.assertEqual(len(set(coords.values())), 48)
                self.assertTrue(all(x not in void_columns(self.policy) for x, _ in coords.values()))
                self.assertTrue(all(separation(a, b) >= 4 for a, b in itertools.combinations(coords.values(), 2)))
                self.assertTrue(all(10 <= sum(left <= x < left + 60 for x, _ in coords.values()) <= 18
                                    for left in range(0, 240, 60)))
                self.assertEqual(len(reachable(data)), 48)
                self.assertEqual(sum(r['is_open'] for r in data['routes']), 47)
                private = data['universe']['private_world']
                point = (private['position']['x'], private['position']['y'])
                self.assertGreaterEqual(min(separation(point, p) for p in coords.values()), 10)
                self.assertLessEqual(separation(point, coords[private['reference_planet_id']]), 40)

    def test_same_seed_reproduces_clustered_definition_and_is_denser_than_uniform(self):
        again = generate(self.template, self.policy, self.levels, self.seed,
                         self.data['universe']['universe_id'])
        self.assertEqual(again, self.data)
        uniform = generate(self.template, example('connected-universe-trial'), self.levels, self.seed)
        self.assertLess(nearest_mean(list(points(self.data).values())), nearest_mean(list(points(uniform).values())))

    def test_large_comparison_round_trips(self):
        policy = example('clustered-universe-large-comparison')
        data = generate(self.template, policy, self.levels, self.seed)
        self.assertEqual(to_catalog(export_package(data)).data, data)
        self.assertEqual(len(reachable(data)), 48)
        self.assertTrue(any(x >= 240 or y >= 120 for x, y in points(data).values()))

    def test_impossible_policy_exhausts_configured_attempts(self):
        policy = copy.deepcopy(self.policy)
        policy['distribution']['min_distance'] = 240
        policy['max_attempts'] = 2
        from srt_universe_generator.clustered import clustered_cells
        with patch('srt_universe_generator.clustered.clustered_cells', wraps=clustered_cells) as place:
            with self.assertRaisesRegex(ValueError, 'constraints unsatisfied'):
                generate(self.template, policy, self.levels, self.seed)
        self.assertEqual(place.call_count, 2)

    def test_catalog_rejects_resealed_layout_inside_void(self):
        data = copy.deepcopy(self.data)
        data['universe']['coordinates'][0]['x'] = 120
        seal_manifest(data)
        with self.assertRaises(GameError) as raised:
            Catalog(data)
        self.assertEqual(str(raised.exception.__cause__), 'planet in reserved void')

    def test_registered_world_keeps_private_data_and_donation_working(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'game.db'
            initialize(db, 100)
            manager = Manager(db, 100)
            try:
                uid = manager.stage(json.dumps(export_package(self.data)).encode())
                manager.register(uid)
                manager.prepare(uid, 1, 100)
                manager.activate(1, uid)
            finally:
                manager.close()
            repo = SQLiteRepository(db)
            try:
                catalog = repo.catalog
                route = next(route for route in catalog.data['routes'] if not route['is_open'])
                app = Application(repo, ManualClock(100))
                with patch('secrets.choice', return_value=route['from']):
                    app.create_player('pilot', 'Pilot')
                with repo.transaction() as world:
                    world.players['pilot'].cash = 100000000
                self.assertTrue(app._call('donate', 'pilot', route['id'], 1000000, request_id='open')['opened'])
                public = public_definition(catalog, WorldTarget(uid, 1),
                                           Visibility(frozenset(catalog.planets), frozenset(catalog.planets),
                                                      frozenset(r['id'] for r in catalog.data['routes'])))
                for field in ('hidden-001', 'private_world', 'reference_planet_id', '"seed"'):
                    self.assertNotIn(field, json.dumps(public))
            finally:
                repo.close()
