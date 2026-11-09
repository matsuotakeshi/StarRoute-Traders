"""TLS-only bounded master transport. All game decisions stay in Application."""
import argparse,json,ssl,threading,time,secrets,sqlite3
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from .repository import SQLiteRepository
from .application import Application
from .clock import SystemClock
from .master import MasterService,ServerContext,WorldTarget,Visibility,MUTATIONS,public_definition
from .model import GameError
from .catalog import identifier,display_name
from . import network_security as security


def visibility(repo,pid):
    c=repo.connection;r=c.execute('SELECT * FROM player_state WHERE player_id=?',(pid,)).fetchone()
    if not r:return Visibility()
    known={x[0] for x in c.execute('SELECT planet_id FROM p4_visits WHERE round_id=? AND player_id=?',(r['season_id'],pid))}
    known.add(r['planet_id'])
    if r['destination_id']:known.add(r['destination_id'])
    routes=set();planets=set(known)
    for route in c.execute('SELECT * FROM routes WHERE season_id=?',(r['season_id'],)):
        if route['from_id'] in known or route['to_id'] in known:
            routes.add(route['id']);planets.update((route['from_id'],route['to_id']))
    if repo.catalog.exploration is not None:
        from .exploration import discovered,HIDDEN
        if discovered(repo._load(),pid):planets.add(HIDDEN)
        else:planets.discard(HIDDEN)
    return Visibility(frozenset(planets),frozenset(planets),frozenset(routes))


def site_result(repo,bbs,user,body):
    """Read-only completion lookup, including a formally departed site's history."""
    import hashlib,zlib
    from .master import OPERATIONS,response
    identifier(user);identifier(body['request_id'])
    if body['operation'] not in MUTATIONS:raise GameError('INVALID_REQUEST')
    c=repo.connection;roundrow=c.execute('SELECT * FROM p4_rounds WHERE round_id=? AND universe_id=?',(body['round_id'],body['universe_id'])).fetchone()
    if not roundrow:raise GameError('WORLD_TARGET_MISMATCH')
    if body['operation']=='register':actor='account:'+json.dumps([bbs,user])
    else:
        identity=c.execute('SELECT player_id FROM bbs_accounts WHERE bbs_id=? AND local_user_id=?',(bbs,user)).fetchone()
        if not identity:return {'status':'unknown'}
        actor=identity[0]
    saved=c.execute('SELECT * FROM operation_history WHERE season_id=? AND actor=? AND request_id=?',(body['round_id'],actor,body['request_id'])).fetchone()
    if saved is None:
        archive=c.execute('SELECT * FROM p4_archives WHERE round_id=?',(body['round_id'],)).fetchone()
        if archive:
            raw=zlib.decompress(archive['snapshot'])
            if hashlib.sha256(raw).hexdigest()!=archive['sha256']:raise GameError('CONFIG_VERIFICATION_FAILED')
            saved=next((x for x in json.loads(raw)['tables']['operation_history'] if x['actor']==actor and x['request_id']==body['request_id']),None)
    if saved and json.loads(saved['payload'])[0]!=OPERATIONS[body['operation']][0]:raise GameError('REQUEST_CONFLICT')
    return {'status':'committed','result':response(body['operation'],json.loads(saved['result']),Visibility())} if saved else {'status':'unknown','closed_round':roundrow['state']!='ACTIVE'}


class Gateway:
    def __init__(self,database,key,clock=None,session_seconds=300):
        self.database=str(database);self.key=key;self.clock=clock or SystemClock();self.session_seconds=session_seconds

    def dispatch(self,path,token,body):
        if not isinstance(body,dict):raise GameError('INVALID_REQUEST')
        if 'round_id' in body and (type(body['round_id']) is not int or body['round_id']<1):raise GameError('INVALID_REQUEST')
        r=SQLiteRepository(self.database);c=r.connection;now=self.clock.now();site=None;user=None
        try:
            ref=security.reference(r,self.key)
            if path in ('connect','session','reference','leave','rebind','site-result'):
                if path in ('leave','site-result'):
                    site=c.execute('SELECT * FROM p5_sites WHERE credential_hash=?',(security.digest(token),)).fetchone()
                    if not site or site['state'] not in ('ENABLED','LEFT'):raise GameError('AUTH_FAILED')
                    if path=='leave' and site['state']=='LEFT' and body.get('confirm_bbs_id')==site['bbs_id']:return {'state':'LEFT'}
                else:site=security.authenticate(c,token)
                if path=='site-result':
                    if set(body)!={'user_id','universe_id','round_id','operation','request_id'}:raise GameError('INVALID_REQUEST')
                    return site_result(r,site['bbs_id'],body['user_id'],body)
                if path=='rebind':
                    if set(body)!={'attestation','configuration'}:raise GameError('INVALID_REQUEST')
                    evidence=security.verified(self.key,body['attestation'])
                    if evidence.get('bbs_id')!=site['bbs_id'] or body['attestation']!=json.loads(site['approved']) or evidence['configuration']!=body['configuration']:raise GameError('CONFIG_VERIFICATION_FAILED')
                    if any(evidence['configuration'].get(k)!=ref[k] for k in security.CONFIG_FIELDS if k not in ('universe_id','round_id')):raise GameError('LOCAL_CONFIG_MISMATCH')
                    envelope=security.seal(self.key,dict(bbs_id=site['bbs_id'],configuration=ref))
                    c.execute('BEGIN IMMEDIATE');security.authenticate(c,token)
                    if security.reference(r,self.key)!=ref:raise GameError('WORLD_TARGET_MISMATCH')
                    c.execute('UPDATE p5_sites SET approved=?,verified_config=NULL,verified_at=NULL WHERE bbs_id=?',(json.dumps(envelope),site['bbs_id']))
                    c.execute('DELETE FROM p5_sessions WHERE bbs_id=?',(site['bbs_id'],));security.audit(c,now,site['bbs_id'],None,'round_rebind','OK');c.commit()
                    return {'attestation':envelope,'configuration':ref}
                if path=='reference':
                    if body:raise GameError('INVALID_REQUEST')
                    return {'reference':ref}
                if path=='connect':
                    if set(body)-{'attestation','configuration','peer'} or not {'attestation','configuration'}<=set(body):raise GameError('INVALID_REQUEST')
                    result=security.assess(r,self.key,site,body['attestation'],body['configuration'],now,body.get('peer'))
                    if result['code']!='OK':return {'diagnostic':result,'admitted':False}
                    return {'diagnostic':result,'admitted':True}
                if path=='leave':
                    if body!={'universe_id':ref['universe_id'],'round_id':ref['round_id'],'confirm_bbs_id':site['bbs_id']}:raise GameError('INVALID_REQUEST')
                    c.execute('BEGIN IMMEDIATE')
                    c.execute("UPDATE p5_sites SET state='LEFT' WHERE bbs_id=?",(site['bbs_id'],));c.execute('DELETE FROM p5_sessions WHERE bbs_id=?',(site['bbs_id'],))
                    security.audit(c,now,site['bbs_id'],None,'leave','OK');c.commit();return {'state':'LEFT'}
                if set(body)!={'user_id','display_name','session_id','universe_id','round_id'}:raise GameError('INVALID_REQUEST')
                identifier(body['user_id']);identifier(body['session_id']);display_name(body['display_name']);user=body['user_id']
                if not site['verified_config'] or json.loads(site['verified_config'])!=ref:raise GameError('CONFIG_VERIFICATION_FAILED')
                if (body['universe_id'],body['round_id'])!=(ref['universe_id'],ref['round_id']):raise GameError('WORLD_TARGET_MISMATCH')
                app=Application(r,self.clock);ctx=ServerContext(WorldTarget(ref['universe_id'],ref['round_id']),site['bbs_id'],user)
                try:app.resolve_account(site['bbs_id'],user)
                except GameError as e:
                    if e.code!='PLAYER_NOT_FOUND':raise
                    registration=MasterService(app);original_guard=registration._target_guard
                    def registration_guard(context):
                        base=original_guard(context)
                        def check(world):
                            current=security.authenticate(c,token)
                            if not current['verified_config'] or json.loads(current['verified_config'])!=security.reference(r,self.key):raise GameError('CONFIG_VERIFICATION_FAILED')
                            base(world)
                        return check
                    registration._target_guard=registration_guard
                    registration.execute(ctx,'register',{'handle':body['display_name']},request_id='initial-registration')
                session_token=secrets.token_urlsafe(32)
                c.execute('BEGIN IMMEDIATE');security.authenticate(c,token)
                if security.reference(r,self.key)!=ref:raise GameError('WORLD_TARGET_MISMATCH')
                c.execute('DELETE FROM p5_sessions WHERE bbs_id=? AND user_id=? AND session_id=?',(site['bbs_id'],user,body['session_id']))
                c.execute('INSERT INTO p5_sessions VALUES(?,?,?,?,?,?,?,?)',(security.digest(session_token),site['bbs_id'],user,body['display_name'],body['session_id'],now,ref['universe_id'],ref['round_id']))
                security.audit(c,now,site['bbs_id'],user,'login','OK');c.commit()
                return {'session_token':session_token,'reference':ref}
            logged=security.session(c,token,now,self.session_seconds);user=logged['user_id'];site={'bbs_id':logged['bbs_id']}
            if (logged['universe_id'],logged['round_id'])!=(ref['universe_id'],ref['round_id']):raise GameError('WORLD_TARGET_MISMATCH')
            # Every operation rechecks revocation and target under the game write lock.
            app=Application(r,self.clock);pid=app.resolve_account(site['bbs_id'],user)
            ctx=ServerContext(WorldTarget(ref['universe_id'],ref['round_id']),site['bbs_id'],user,visibility(r,pid));master=MasterService(app)
            original=master._target_guard
            def guarded(context):
                base=original(context)
                def check(world):
                    security.session(c,token,now,self.session_seconds)
                    if security.reference(r,self.key)!=ref:raise GameError('WORLD_TARGET_MISMATCH')
                    base(world)
                return check
            master._target_guard=guarded
            if path=='logout':
                if body:raise GameError('INVALID_REQUEST')
                c.execute('DELETE FROM p5_sessions WHERE token_hash=?',(security.digest(token),));security.audit(c,now,site['bbs_id'],user,'logout','OK');return {'logged_out':True}
            if path=='who':
                if body:raise GameError('INVALID_REQUEST')
                rows=c.execute('''SELECT s.bbs_id,s.user_id,MAX(s.display_name) AS display_name,b.name FROM p5_sessions s JOIN p5_sites b ON s.bbs_id=b.bbs_id
                  WHERE b.state='ENABLED' AND s.last_seen>=? AND s.universe_id=? AND s.round_id=? GROUP BY s.bbs_id,s.user_id,b.name ORDER BY b.name,display_name,s.bbs_id,s.user_id''',(now-self.session_seconds,ref['universe_id'],ref['round_id']))
                people=[{'player':x['display_name'],'bbs':x['name']} for x in rows];result={'players':people,'count':len(people)}
            elif path=='heartbeat':
                if body:raise GameError('INVALID_REQUEST')
                result={'online':True}
            elif path=='call':
                if set(body)!={'universe_id','round_id','operation','arguments','request_id'}:raise GameError('INVALID_REQUEST')
                if (body['universe_id'],body['round_id'])!=(ref['universe_id'],ref['round_id']):raise GameError('WORLD_TARGET_MISMATCH')
                op=body['operation']
                if op=='trade_history':
                    from .trade_view import history
                    if body['request_id'] is not None:raise GameError('INVALID_REQUEST')
                    with r.transaction() as world:
                        master._target_guard(ctx)(world)
                        if world.players[pid].destination_id is not None:raise GameError('IN_TRANSIT')
                        result=history(r,world,pid,body['arguments'])
                elif op in ('ui_info','map','score','rankings','hall','rounds','exploration'):
                    if body['arguments'] or body['request_id'] is not None:raise GameError('INVALID_REQUEST')
                    if op not in ('map','ui_info') and c.execute('SELECT destination_id FROM player_state WHERE player_id=?',(pid,)).fetchone()[0]:raise GameError('IN_TRANSIT')
                    if op=='ui_info':
                        from .ui_info import describe
                        with r.transaction() as world:
                            master._target_guard(ctx)(world)
                            result=describe(app.engine,world,pid,ctx.visibility,site['bbs_id'],c)
                    elif op=='map':
                        result=master.manifest(ctx)
                        from .universe import normal_planets
                        english={p['id']:p['en'] for p in normal_planets()}
                        for planet in result['definition']['planets']:planet['name']=english.get(planet['planet_id'],planet['name'])
                        import hashlib
                        from .rules import canonical_bytes
                        result['public_definition_hash']=hashlib.sha256(canonical_bytes(result['definition'])).hexdigest()
                    else:result=app.records(op,pid,ref['round_id'] if op not in ('hall','rounds') else None)
                else:
                    result=master.execute(ctx,op,body['arguments'],request_id=body['request_id'])
                    if op=='news':
                        saved=c.execute('SELECT state_json FROM phase3_state WHERE season_id=?',(ref['round_id'],)).fetchone()
                        news=json.loads(saved[0]).get('news',{}) if saved else {}
                        for item in result:item['public']=news.get(item['event_id'],{}).get('player_id','private') is None
                security.audit(c,now,site['bbs_id'],user,op,'OK',{'request_id':body['request_id']})
            elif path=='result':
                if set(body)!={'universe_id','round_id','operation','request_id'}:raise GameError('INVALID_REQUEST')
                if (body['universe_id'],body['round_id'])!=(ref['universe_id'],ref['round_id']):
                    import zlib,hashlib
                    from .master import OPERATIONS,response
                    if body['operation'] not in MUTATIONS:raise GameError('INVALID_REQUEST')
                    identifier(body['request_id'])
                    archive=c.execute('SELECT * FROM p4_archives WHERE round_id=? AND universe_id=?',(body['round_id'],body['universe_id'])).fetchone()
                    if not archive:raise GameError('WORLD_TARGET_MISMATCH')
                    raw=zlib.decompress(archive['snapshot'])
                    if hashlib.sha256(raw).hexdigest()!=archive['sha256']:raise GameError('CONFIG_VERIFICATION_FAILED')
                    actor='account:'+json.dumps([site['bbs_id'],user]) if body['operation']=='register' else pid
                    saved=next((x for x in json.loads(raw)['tables']['operation_history'] if x['actor']==actor and x['request_id']==body['request_id']),None)
                    if saved and json.loads(saved['payload'])[0]!=OPERATIONS[body['operation']][0]:raise GameError('REQUEST_CONFLICT')
                    result={'status':'committed','result':response(body['operation'],json.loads(saved['result']),Visibility())} if saved else {'status':'unknown','closed_round':True}
                else:result=master.result(ctx,body['operation'],body['request_id'])
            else:raise GameError('INVALID_REQUEST')
            c.execute('UPDATE p5_sessions SET last_seen=? WHERE token_hash=?',(now,security.digest(token)))
            return result
        except BaseException as e:
            c.rollback()
            security.audit(c,now,site['bbs_id'] if site else None,user,path,e.code if isinstance(e,GameError) else 'INVALID_REQUEST')
            raise
        finally:r.close()


class TLSServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,gateway,cert,key,*,max_body=16384,timeout=10,max_clients=32,requests_per_minute=120):
        self.gateway=gateway;self.max_body=max_body;self.timeout_seconds=timeout
        self.slots=threading.BoundedSemaphore(max_clients);self.rate={};self.rate_lock=threading.Lock();self.requests_per_minute=requests_per_minute
        super().__init__(address,Handler)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2;context.load_cert_chain(cert,key)
        self.context=context
    def get_request(self):
        sock,addr=self.socket.accept();sock.settimeout(self.timeout_seconds)
        return sock,addr
    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):request.close();return
        try:super().process_request(request,address)
        except BaseException:self.slots.release();raise
    def process_request_thread(self,request,address):
        try:
            secured=self.context.wrap_socket(request,server_side=True)
            super().process_request_thread(secured,address)
        except (OSError,ssl.SSLError):request.close()
        finally:self.slots.release()


class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    server_version='StarRoute'
    sys_version=''
    def log_message(self,*args):pass
    def do_POST(self):
        status=200
        try:
            length=int(self.headers.get('Content-Length','-1'))
            if length<0 or length>self.server.max_body or self.headers.get('Transfer-Encoding'):raise GameError('REQUEST_TOO_LARGE')
            if self.headers.get('Content-Type')!='application/json':raise GameError('INVALID_REQUEST')
            auth=self.headers.get('Authorization','')
            if not auth.startswith('Bearer '):raise GameError('AUTH_FAILED')
            token=auth[7:]
            now=int(time.time())//60;ratekey=(self.client_address[0],0,now)
            with self.server.rate_lock:
                self.server.rate={k:v for k,v in self.server.rate.items() if k[2]==now}
                count=self.server.rate.get(ratekey,0)+1;self.server.rate[ratekey]=count
            if count>self.server.requests_per_minute:raise GameError('RATE_LIMITED')
            def unique(pairs):
                d={}
                for k,v in pairs:
                    if k in d:raise ValueError('duplicate field')
                    d[k]=v
                return d
            body=json.loads(self.rfile.read(length),object_pairs_hook=unique)
            if not self.path.startswith('/v1/') or '?' in self.path:raise GameError('INVALID_REQUEST')
            value=self.server.gateway.dispatch(self.path[4:],token,body);reply={'ok':True,'result':value}
        except GameError as e:status=403 if e.code in ('AUTH_FAILED','SESSION_EXPIRED') else 409;reply={'ok':False,'error':e.code}
        except sqlite3.OperationalError:status=503;reply={'ok':False,'error':'RETRY_SAME_REQUEST'}
        except (ValueError,TypeError,KeyError,OverflowError,RecursionError):status=400;reply={'ok':False,'error':'INVALID_REQUEST'}
        except Exception:status=500;reply={'ok':False,'error':'SERVER_ERROR'}
        encoded=json.dumps(reply,ensure_ascii=False).encode();self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(encoded)));self.send_header('Cache-Control','no-store');self.send_header('Connection','close');self.end_headers()
        try:self.wfile.write(encoded)
        except (OSError,ssl.SSLError):pass
        self.close_connection=True


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);args=p.parse_args();cfg=json.loads(Path(args.config).read_text())
    key=Path(cfg['reference_key']).read_bytes()
    if len(key)<32:raise ValueError('reference key must contain at least 32 random bytes')
    gateway=Gateway(cfg['database'],key,session_seconds=cfg.get('session_seconds',300))
    server=TLSServer((cfg.get('host','127.0.0.1'),cfg['port']),gateway,cfg['certificate'],cfg['private_key'],
                     max_body=cfg.get('max_body',16384),timeout=cfg.get('timeout',10),max_clients=cfg.get('max_clients',32),requests_per_minute=cfg.get('requests_per_minute',120))
    try:server.serve_forever()
    finally:server.server_close()


if __name__=='__main__':main()
