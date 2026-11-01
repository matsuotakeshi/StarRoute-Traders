import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from starroute.application import Application
from starroute.repository import SQLiteRepository
from starroute.catalog import Catalog
from starroute.clock import ManualClock
from starroute.model import GameError
from starroute.master import MasterService,ServerContext,Visibility,WorldTarget,target_for,public_definition
from starroute.universe import generate

ROOT=Path(__file__).resolve().parents[1]

class MasterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'world.db';self.clock=ManualClock(100)

    def ready(self,data=None):
        r=SQLiteRepository(self.path,Catalog(data) if data else Catalog.load(ROOT/'examples/industry-effects-trial.json'),now=100)
        self.addCleanup(r.close);a=Application(r,self.clock);m=MasterService(a)
        with r.transaction() as world:target=target_for(r,world)
        v=Visibility({'aurora','forge'},set(),{'aurora-forge'})
        c=ServerContext(target,'site_a','user1',v)
        m.execute(c,'register',{'handle':'Captain'},request_id='register')
        return r,a,m,c

    def state(self,r):
        return {t:[tuple(x) for x in r.connection.execute('SELECT * FROM '+t)] for t in
                ('markets','player_state','cargo','planet_development','investment_records','operation_history','economy_clock')}

    def test_site_accounts_and_assets_are_independent(self):
        r,a,m,c=self.ready();other=ServerContext(c.target,'site_b','user1',c.visibility)
        second=m.execute(other,'register',{'handle':'Same person'},request_id='register')
        first=m.execute(c,'status',{})
        self.assertNotEqual(first['player_id'],second['player_id'])
        m.execute(c,'buy',{'goods_id':'grain','quantity':1},request_id='buy')
        self.assertEqual(m.execute(other,'status',{})['cash'],5000)
        self.assertEqual(m.execute(other,'status',{})['cargo'],[])
        self.assertEqual(m.execute(other,'market',{})['entries'][0]['stock'],199)

    def test_explicit_disclosure_excludes_closed_or_unknown_routes(self):
        r,a,m,c=self.ready();view=m.manifest(c)
        self.assertEqual([p['planet_id'] for p in view['definition']['planets']],['aurora','forge'])
        self.assertEqual([x['id'] for x in view['definition']['routes']],['aurora-forge'])
        self.assertEqual([x['route_id'] for x in m.execute(c,'routes',{})],['aurora-forge'])
        self.assertNotIn('haven',json.dumps(view))
        with self.assertRaises(GameError) as e:m.execute(c,'quote_navigation',{'destination_id':'haven','mode':'normal','level':None})
        self.assertEqual(e.exception.code,'DISCLOSURE_DENIED')

    def test_default_visibility_denies_private_and_market_reads(self):
        r,a,m,c=self.ready();empty=ServerContext(c.target,c.bbs_id,c.user_id)
        self.assertEqual(m.manifest(empty)['definition']['planets'],[])
        self.assertEqual(m.manifest(empty)['definition']['routes'],[])
        self.assertEqual(m.execute(empty,'status',{})['handle'],'Captain')
        for op in ('market','production','development','routes'):
            with self.subTest(op=op),self.assertRaises(GameError):m.execute(empty,op,{})

    def test_generated_seed_caps_resources_and_full_hash_not_disclosed(self):
        t=Catalog.load(ROOT/'examples/industry-effects-trial.json').data
        p=json.loads((ROOT/'examples/universe-generator-trial.json').read_text())
        d=generate(t,p,'server-private-seed');r,a,m,c=self.ready(d)
        pid=d['starting']['planet_id'];c=ServerContext(c.target,c.bbs_id,c.user_id,Visibility({pid},{pid},set()))
        view=m.manifest(c);text=json.dumps([view,m.execute(c,'development',{}),m.execute(c,'production',{})])
        self.assertEqual(len(view['definition']['planets']),1)
        self.assertIn('coordinates',view['definition']['planets'][0])
        for token in ('server-private-seed','private_caps','resources','template',d['universe']['definition_hash']):
            self.assertNotIn(token,text)
        self.assertNotIn('definition_hash',view);self.assertIn('public_definition_hash',view)

    def test_coordinates_need_explicit_separate_permission(self):
        t=Catalog.load(ROOT/'examples/industry-effects-trial.json').data
        d=generate(t,json.loads((ROOT/'examples/universe-generator-trial.json').read_text()),'coordinates')
        cat=Catalog(d);target=WorldTarget(d['universe']['universe_id'],1)
        hidden=public_definition(cat,target,Visibility({'001'},set(),set()))
        shown=public_definition(cat,target,Visibility({'001'},{'001'},set()))
        self.assertNotIn('coordinates',hidden['definition']['planets'][0]);self.assertIn('coordinates',shown['definition']['planets'][0])
        self.assertNotEqual(hidden['public_definition_hash'],shown['public_definition_hash'])

    def test_public_hash_independent_of_current_economy_and_player(self):
        r,a,m,c=self.ready();before=m.manifest(c)
        m.execute(c,'buy',{'goods_id':'grain','quantity':1},request_id='one')
        m.execute(c,'invest',{'industry':'primary','paid_credits':100},request_id='invest')
        self.clock.advance(120);m.execute(c,'production',{})
        self.assertEqual(before,m.manifest(c))
        other=ServerContext(c.target,'site_b','u',c.visibility);m.execute(other,'register',{'handle':'B'},request_id='reg')
        self.assertEqual(before,m.manifest(other))

    def test_client_results_and_identity_fields_rejected(self):
        r,a,m,c=self.ready();before=self.state(r)
        for field in ('price','total','cash','result','bbs_id','user_id','player_id','universe_id','round_id','visibility'):
            with self.subTest(field=field),self.assertRaises(GameError) as error:
                m.execute(c,'buy',{'goods_id':'grain','quantity':1,field:0},request_id='fake')
            self.assertEqual(error.exception.code,'MASTER_REQUEST_INVALID')
        self.assertEqual(before,self.state(r))
        for qty in (True,-1,0,1.5,'1'):
            with self.subTest(qty=qty),self.assertRaises(GameError):m.execute(c,'buy',{'goods_id':'grain','quantity':qty},request_id='bad')

    def test_stale_universe_and_round_rejected_before_retry_or_update(self):
        r,a,m,c=self.ready();m.execute(c,'buy',{'goods_id':'grain','quantity':1},request_id='saved')
        before=self.state(r);self.clock.advance(120)
        for target in (WorldTarget('other-universe',1),WorldTarget(c.target.universe_id,2)):
            stale=ServerContext(target,c.bbs_id,c.user_id,c.visibility)
            for call in (lambda:m.execute(stale,'buy',{'goods_id':'grain','quantity':1},request_id='saved'),
                         lambda:m.result(stale,'buy','saved'),lambda:m.manifest(stale),
                         lambda:m.execute(stale,'register',{'handle':'Captain'},request_id='register')):
                with self.assertRaises(GameError) as e:call()
                self.assertEqual(e.exception.code,'WORLD_TARGET_MISMATCH')
        self.assertEqual(before,self.state(r))

    def test_missing_idempotency_key_and_conflicting_retry_rejected(self):
        r,a,m,c=self.ready()
        with self.assertRaises(GameError):m.execute(c,'buy',{'goods_id':'grain','quantity':1})
        m.execute(c,'buy',{'goods_id':'grain','quantity':1},request_id='buy')
        with self.assertRaises(GameError) as e:m.execute(c,'buy',{'goods_id':'grain','quantity':2},request_id='buy')
        self.assertEqual(e.exception.code,'REQUEST_CONFLICT')

    def test_uncertain_completion_lookup_and_retry_after_restart(self):
        r,a,m,c=self.ready();receipt=m.execute(c,'buy',{'goods_id':'grain','quantity':1},request_id='lost-reply')
        # Simulate losing only the response, not rolling back a committed transaction.
        r.close();r=SQLiteRepository(self.path);self.addCleanup(r.close);m=MasterService(Application(r,self.clock))
        self.assertEqual(m.result(c,'buy','lost-reply'),{'status':'committed','result':receipt})
        self.assertEqual(m.execute(c,'buy',{'goods_id':'grain','quantity':1},request_id='lost-reply'),receipt)
        self.assertEqual(m.result(c,'buy','never-seen'),{'status':'unknown'})
        self.assertEqual(len(Application(r,self.clock).trade_ledger(receipt.get('player_id',r.resolve_account(c.bbs_id,c.user_id)))),1)

    def test_result_lookup_is_scoped_and_does_not_advance_time(self):
        r,a,m,c=self.ready();m.execute(c,'buy',{'goods_id':'grain','quantity':1},request_id='same-key')
        other=ServerContext(c.target,'site_b','user1',c.visibility);m.execute(other,'register',{'handle':'B'},request_id='reg')
        before=self.state(r);self.clock.advance(300)
        self.assertEqual(m.result(other,'buy','same-key'),{'status':'unknown'})
        self.assertEqual(m.result(c,'register','register')['status'],'committed')
        with self.assertRaises(GameError):m.result(c,'invest','same-key')
        self.assertEqual(before,self.state(r))

    def test_failed_transaction_rolls_back_cash_stock_and_ledger(self):
        r,a,m,c=self.ready();before=self.state(r);self.clock.advance(60)
        with patch.object(r,'record_trade',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):m.execute(c,'buy',{'goods_id':'grain','quantity':1},request_id='failure')
        self.assertEqual(before,self.state(r));self.assertEqual(m.result(c,'buy','failure'),{'status':'unknown'})

    def test_repeated_investment_only_one_charge(self):
        r,a,m,c=self.ready();args={'industry':'primary','paid_credits':100}
        first=m.execute(c,'invest',args,request_id='invest');self.clock.advance(60)
        self.assertEqual(first,m.execute(c,'invest',args,request_id='invest'))
        self.assertEqual(m.execute(c,'status',{})['cash'],4900)
        self.assertEqual(len(a.investment_ledger(a.resolve_account(c.bbs_id,c.user_id))),1)

    def test_navigation_requires_disclosed_route_and_master_quote(self):
        r,a,m,c=self.ready();args={'destination_id':'forge','mode':'warp','level':'fast'}
        quote=m.execute(c,'quote_navigation',args)
        self.assertNotIn('quote_id',quote)
        receipt=m.execute(c,'navigate',args,request_id='trip')
        self.assertNotIn('quote_id',receipt)
        self.assertEqual(receipt['fuel_cost'],20);self.assertEqual(m.execute(c,'status',{})['cash'],4980)
        self.clock.advance(receipt['seconds']);self.assertEqual(m.execute(c,'dock',{},request_id='dock')['fee'],0)

    def test_concurrent_sites_cannot_double_spend_last_stock(self):
        d=Catalog.load().data
        for row in d['markets']:
            if row['planet_id']=='aurora' and row['goods_id']=='grain':row['stock']=1
        r,a,m,c=self.ready(d);other=ServerContext(c.target,'site_b','user1',c.visibility)
        m.execute(other,'register',{'handle':'B'},request_id='register');r.close();results=[]
        def buy(ctx):
            repo=SQLiteRepository(self.path)
            try:results.append(MasterService(Application(repo,ManualClock(100))).execute(ctx,'buy',{'goods_id':'grain','quantity':1},request_id='buy'))
            except GameError as e:results.append(e.code)
            finally:repo.close()
        threads=[threading.Thread(target=buy,args=(ctx,)) for ctx in (c,other)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(sum(isinstance(x,dict) for x in results),1);self.assertIn('INSUFFICIENT_STOCK',results)
        repo=SQLiteRepository(self.path);self.addCleanup(repo.close)
        self.assertEqual(repo.connection.execute("SELECT stock FROM markets WHERE planet_id='aurora' AND goods_id='grain'").fetchone()[0],0)

    def test_same_account_parallel_requests_preserve_cash_and_capacity(self):
        d=Catalog.load().data;d['starting']['cash']=100
        r,a,m,c=self.ready(d);r.close();results=[]
        def buy(key):
            repo=SQLiteRepository(self.path)
            try:results.append(MasterService(Application(repo,ManualClock(100))).execute(c,'buy',{'goods_id':'grain','quantity':1},request_id=key))
            except GameError as e:results.append(e.code)
            finally:repo.close()
        threads=[threading.Thread(target=buy,args=(key,)) for key in ('one','two')]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(sum(isinstance(x,dict) for x in results),1);self.assertIn('INSUFFICIENT_FUNDS',results)
        repo=SQLiteRepository(self.path);self.addCleanup(repo.close)
        status=MasterService(Application(repo,ManualClock(100))).execute(c,'status',{})
        self.assertEqual(status['cash'],40);self.assertLessEqual(status['used_capacity'],status['capacity'])

    def test_master_enforces_cargo_limit_and_authoritative_price(self):
        d=Catalog.load().data
        for ship in d['ships']:
            if ship['id']==d['starting']['ship_id']:ship['capacity']=1
        r,a,m,c=self.ready(d);before=self.state(r)
        with self.assertRaises(GameError) as e:m.execute(c,'buy',{'goods_id':'grain','quantity':2},request_id='too-many')
        self.assertEqual(e.exception.code,'INSUFFICIENT_CAPACITY');self.assertEqual(before,self.state(r))
        result=m.execute(c,'buy',{'goods_id':'grain','quantity':1},request_id='valid')
        self.assertEqual(result['total'],60);self.assertEqual(m.execute(c,'status',{})['used_capacity'],1)

    def test_unknown_request_values_return_domain_errors(self):
        r,a,m,c=self.ready()
        with self.assertRaises(GameError):m.execute(c,'quote_navigation',{'destination_id':[],'mode':'normal','level':None})
        with self.assertRaises(GameError):m.result(c,[],'key')

    def test_future_internal_response_fields_are_not_forwarded(self):
        r,a,m,c=self.ready();original=a.engine.get_player
        def extended(*args):return {**original(*args),'private_caps':{'secret':123},'seed':'secret'}
        with patch.object(a.engine,'get_player',extended):
            result=m.execute(c,'status',{})
        self.assertNotIn('private_caps',result);self.assertNotIn('seed',result)

    def test_no_unimplemented_network_or_internal_operations_exposed(self):
        r,a,m,c=self.ready()
        for name in ('update','generate','reference_candidate','configuration_info','event_history','get_region','set_language','admit','donate'):
            with self.subTest(name=name),self.assertRaises(GameError):m.execute(c,name,{})

if __name__=='__main__':unittest.main()
