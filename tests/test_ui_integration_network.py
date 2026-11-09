import json,unittest
import tests.test_phase5 as phase5
from starroute_bbs.client import ClientError
class IntegratedNetworkTests(unittest.TestCase):
    setUp=phase5.Phase5Tests.setUp
    stop_server=phase5.Phase5Tests.stop_server
    client=phase5.Phase5Tests.client
    logged=phase5.Phase5Tests.logged
    good=phase5.Phase5Tests.good
    @classmethod
    def setUpClass(cls):
        phase5.Phase5Tests.setUpClass();cls.package=phase5.Phase5Tests.package;cls.cert=phase5.Phase5Tests.cert;cls.key=phase5.Phase5Tests.key
    @classmethod
    def tearDownClass(cls):phase5.Phase5Tests.tearDownClass()
    def test_history_is_owner_scoped_newest_and_cursor(self):
        a=self.logged();b=self.logged('bbs_b');g=self.good(a)
        a.call('buy',{'goods_id':g,'quantity':1},'buy');b.call('buy',{'goods_id':g,'quantity':1});a.call('sell',{'goods_id':g,'quantity':1})
        score=a.call('score');one=a.call('trade_history',{'before':None,'limit':1});two=a.call('trade_history',{'before':one['next_before'],'limit':1})
        self.assertEqual(one['entries'][0]['side'],'sell');self.assertEqual(two['entries'][0]['side'],'buy');self.assertIsNone(two['next_before'])
        self.assertGreater(one['entries'][0]['sequence'],two['entries'][0]['sequence']);self.assertEqual(a.call('score'),score)
        self.assertEqual(len(b.call('trade_history',{'before':None,'limit':10})['entries']),1)
        a.call('buy',{'goods_id':g,'quantity':1},'buy');self.assertEqual(len(a.call('trade_history',{'before':None,'limit':10})['entries']),2)
    def test_history_denies_foreign_identity_invalid_limits_and_cache(self):
        a=self.logged()
        for args in ({'before':None,'limit':0},{'before':None,'limit':101},{'before':None,'limit':True},{'before':None,'limit':5,'player_id':'other'}):
            with self.assertRaises(ClientError):a.call('trade_history',args)
        with self.assertRaises(ClientError):a.cached('trade_history')
    def test_shared_route_progress_bonus_and_open(self):
        a=self.logged();b=self.logged('bbs_b');pa=a.call('status')['player_id'];pb=b.call('status')['player_id']
        with self.m.repo.transaction() as w:
            rid,route=next((rid,r) for rid,r in w.routes.items() if not r['is_open'])
            for pid in (pa,pb):w.players[pid].planet_id=route['from'];w.players[pid].cash=10000000
            w.players[pa].ship_id=next(sid for sid,p in self.m.repo.catalog.ship_profiles.items() if p.ship_type=='engineering')
        before=next(r for r in a.call('routes') if r['route_id']==rid)
        result=a.call('donate',{'route_id':rid,'paid_credits':1})
        after=next(r for r in a.call('routes') if r['route_id']==rid);other=next(r for r in b.call('routes') if r['route_id']==rid)
        self.assertEqual(after['donated_credits'],1);self.assertEqual(after['development_effect'],other['development_effect'])
        self.assertLessEqual(after['remaining_credits'],other['remaining_credits'])
        a.call('donate',{'route_id':rid,'paid_credits':after['remaining_credits']})
        self.assertTrue(next(r for r in b.call('routes') if r['route_id']==rid)['is_open'])
        q=a.call('quote_navigation',{'destination_id':before['destination_id'],'mode':'normal','level':None})
        self.assertEqual(q['fuel_cost'],0);self.assertEqual(q['distance'],before['distance']);self.assertIn('estimated_arrival_at',q)
