import concurrent.futures
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import tests.test_phase5 as phase5
from tests.phase5_support import certificate
from srt_universe_generator.levels import generate
from starroute.universe_package import export_package, to_catalog
from starroute_bbs.client import ClientError

ROOT=Path(__file__).resolve().parents[1]


class BuybackNetworkTests(unittest.TestCase):
    setUp=phase5.Phase5Tests.setUp
    stop_server=phase5.Phase5Tests.stop_server
    client=phase5.Phase5Tests.client
    logged=phase5.Phase5Tests.logged
    good=phase5.Phase5Tests.good

    @classmethod
    def setUpClass(cls):
        template=json.loads((ROOT/'examples/market-buyback-trial.json').read_text(encoding='utf-8'))
        template['market_buyback'].update(capacity=2,initial=2,recovery_units=1,interval_seconds=10)
        params=json.loads((ROOT/'examples/phase3-generator.json').read_text(encoding='utf-8'))
        levels=json.loads((ROOT/'examples/industry-levels-trial.json').read_text(encoding='utf-8'))
        cls.package=export_package(generate(template,params,levels,'buyback-network'))
        assert cls.package['schema_version']==2
        assert to_catalog(cls.package).market_buyback==template['market_buyback']
        cls.certdir=tempfile.TemporaryDirectory();cls.cert,cls.key=certificate(cls.certdir.name)

    @classmethod
    def tearDownClass(cls):cls.certdir.cleanup()

    def test_two_sites_concurrent_sale_and_shared_recovery(self):
        a=self.logged();b=self.logged('bbs_b');good=self.good(a)
        for client in (a,b):client.call('buy',{'goods_id':good,'quantity':2})
        def sell(client):
            try:return client.call('sell',{'goods_id':good,'quantity':2},'one-sale')
            except ClientError as error:return error.code
        with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(sell,(a,b)))
        self.assertEqual(sum(isinstance(x,dict) for x in results),1)
        self.assertIn('INSUFFICIENT_BUYBACK',results)
        def row(client):return next(r for r in client.call('market')['entries'] if r['goods_id']==good)
        self.assertEqual(row(a)['buyback_available'],0)
        self.assertEqual(row(b)['buyback_available'],0)
        self.clock.advance(9);self.assertEqual(row(a)['buyback_available'],0)
        self.clock.advance(1);self.assertEqual(row(a)['buyback_available'],1)
        self.assertEqual(row(b)['buyback_available'],1)
        cached=a.cached('market')['value']['entries']
        self.assertTrue(all(not (set(r)&{'owned','free_capacity','max_buy','max_sell'}) for r in cached))

    def test_lost_sale_response_resolves_without_second_sale(self):
        a=self.logged();good=self.good(a);a.call('buy',{'goods_id':good,'quantity':2})
        original=a.post
        def lost(path,body,site=False):
            result=original(path,body,site)
            if path=='call' and body['operation']=='sell':
                a.connected=False;raise ClientError('MASTER_UNAVAILABLE')
            return result
        with patch.object(a,'post',side_effect=lost):
            with self.assertRaises(ClientError):a.call('sell',{'goods_id':good,'quantity':1})
        self.assertEqual(a.connect()['status'],'committed')
        self.assertEqual(a.call('status')['cargo'][0]['quantity'],1)
        row=next(r for r in a.call('market')['entries'] if r['goods_id']==good)
        self.assertEqual(row['buyback_available'],1)


if __name__=='__main__':unittest.main()
