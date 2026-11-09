import json,tempfile,unittest
from unittest.mock import patch
import tests.test_phase5 as phase5
from tests.phase5_support import certificate
from tests.test_connected_universe import inputs
from srt_universe_generator.levels import generate
from starroute.universe_package import export_package
from starroute_bbs.client import ClientError

class ConnectedNetworkTests(unittest.TestCase):
    setUp=phase5.Phase5Tests.setUp
    stop_server=phase5.Phase5Tests.stop_server
    client=phase5.Phase5Tests.client
    logged=phase5.Phase5Tests.logged
    good=phase5.Phase5Tests.good
    @classmethod
    def setUpClass(cls):
        cls.package=export_package(generate(*inputs(),'connected-network'))
        cls.certdir=tempfile.TemporaryDirectory();cls.cert,cls.key=certificate(cls.certdir.name)
    @classmethod
    def tearDownClass(cls):cls.certdir.cleanup()
    def test_same_universe_independent_start_and_reconnect(self):
        with patch('secrets.choice',side_effect=['001','048']) as choose:
            a=self.logged();b=self.logged('bbs_b');a.connect()
        self.assertEqual(choose.call_count,2)
        self.assertEqual(a.call('status')['planet_id'],'001');self.assertEqual(b.call('status')['planet_id'],'048')
        first=a.call('map');second=b.call('map')
        self.assertEqual(first['definition']['universe_id'],second['definition']['universe_id'])
        self.assertEqual(first['rules'],second['rules'])
        for view in (first,second):
            self.assertTrue({r['planet_id'] for r in view['definition']['planets']}<={f'{n:03}' for n in range(1,49)})
    def test_public_api_cache_and_direct_hidden_requests(self):
        a=self.logged()
        for op in ('map','market','ui_info','news','production','development','routes'):
            encoded=json.dumps(a.call(op))
            for forbidden in ('hidden-001','private_world','reference_planet_id','private_caps','"definition_hash"'):
                self.assertNotIn(forbidden,encoded)
        with self.assertRaises(ClientError):a.call('market',{'planet_id':'hidden-001'})
        with self.assertRaises(ClientError):a.call('buy',{'goods_id':'grain','quantity':1,'planet_id':'hidden-001'})
        with self.assertRaises(ClientError):a.call('navigate',{'destination_id':'hidden-001','mode':'normal','level':None})
        cache=json.dumps(a.cached('map'))
        self.assertNotIn('hidden-001',cache);self.assertNotIn('private_world',cache)

if __name__=='__main__':unittest.main()
