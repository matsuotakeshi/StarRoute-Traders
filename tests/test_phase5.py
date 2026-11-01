import copy,json,sqlite3,tempfile,threading,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import tests.test_phase4 as fixtures
from tests.phase5_support import certificate
from starroute.operations import Manager,initialize
from starroute.network import Gateway,TLSServer
from starroute import network_security as sec
from starroute.clock import ManualClock
from starroute_bbs.client import Client,ClientError,save
from starroute.model import GameError
from starroute_bbs.terminal import Terminal,width


class Phase5Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.Phase4Tests.setUpClass();cls.package=fixtures.Phase4Tests.packages[0];cls.next_package=fixtures.Phase4Tests.packages[1]
        cls.certdir=tempfile.TemporaryDirectory();cls.cert,cls.key=certificate(cls.certdir.name)
    @classmethod
    def tearDownClass(cls):cls.certdir.cleanup()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.db=self.root/'game.db';initialize(self.db,100);self.m=Manager(self.db,100);self.addCleanup(self.m.close)
        self.uid=self.m.stage(json.dumps(self.package).encode());self.m.register(self.uid);self.m.prepare(self.uid,1,100);self.m.activate(1,self.uid)
        sec.schema(self.m.c);self.signing=b'x'*32;sec.publish(self.m.repo,self.signing);self.clock=ManualClock(100)
        self.gateway=Gateway(self.db,self.signing,self.clock,session_seconds=60)
        self.server=TLSServer(('127.0.0.1',0),self.gateway,self.cert,self.key,requests_per_minute=1000)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.stop_server)
        self.profiles={};self.clients=[]
    def stop_server(self):self.server.shutdown();self.server.server_close();self.thread.join(5)
    def client(self,site='bbs_a',user='1',name='Pilot',claim=None):
        if site not in self.profiles:
            p=sec.provision(self.m.repo,self.signing,site,site,100,claim);self.profiles[site]=p;save(self.root/(site+'.json'),p)
        cfg={'url':f'https://127.0.0.1:{self.server.server_port}','profile':str(self.root/(site+'.json')),'ca_file':self.cert,'state_directory':str(self.root/'client-state'),'timeout':2}
        c=Client(cfg,user,name);self.clients.append(c);return c
    def logged(self,*args,**kwargs):
        c=self.client(*args,**kwargs);c.connect();return c
    def good(self,c):return next(r['goods_id'] for r in c.call('market')['entries'] if r['stock']>2)

    def test_two_sites_identity_and_shared_stock(self):
        a=self.logged();b=self.logged('bbs_b');self.assertNotEqual(a.call('status')['player_id'],b.call('status')['player_id'])
        good=self.good(a);before=next(x['stock'] for x in b.call('market')['entries'] if x['goods_id']==good)
        a.call('buy',{'goods_id':good,'quantity':1});after=next(x['stock'] for x in b.call('market')['entries'] if x['goods_id']==good)
        self.assertEqual(before-after,1);self.assertEqual(b.call('status')['cargo'],[])
    def test_bad_site_token(self):
        c=self.client();c.profile['credential']='bad'
        with self.assertRaises(ClientError) as e:c.connect()
        self.assertEqual(e.exception.code,'AUTH_FAILED')
    def test_user_impersonation_body_rejected(self):
        c=self.logged()
        with self.assertRaises(ClientError):c.post('call',{**c.target(),'operation':'status','arguments':{'user_id':'other'},'request_id':None})
    def test_site_impersonation_attestation(self):
        a=self.client();b=self.client('bbs_b');a.profile['attestation']=b.profile['attestation']
        with self.assertRaises(ClientError) as e:a.connect()
        self.assertEqual(e.exception.code,'CONFIG_VERIFICATION_FAILED')
    def test_disabled_site(self):
        a=self.logged();self.m.c.execute("UPDATE p5_sites SET state='DISABLED'")
        with self.assertRaises(ClientError):a.call('status')
    def test_request_replay_and_conflict(self):
        a=self.logged();good=self.good(a);args={'goods_id':good,'quantity':1}
        one=a.call('buy',args,'same');two=a.call('buy',args,'same');self.assertEqual(one,two)
        with self.assertRaises(ClientError) as e:a.call('buy',{'goods_id':good,'quantity':2},'same')
        self.assertEqual(e.exception.code,'REQUEST_CONFLICT');self.assertEqual(a.call('status')['cargo'][0]['quantity'],1)
    def test_untrusted_price_rejected(self):
        a=self.logged()
        with self.assertRaises(ClientError):a.call('buy',{'goods_id':self.good(a),'quantity':1,'price':0})
    def test_unknown_operation(self):
        a=self.logged()
        with self.assertRaises(ClientError):a.call('activate',{'universe_id':'x'})
    def test_signed_local_mismatch(self):
        ref=sec.reference(self.m.repo,self.signing);ref['game_rules_hash']='0'*64;a=self.client(claim=ref)
        with self.assertRaises(ClientError) as e:a.connect()
        self.assertEqual(e.exception.code,'LOCAL_CONFIG_MISMATCH')
    def test_remote_and_both_mismatch(self):
        normal=self.client();bad=sec.reference(self.m.repo,self.signing);bad['protocol']=999;other=self.client('bbs_b',claim=bad)
        other.post('connect',{'attestation':other.profile['attestation'],'configuration':bad},site=True)
        r=normal.post('connect',{'attestation':normal.profile['attestation'],'configuration':normal.profile['configuration'],'peer':'bbs_b'},site=True)
        self.assertEqual(r['diagnostic']['code'],'REMOTE_CONFIG_MISMATCH')
        third=self.client('bbs_c',claim=bad)
        r=third.post('connect',{'attestation':third.profile['attestation'],'configuration':bad,'peer':'bbs_b'},site=True)
        self.assertEqual(r['diagnostic']['code'],'BOTH_CONFIG_MISMATCH')
    def test_unavailable_peer_not_mismatch(self):
        a=self.client();r=a.post('connect',{'attestation':a.profile['attestation'],'configuration':a.profile['configuration'],'peer':'missing'},site=True)
        self.assertEqual(r['diagnostic']['code'],'CONFIG_VERIFICATION_FAILED');self.assertEqual(r['diagnostic']['remote'],'unavailable')
    def test_unverified_self_report(self):
        a=self.client();a.profile['configuration']['game_rules_hash']='bad'
        with self.assertRaises(ClientError) as e:a.connect()
        self.assertEqual(e.exception.code,'CONFIG_VERIFICATION_FAILED')
    def test_reference_missing(self):
        a=self.client();self.m.c.execute('DELETE FROM p5_references')
        with self.assertRaises(ClientError) as e:a.connect()
        self.assertEqual(e.exception.code,'REFERENCE_CONFIG_UNAVAILABLE')
    def test_reference_signature_invalid(self):
        a=self.client();row=json.loads(self.m.c.execute('SELECT reference_json FROM p5_references').fetchone()[0]);row['mac']='bad'
        self.m.c.execute('UPDATE p5_references SET reference_json=?',(json.dumps(row),))
        with self.assertRaises(ClientError) as e:a.connect()
        self.assertEqual(e.exception.code,'CONFIG_VERIFICATION_FAILED')
    def test_target_mismatch(self):
        a=self.logged();body={**a.target(),'operation':'status','arguments':{},'request_id':None};body['round_id']=2
        with self.assertRaises(ClientError) as e:a.post('call',body)
        self.assertEqual(e.exception.code,'WORLD_TARGET_MISMATCH')
    def test_language_is_not_rules(self):
        a=self.logged();a.config['language']='ja';b=self.logged('bbs_b');b.config['language']='en'
        self.assertEqual(a.reference,b.reference)
    def test_public_projection_no_secrets(self):
        a=self.logged();data=a.call('map');text=json.dumps(data)
        self.assertLess(len(data['definition']['planets']),48)
        for secret in ('maximum_level','private_caps','seed','template','resources','event_probabilities'):self.assertNotIn(secret,text)
    def test_who_scope_logout_timeout(self):
        a=self.logged();b=self.logged('bbs_b');rows=a.who();self.assertEqual(rows['count'],2)
        self.assertEqual(set(rows['players'][0]),{'player','bbs'});b.logout();self.assertEqual(a.who()['count'],1)
        self.clock.advance(61)
        with self.assertRaises(ClientError):a.who()
    def test_duplicate_session_not_duplicate_who(self):
        a=self.logged();b=self.client();b.session_id=a.session_id;b.connect();self.assertEqual(b.who()['count'],1)
        with self.assertRaises(ClientError):a.call('status')
    def test_disconnect_no_offline_mutation_or_reset(self):
        a=self.logged();a.call('market');before=a.call('status');a.config['url']='https://127.0.0.1:1'
        with self.assertRaises(ClientError):a.call('status')
        with self.assertRaises(ClientError):a.call('buy',{'goods_id':'x','quantity':1})
        self.assertFalse(a.pending.exists());self.assertTrue(a.cached('market')['stale'])
        a.config['url']=f'https://127.0.0.1:{self.server.server_port}';a.connect();self.assertEqual(a.call('status'),before)
    def test_lost_response_recovery(self):
        a=self.logged();good=self.good(a);original=a.post
        def lost(path,body,site=False):
            result=original(path,body,site)
            if path=='call' and body['operation']=='buy':a.connected=False;raise ClientError('MASTER_UNAVAILABLE')
            return result
        with patch.object(a,'post',side_effect=lost):
            with self.assertRaises(ClientError):a.call('buy',{'goods_id':good,'quantity':1})
        self.assertTrue(a.pending.exists());self.assertEqual(a.connect()['status'],'committed')
        self.assertEqual(a.call('status')['cargo'][0]['quantity'],1);self.assertFalse(a.pending.exists())
    def test_truncated_response_preserves_uncertain_request(self):
        from http.client import IncompleteRead
        from unittest.mock import MagicMock
        a=self.logged();good=self.good(a);opener=MagicMock();opener.open.return_value.read.side_effect=IncompleteRead(b'{',10)
        with patch('starroute_bbs.client.build_opener',return_value=opener):
            with self.assertRaises(ClientError) as e:a.call('buy',{'goods_id':good,'quantity':1})
        self.assertEqual(e.exception.code,'MASTER_UNAVAILABLE');self.assertTrue(a.pending.exists());self.assertFalse(a.connected)
        self.assertEqual(a.connect()['status'],'unknown');a.retry_pending();self.assertEqual(a.call('status')['cargo'][0]['quantity'],1)
    def test_private_status_not_cached(self):
        a=self.logged();a.call('status');self.assertFalse(a.cache.exists())
    def test_tls_wrong_ca(self):
        import ssl
        a=self.client();a.context=ssl.create_default_context()
        with self.assertRaises(ClientError):a.connect()
    def test_terminal_map_ansi_names_width(self):
        a=self.logged();out=[];ui=Terminal(a,output=out.append);ui.names=True;ui.map()
        self.assertTrue(any('\x1b[32m*' in x for x in out));self.assertTrue(all(width(x)<=80 for x in out))
        ui.ansi=False;out.clear();ui.map();self.assertNotIn('\x1b',''.join(out))
    def test_transit_restrictions(self):
        a=self.logged();route=next(x for x in a.call('routes') if x['is_open'])
        a.call('navigate',{'destination_id':route['destination_id'],'mode':'normal','level':None});a.call('news');a.call('flight');a.call('map')
        for op,args in [('buy',{'goods_id':'grain','quantity':1}),('invest',{'industry':'primary','paid_credits':100}),('rankings',{})]:
            with self.assertRaises(ClientError) as e:a.call(op,args)
            self.assertEqual(e.exception.code,'IN_TRANSIT')
    def test_audit_no_tokens(self):
        a=self.logged();a.call('status');text=json.dumps([dict(r) for r in self.m.c.execute('SELECT * FROM p5_audit')])
        self.assertNotIn(a.token,text);self.assertNotIn(a.profile['credential'],text)

    def test_concurrent_last_stock_independent_processes(self):
        import subprocess,sys,time
        a=self.logged();b=self.logged('bbs_b');good=self.good(a);planet=a.call('status')['planet_id']
        self.m.c.execute('UPDATE markets SET stock=1 WHERE season_id=1 AND planet_id=? AND goods_id=?',(planet,good))
        start=time.time()+1.5;processes=[]
        script='''import json,sys,time
from starroute_bbs.client import Client,ClientError
c=Client(json.loads(sys.argv[1]),'1','Pilot');c.connect()
while time.time()<float(sys.argv[3]):time.sleep(.01)
try:print(json.dumps({'ok':True,'result':c.call('buy',{'goods_id':sys.argv[2],'quantity':1},'concurrent-buy')}))
except ClientError as e:print(json.dumps({'ok':False,'error':e.code}))
'''
        for client in (a,b):processes.append(subprocess.Popen([sys.executable,'-c',script,json.dumps(client.config),good,str(start)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True))
        results=[]
        for p in processes:
            out,err=p.communicate(timeout=30);self.assertEqual(p.returncode,0,err);results.append(json.loads(out))
        self.assertEqual(sum(r['ok'] for r in results),1,results)
        self.assertEqual(self.m.c.execute('SELECT stock FROM markets WHERE season_id=1 AND planet_id=? AND goods_id=?',(planet,good)).fetchone()[0],0)

    def test_concurrent_route_final_donation(self):
        import concurrent.futures
        a=self.logged();b=self.logged('bbs_b')
        rid,route=next((rid,r) for rid,r in self.m.repo._load().routes.items() if not r['is_open'])
        self.m.c.execute('UPDATE player_state SET planet_id=?',(route['from'],))
        amount=route['distance']*self.m.repo.catalog.phase3['route_cost_per_distance']
        self.m.c.execute('UPDATE player_state SET cash=?',(max(5000,amount),))
        def donate(client):
            try:return client.call('donate',{'route_id':rid,'paid_credits':amount},'final-donation')
            except ClientError as e:return {'error':e.code}
        with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(donate,(a,b)))
        self.assertEqual(sum('jackpot' in r for r in results),1,results)
        saved=[r for r in results if 'jackpot' in r][0]
        self.assertEqual(saved['jackpot'],amount*self.m.repo.catalog.phase3['jackpot_bps']//10000)

    def test_concurrent_last_investment(self):
        import concurrent.futures
        a=self.logged();b=self.logged('bbs_b');c=self.m.repo.catalog;pid=a.call('status')['planet_id'];cap=c.development_planets[pid]['private_caps']['primary']
        self.m.c.execute("UPDATE planet_development SET progress=? WHERE planet_id=? AND industry='primary'",(cap-1,pid))
        def invest(client):
            try:return client.call('invest',{'industry':'primary','paid_credits':c.development['credits_per_unit']['primary']},'last-level')
            except ClientError as e:return {'error':e.code}
        with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(invest,(a,b)))
        self.assertEqual(sum('effect_units' in r for r in results),1,results)
        self.assertEqual(self.m.c.execute("SELECT progress FROM planet_development WHERE planet_id=? AND industry='primary'",(pid,)).fetchone()[0],cap)

    def test_round_reconnect_and_old_pending_result(self):
        a=self.logged();good=self.good(a);body={**a.target(),'operation':'buy','arguments':{'goods_id':good,'quantity':1},'request_id':'old-buy'}
        a.post('call',body);save(a.pending,body);a.call('map')
        nxt=self.m.stage(json.dumps(self.next_package).encode());self.m.register(nxt);self.m.prepare(nxt,2,100);self.m.activate(2,nxt,1,self.uid)
        sec.publish(self.m.repo,self.signing)
        with self.assertRaises(ClientError):a.call('status')
        self.assertEqual(a.connect()['status'],'committed');self.assertEqual(a.reference['round_id'],2)
        self.assertEqual(a.call('status')['cargo'],[]);self.assertFalse(a.cache.exists())
        with self.assertRaises(ClientError):a.post('call',body)

    def test_language_preference_persists(self):
        a=self.logged();a.language('en');b=self.client();self.assertEqual(b.language(),'en')

    def test_heartbeat_keeps_idle_session_without_game_changes(self):
        a=self.logged();before=a.call('status');self.clock.advance(50);a.heartbeat();self.clock.advance(50)
        self.assertEqual(a.who()['count'],1);self.assertEqual(a.call('status'),before)

    def test_terminal_live_size_overrides_startup_environment(self):
        import os,io
        ui=Terminal(None);stream=io.StringIO()
        with patch.dict(os.environ,{'COLUMNS':'80','LINES':'24'}),patch('os.get_terminal_size',return_value=os.terminal_size((100,30))):
            with patch.object(stream,'fileno',return_value=0):ui.resize(stream)
        self.assertEqual((ui.columns,ui.rows),(100,30))

    def test_private_news_never_cached(self):
        a=self.logged()
        with patch.object(a,'post',return_value=[{'event_id':'public','public':True},{'event_id':'private','public':False}]):a.call('news')
        self.assertEqual(a.cached('news')['value'],[{'event_id':'public','public':True}])

    def test_boolean_round_cannot_alias_integer(self):
        a=self.logged()
        with self.assertRaises(ClientError) as e:a.post('call',{'universe_id':self.uid,'round_id':True,'operation':'status','arguments':{},'request_id':None})
        self.assertEqual(e.exception.code,'INVALID_REQUEST')

    def test_rate_and_request_size_bounds(self):
        a=self.logged();self.server.max_body=100
        with self.assertRaises(ClientError) as e:a.post('reference',{'excess':'x'*101},site=True)
        self.assertEqual(e.exception.code,'REQUEST_TOO_LARGE');self.server.max_body=16384
        self.server.requests_per_minute=0
        with self.assertRaises(ClientError) as e:a.who()
        self.assertEqual(e.exception.code,'RATE_LIMITED')

    def test_healthy_peer_and_freshness(self):
        a=self.logged();b=self.logged('bbs_b')
        body={'attestation':a.profile['attestation'],'configuration':a.profile['configuration'],'peer':'bbs_b'}
        self.assertTrue(a.post('connect',body,site=True)['admitted']);self.clock.advance(301)
        self.assertEqual(a.post('connect',body,site=True)['diagnostic']['code'],'CONFIG_VERIFICATION_FAILED')

    def test_site_admin_rotation_and_disable_cli(self):
        import subprocess,sys
        a=self.logged();key=self.root/'reference.key';key.write_bytes(self.signing);output=self.root/'rotated.json'
        prefix=[sys.executable,'-m','starroute.network_admin','--db',str(self.db),'--reference-key',str(key)]
        run=subprocess.run(prefix+['rotate','--bbs-id','bbs_a','--output',str(output)],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr);self.assertNotIn(a.profile['credential'],run.stdout)
        with self.assertRaises(ClientError):a.connect()
        save(self.root/'bbs_a.json',json.loads(output.read_text()));a.connect();a.call('status')
        run=subprocess.run(prefix+['disable','--bbs-id','bbs_a'],capture_output=True,text=True);self.assertEqual(run.returncode,0,run.stderr)
        with self.assertRaises(ClientError):a.call('status')

    def test_result_lookup_cannot_cross_user_or_site(self):
        a=self.logged();b=self.logged('bbs_b');c=self.logged(user='2')
        a.call('buy',{'goods_id':self.good(a),'quantity':1},'private-receipt')
        for client in (b,c):
            result=client.post('result',{**client.target(),'operation':'buy','request_id':'private-receipt'})
            self.assertEqual(result['status'],'unknown');self.assertNotIn('result',result)

    def test_duplicate_json_and_missing_auth_rejected(self):
        import http.client
        a=self.client()
        for body,headers,expected in [('{}',{'Content-Type':'application/json'},'AUTH_FAILED'),
            ('{"x":1,"x":2}',{'Content-Type':'application/json','Authorization':'Bearer '+a.profile['credential']},'INVALID_REQUEST')]:
            conn=http.client.HTTPSConnection('127.0.0.1',self.server.server_port,context=a.context,timeout=3)
            try:
                conn.request('POST','/v1/reference',body,headers);response=conn.getresponse();self.assertEqual(json.loads(response.read())['error'],expected)
            finally:conn.close()

    def test_thin_client_imports_without_engine(self):
        import shutil,subprocess,sys,os
        target=self.root/'thin';target.mkdir();shutil.copytree(Path(__file__).parents[1]/'starroute_bbs',target/'starroute_bbs',ignore=shutil.ignore_patterns('__pycache__'))
        env=os.environ.copy();env.pop('PYTHONPATH',None)
        run=subprocess.run([sys.executable,'-c','import starroute_bbs.client,starroute_bbs.terminal,starroute_bbs.node,starroute_bbs.door; import importlib.util; assert importlib.util.find_spec("starroute") is None'],cwd=target,env=env,capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr)

    def test_news_details_rendered_and_help_not_truncated(self):
        a=self.logged();out=[];ui=Terminal(a,output=out.append)
        with patch.object(a,'call',return_value=[{'kind':'price_surge','planet_id':'001','game_time':100,'values':{'goods_id':'grain','delta':30}}]):ui.execute('news')
        self.assertTrue(any('grain' in line and '30' in line for line in out));out.clear();ui.execute('help')
        self.assertTrue(any('retry' in line for line in out));self.assertTrue(all(width(line)<=80 for line in out))

    def test_join_leave_and_recovery(self):
        from starroute_bbs.node import join,leave,recover
        # Independent local world, with identities/assets kept only in its backup.
        local=self.root/'local.db';initialize(local,100);m=Manager(local,100)
        try:
            uid=m.stage(json.dumps(self.next_package).encode());m.register(uid);m.prepare(uid,1,100);m.activate(1,uid)
        finally:m.close()
        a=self.client();node=self.root/'node.json';new=self.root/'remote.json'
        old={'mode':'standalone','database':str(local)};remote={'mode':'inter-bbs',**a.config};save(node,old);save(new,remote)
        with self.assertRaises(RuntimeError):join(node,new,lambda step:(_ for _ in ()).throw(RuntimeError()))
        self.assertEqual(recover(node)['state'],'RECOVERED');self.assertEqual(json.loads(node.read_text()),old)
        self.assertEqual(join(node,new)['state'],'COMMITTED');a.connect();a.call('buy',{'goods_id':self.good(a),'quantity':1})
        # Leaving requires a distinct, fresh local universe prepared in advance.
        fresh=self.root/'fresh.db';initialize(fresh,100);m=Manager(fresh,100)
        try:
            uid=m.stage(json.dumps(fixtures.Phase4Tests.packages[2]).encode());m.register(uid);m.prepare(uid,1,100);m.activate(1,uid)
        finally:m.close()
        destination=self.root/'standalone.json';save(destination,{'mode':'standalone','database':str(fresh)})
        before=[tuple(r) for r in self.m.c.execute('SELECT * FROM markets')]
        # A committed operation with a lost response must be settled even after departure.
        body={**a.target(),'operation':'buy','arguments':{'goods_id':self.good(a),'quantity':1},'request_id':'departing-buy'}
        a.post('call',body);save(a.pending,body)
        before=[tuple(r) for r in self.m.c.execute('SELECT * FROM markets')]
        original=Client.post
        def lost(client,path,body,site=False):
            result=original(client,path,body,site)
            if path=='leave':raise ClientError('MASTER_UNAVAILABLE')
            return result
        with patch.object(Client,'post',lost):
            with self.assertRaises(ClientError):leave(node,destination)
        self.assertEqual(recover(node)['state'],'COMMITTED');self.assertFalse(a.pending.exists())
        receipt=json.loads((a.directory/'departure-result-departing-buy.json').read_text());self.assertEqual(receipt['status'],'committed');self.assertNotIn('result',receipt)
        self.assertEqual(before,[tuple(r) for r in self.m.c.execute('SELECT * FROM markets')])
        self.assertEqual(self.m.c.execute('SELECT state FROM p5_sites').fetchone()[0],'LEFT')
        self.assertTrue(self.m.c.execute('SELECT * FROM operation_history').fetchall())
