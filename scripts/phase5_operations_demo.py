"""Isolated real TLS process + operator CLI scenarios C/D/E; no production data."""
import argparse,json,os,sys,time,socket,subprocess,http.client
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from phase5_telnet_demo import setup_world
from tests.phase5_support import certificate
from starroute_bbs.client import Client,ClientError,save
from starroute.local_door import LocalDoor
from starroute.repository import SQLiteRepository


def main():
    p=argparse.ArgumentParser();p.add_argument('--directory',required=True);a=p.parse_args()
    base=Path(a.directory).resolve();base.mkdir(mode=0o700,parents=True,exist_ok=False)
    results={};process=None
    def cli(module,*args):
        r=subprocess.run([sys.executable,'-m',module,*map(str,args)],cwd=ROOT,capture_output=True,text=True)
        print(module+' '+str(args[0])+' -> '+r.stdout.strip(),flush=True)
        if r.returncode:raise RuntimeError(r.stderr)
        return r.stdout
    db,_=setup_world(base/'master','phase3-complete-demo');key=base/'master/reference.key'
    cert,tlskey=certificate(base)
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    servercfg=base/'master.json';save(servercfg,{'database':str(db),'reference_key':str(key),'certificate':cert,'private_key':tlskey,'host':'127.0.0.1','port':port,'requests_per_minute':1000})
    log=(base/'server.log').open('w')
    def start():
        proc=subprocess.Popen([sys.executable,'-m','starroute.network','--config',str(servercfg)],cwd=ROOT,stdout=log,stderr=log)
        for _ in range(100):
            if proc.poll() is not None:raise RuntimeError('master exited')
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.1):return proc
            except OSError:time.sleep(.05)
        proc.terminate();proc.wait();raise RuntimeError('master startup timeout')
    def admin(command,*args):return cli('starroute.network_admin','--db',db,'--reference-key',key,command,*args)
    def profile(site):
        path=base/(site+'.json');admin('add','--bbs-id',site,'--name',site,'--output',path)
        return {'mode':'inter-bbs','url':f'https://127.0.0.1:{port}','profile':str(path),'ca_file':cert,'state_directory':str(base/(site+'-state')),'timeout':2}
    def approve(client,bad=False):
        claim=dict(normal)
        if bad:claim['game_rules_hash']='0'*64
        request=base/('claim-'+os.urandom(4).hex()+'.json');output=request.with_suffix('.approved.json');save(request,claim)
        admin('approve','--bbs-id',client.profile['bbs_id'],'--configuration',request,'--output',output)
        client.profile.update(json.loads(output.read_text()));save(client.config['profile'],client.profile)
    def check(client,peer=None):
        body={'attestation':client.profile['attestation'],'configuration':client.profile['configuration']}
        if peer:body['peer']=peer
        result=client.post('connect',body,site=True);print('DIAGNOSTIC '+result['diagnostic']['code'],flush=True);return result
    try:
        process=start();cfg=profile('bbs_c');other=Client(profile('bbs_d'),'1','Pilot');other.connect()
        # C: active local game -> join shared world -> leave into a fresh local world.
        local,_=setup_world(base/'standalone','local-before-join');localprofile=base/'local.json'
        cli('starroute.network_admin','--db',local,'--reference-key',base/'standalone/reference.key','add','--bbs-id','standalone','--name','Local','--output',localprofile)
        node=base/'node.json';old={'mode':'standalone','database':str(local),'reference_key':str(base/'standalone/reference.key'),'profile':str(localprofile)};save(node,old)
        localdoor=LocalDoor(old,'1','Pilot');localdoor.connect();good=next(x['goods_id'] for x in localdoor.call('market')['entries'] if x['stock']>1)
        localdoor.call('buy',{'goods_id':good,'quantity':1});localdoor.logout()
        new=base/'remote.json';save(new,cfg);cli('starroute_bbs.node','--config',node,'join','--new-config',new)
        client=Client(cfg,'1','Pilot');client.connect();assert client.call('status')['cargo']==[]
        good=next(x['goods_id'] for x in client.call('market')['entries'] if x['stock']>1)
        # D: send purchase, discard response body, preserve its durable request ID.
        body={**client.target(),'operation':'buy','arguments':{'goods_id':good,'quantity':1},'request_id':'response-discarded'};save(client.pending,body)
        conn=http.client.HTTPSConnection('127.0.0.1',port,context=client.context,timeout=5)
        conn.request('POST','/v1/call',json.dumps(body),{'Authorization':'Bearer '+client.token,'Content-Type':'application/json'})
        response=conn.getresponse();assert response.status==200;conn.close()
        assert client.connect()['status']=='committed';assert client.call('status')['cargo'][0]['quantity']==1
        client.call('market');before=client.call('status');process.terminate();process.wait();process=None
        try:client.call('status');raise AssertionError('offline accepted')
        except ClientError as e:assert e.code=='MASTER_UNAVAILABLE'
        try:client.call('buy',{'goods_id':good,'quantity':1});raise AssertionError('offline mutation accepted')
        except ClientError as e:assert e.code=='MASTER_UNAVAILABLE'
        assert client.cached('market')['stale'];assert not client.pending.exists()
        process=start();client.connect();assert client.call('status')==before
        results['D']={'discarded_response_resolved':True,'single_purchase':True,'master_process_restart':True,'readonly_cache':True,'no_offline_queue':True}
        print('SCENARIO D PASS',flush=True)
        # E: independently approved descriptors provide verifiable mismatch evidence.
        normal=dict(client.reference);approve(client,True);assert check(client)['diagnostic']['code']=='LOCAL_CONFIG_MISMATCH'
        approve(client);approve(other,True);check(other)
        assert check(client,'bbs_d')['diagnostic']['code']=='REMOTE_CONFIG_MISMATCH'
        approve(client,True);assert check(client,'bbs_d')['diagnostic']['code']=='BOTH_CONFIG_MISMATCH'
        approve(client);approve(other);check(other);assert check(client,'bbs_d')['admitted'];client.connect();other.connect()
        r=SQLiteRepository(db)
        try:
            codes={x[0] for x in r.connection.execute('SELECT code FROM p5_audit')}
            assert {'LOCAL_CONFIG_MISMATCH','REMOTE_CONFIG_MISMATCH','BOTH_CONFIG_MISMATCH'}<=codes
        finally:r.close()
        results['E']={'local_remote_both':True,'restored_and_reconnected':True,'administrator_diagnostics':True};print('SCENARIO E PASS',flush=True)
        fresh,_=setup_world(base/'fresh-local','fresh-after-leave');freshprofile=base/'fresh-profile.json'
        cli('starroute.network_admin','--db',fresh,'--reference-key',base/'fresh-local/reference.key','add','--bbs-id','standalone','--name','Local','--output',freshprofile)
        newlocal=base/'fresh-config.json';save(newlocal,{'mode':'standalone','database':str(fresh),'reference_key':str(base/'fresh-local/reference.key'),'profile':str(freshprofile)})
        otherbefore=other.call('status');marketbefore=other.call('market')
        cli('starroute_bbs.node','--config',node,'leave','--new-config',newlocal)
        assert other.call('status')==otherbefore;assert other.call('market')==marketbefore
        localdoor=LocalDoor(json.loads(node.read_text()),'1','Pilot');localdoor.connect();assert localdoor.call('status')['cargo']==[];localdoor.logout()
        for path in (db,local,fresh):
            r=SQLiteRepository(path)
            try:assert r.connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok';assert not r.connection.execute('PRAGMA foreign_key_check').fetchall()
            finally:r.close()
        results['C']={'operator_cli_join_leave':True,'local_assets_not_imported':True,'fresh_local_reset':True,'other_site_unchanged':True,'backups':len(list(base.rglob('standalone-backup.db'))),'db_integrity':'ok'}
        print('SCENARIO C PASS',flush=True);save(base/'result.json',results);print(json.dumps(results),flush=True)
    finally:
        if process:process.terminate();process.wait()
        log.close()


if __name__=='__main__':main()
