import json,tempfile,unittest,concurrent.futures
from unittest.mock import patch
import tests.test_phase5 as phase5
from tests.phase5_support import certificate
from tests.test_exploration import exploration_data
from starroute.universe_package import export_package
from starroute_bbs.client import ClientError
from starroute.exploration import coordinates,HIDDEN
from starroute.repository import SQLiteRepository
from starroute.operations import Manager

class ExplorationNetworkTests(unittest.TestCase):
    setUp=phase5.Phase5Tests.setUp
    stop_server=phase5.Phase5Tests.stop_server
    client=phase5.Phase5Tests.client
    logged=phase5.Phase5Tests.logged
    @classmethod
    def setUpClass(cls):
        cls.package=export_package(exploration_data('exploration-network'))
        cls.certdir=tempfile.TemporaryDirectory();cls.cert,cls.key=certificate(cls.certdir.name)
    @classmethod
    def tearDownClass(cls):cls.certdir.cleanup()
    def equip(self,client):
        pid=client.call('status')['player_id']
        with self.m.repo.transaction() as w:w.players[pid].cash=2000000
        client.call('buy_device',{},'device');return pid
    def trip(self,c):
        x,y=coordinates(self.m.repo.catalog)[HIDDEN]
        args=dict(x=x,y=y,mode='normal',level=None);q=c.call('coordinate_quote',args)
        c.call('coordinate_depart',{**args,'quote_id':q['quote_id']},'trip');return q
    def test_tls_discovery_private_map_shared_market_and_replay(self):
        a=self.logged();b=self.logged('bbs_b');pa=self.equip(a);pb=self.equip(b)
        for op in ('map','market','ui_info','news','production','development','routes','notebook','explorer_info'):
            encoded=json.dumps(a.call(op))
            for forbidden in ('hidden-001','private_world','reference_planet_id','private_caps','"truth"'):
                self.assertNotIn(forbidden,encoded)
        q=self.trip(a);self.assertNotIn('hidden-001',json.dumps(a.call('map')))
        self.clock.advance(q['seconds']);a.connect();b.connect();a.call('status');b.call('status')
        self.assertTrue(a.call('ui_info')['exploration']['naming_pending'])
        self.assertIn('hidden-001',json.dumps(a.call('map')));self.assertNotIn('hidden-001',json.dumps(b.call('map')))
        a.call('name_star',{'value':'私のMiXeD星'},'name')
        self.assertEqual(a.post('result',{**a.target(),'operation':'name_star','request_id':'name'})['result']['personal_name'],'私のMiXeD星')
        with self.assertRaises(ClientError):b.call('market',{'planet_id':HIDDEN})
        q=self.trip(b);self.clock.advance(q['seconds']);a.connect();b.connect();a.call('status');b.call('status')
        b.call('name_star',{'value':'私のMiXeD星'})
        good=next(r for r in a.call('market')['entries'] if r['stock']>0)
        a.call('buy',{'goods_id':good['goods_id'],'quantity':1},'shared-buy')
        self.assertEqual(next(r for r in b.call('market')['entries'] if r['goods_id']==good['goods_id'])['stock'],good['stock']-1)
        self.assertEqual(len(a.call('discoverers')),2)
        # An undiscovered third site's persistent cache contains no private world.
        c=self.logged('bbs_c');c.call('map');self.assertNotIn('hidden-001',json.dumps(c.call('map')))
    def test_concurrent_device_requests_one_charge(self):
        a=self.logged();pid=a.call('status')['player_id']
        with self.m.repo.transaction() as w:w.players[pid].cash=2000000
        def buy(_):return a.post('call',{**a.target(),'operation':'buy_device','arguments':{},'request_id':'same'})
        with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(buy,range(2)))
        self.assertEqual(results[0],results[1]);self.assertEqual(a.call('status')['cash'],1000000)
    def test_round_archive_retains_arrivals_resets_device_and_notebook(self):
        a=self.logged();self.equip(a);q=self.trip(a);self.clock.advance(q['seconds']);a.connect();a.call('status');a.call('name_star',{'value':'First Star'})
        pkg=export_package(exploration_data('exploration-next'))
        m=Manager(self.db,self.clock.now());self.addCleanup(m.close)
        uid=m.stage(json.dumps(pkg).encode());m.register(uid);m.prepare(uid,2,self.clock.now());m.activate(2,uid,1,self.uid)
        from starroute.application import Application
        app=Application(m.repo,self.clock);pid=m.repo.resolve_account('bbs_a','1')
        self.assertFalse(app._call('explorer_info',pid)['device']);self.assertEqual(app._call('notebook',pid),[])
        records=app._call('discoverers',pid);self.assertEqual(len(records),1);self.assertEqual(records[0]['round_id'],1)
        self.assertEqual(records[0]['name'],'First Star');self.assertEqual(m.inspect()['integrity'],['ok'])
    def test_disconnect_before_response_resolves_without_rebilling(self):
        a=self.logged();self.equip(a)
        result=a.call('guild',{},'guild-once');cash=a.call('status')['cash'];a.connect()
        self.assertEqual(a.post('result',{**a.target(),'operation':'guild','request_id':'guild-once'})['result'],result)
        self.assertEqual(a.call('guild',{},'guild-once'),result);self.assertEqual(a.call('status')['cash'],cash)
