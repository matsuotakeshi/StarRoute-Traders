"""FreeBSD real Liner notes/Telnet/PTY/TLS acceptance, isolated paths only."""
import argparse,json,os,sys,time,threading,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from starroute.operations import initialize,Manager
from starroute.repository import SQLiteRepository
from starroute import network_security as sec
from starroute.network import Gateway,TLSServer
from starroute_bbs.client import Client,save
from tests.phase5_support import certificate
from starroute.universe_package import export_package
from starroute.catalog import Catalog
from srt_universe_generator.levels import generate


def setup_world(directory,seed,open_routes=4):
    directory.mkdir(mode=0o700);now=int(time.time());db=directory/'game.db'
    parameters=json.loads((ROOT/'examples/phase3-generator.json').read_text());parameters['initial_open_routes']=open_routes
    data=generate(Catalog.load(ROOT/'examples/phase3-trial.json').data,parameters,
                  json.loads((ROOT/'examples/industry-levels-trial.json').read_text()),seed)
    package=export_package(data);save(directory/'private-package.json',package);initialize(db,now);m=Manager(db,now)
    try:
        uid=m.stage(json.dumps(package).encode());m.register(uid);m.prepare(uid,1,now);m.activate(1,uid)
        key=os.urandom(32);(directory/'reference.key').write_bytes(key);os.chmod(directory/'reference.key',0o600)
        sec.schema(m.c);sec.publish(m.repo,key)
    finally:m.close()
    return db,key


def main():
    p=argparse.ArgumentParser();p.add_argument('--directory',required=True);p.add_argument('--liner',required=True);args=p.parse_args()
    base=Path(args.directory).resolve();base.mkdir(mode=0o700,parents=True,exist_ok=False);liner=Path(args.liner).resolve()
    sys.path.insert(0,str(liner/'tests'));from test_board import Server
    from test_telnet import Client as Telnet
    results={};servers=[];clients=[];master=None
    def start_bbs(label,config):
        home=base/label;home.mkdir(mode=0o700);cfg=home/'node.json';save(cfg,config)
        wrapper=home/'starroute-door'
        wrapper.write_text('#!'+sys.executable+'\nimport sys\nsys.path.insert(0,'+repr(str(ROOT))+')\nfrom starroute_bbs.door import main\nsys.argv=["door","--config",'+repr(str(cfg))+']\nraise SystemExit(main())\n')
        wrapper.chmod(0o700);doors=home/'doors.conf';doors.write_text(f'1|0|600|{wrapper}|{home}|StarRoute Traders\n')
        server=Server(str(liner/'runtime'),home/'board',members=home/'members',options=['--doors',str(doors)],menu=True,telnet=True,language='en',menu_dir=liner/'menus',bind='127.0.0.1');servers.append(server)
        client=Telnet(server.port);clients.append(client);client.until()
        password=uuid.uuid4().hex
        client.send(('REGISTER pilot\r\n'+password+'\r\n').encode());logged=client.until();assert b'Logged in as pilot' in logged,logged
        client.send(b'\xff\xfa\x1f\x00\x50\x00\x18\xff\xf0')
        reply=client.cmd('DOOR 1',b'SRT>');assert b'STARROUTE' in reply,reply
        print('TELNET LOGIN / DOOR '+label,flush=True)
        return client,home
    def command(client,line):
        output=client.cmd(line,b'SRT>');print('DOOR> '+line+'\n'+output.decode('utf8','replace'),flush=True)
        assert b'SERVER_ERROR' not in output and b'INVALID_REQUEST' not in output,output
        return output
    def profile(db,key,bbs,name,directory):
        r=SQLiteRepository(db)
        try:value=sec.provision(r,key,bbs,name,int(time.time()))
        finally:r.close()
        path=directory/(bbs+'.json');save(path,value);return str(path)
    try:
        local,key=setup_world(base/'local-world','phase3-complete-demo');localprofile=profile(local,key,'standalone','Standalone',base)
        a,home=start_bbs('local-bbs',{'mode':'standalone','database':str(local),'reference_key':str(base/'local-world/reference.key'),'profile':localprofile,'language':'ja','ansi':True})
        command(a,'map');command(a,'status');command(a,'language en');command(a,'names on');command(a,'color off')
        r=SQLiteRepository(local)
        try:
            pid=r.resolve_account('standalone','1');world=r._load();player=world.players[pid]
            route=min((row for row in world.routes.values() if row['is_open'] and player.planet_id in (row['from'],row['to'])),key=lambda x:x['distance'])
            dest=route['to'] if route['from']==player.planet_id else route['from'];good=next(g for g in r.catalog.goods if world.markets[player.planet_id,g].stock)
        finally:r.close()
        command(a,'buy '+good+' 1');command(a,'warp '+dest+' fast');command(a,'flight');command(a,'news')
        prohibited=command(a,'buy '+good+' 1');assert b'IN_TRANSIT' in prohibited
        # Real wall-clock arrival, no teleports or hidden state edits.
        while True:
            r=SQLiteRepository(local)
            try:arrival=r._load().players[pid].arrival_at
            finally:r.close()
            if arrival is None or int(time.time())>=arrival:break
            print('WAITING FOR REAL ARRIVAL: '+str(arrival-int(time.time()))+' seconds',flush=True);time.sleep(min(10,max(1,arrival-int(time.time()))))
        command(a,'status');command(a,'sell '+good+' 1')
        # Negotiate a new size while the Door owns the PTY; isolated Liner patch propagates it.
        a.send(b'\xff\xfa\x1f\x00\x64\x00\x1e\xff\xf0');resized=command(a,'map')
        maplines=[line for line in resized.splitlines() if len(line)==100];assert len(maplines)>=10,'NAWS resize not reflected'
        returned=a.cmd('quit');assert b'Back to BBS' in returned;assert b'PONG' in a.cmd('PING')
        a.cmd('DOOR 1',b'SRT>');reopened=command(a,'score');assert b'trade' in reopened.lower() or b'profit' in reopened.lower()
        a.cmd('quit');results['A']={'telnet':True,'trade_travel_return_resume':True,'naws_resize':True,'languages':['ja','en']}
        # B: two actual independent BBS servers, one TLS master.
        database,signing=setup_world(base/'shared-world','phase3-complete-demo',open_routes=1);cert,tlskey=certificate(base)
        master=TLSServer(('127.0.0.1',0),Gateway(database,signing),cert,tlskey,requests_per_minute=1000)
        thread=threading.Thread(target=master.serve_forever,daemon=True);thread.start()
        configs=[];bbs=[]
        for site in ('bbs_a','bbs_b'):
            cfg={'mode':'inter-bbs','url':f'https://127.0.0.1:{master.server_port}','profile':profile(database,signing,site,site,base),
                 'ca_file':cert,'state_directory':str(base/(site+'-state')),'language':'en','ansi':True}
            configs.append(cfg);client,_=start_bbs(site,cfg);bbs.append(client)
        x,y=bbs
        probes=[Client(cfg,'1','pilot') for cfg in configs]
        for probe in probes:probe.connect()
        good=next(row['goods_id'] for row in probes[0].call('market')['entries'] if row['stock']>=2)
        before=next(row['stock'] for row in probes[1].call('market')['entries'] if row['goods_id']==good)
        command(x,'buy '+good+' 1');after=next(row['stock'] for row in probes[1].call('market')['entries'] if row['goods_id']==good);assert before-after==1
        command(y,'market');who=command(x,'WHO');assert b'bbs_a' in who and b'bbs_b' in who
        r=SQLiteRepository(database)
        try:
            world=r._load();pid=r.resolve_account('bbs_a','1');planet=world.players[pid].planet_id
            industry=next(i for i,level in r.catalog.development_planets[planet]['private_caps'].items() if world.developments[planet,i]<level)
            cost=r.catalog.development['credits_per_unit'][industry]
        finally:r.close()
        command(x,f'invest {industry} {cost}');command(y,'development')
        assert probes[0].call('development')==probes[1].call('development')
        r=SQLiteRepository(database)
        try:
            world=r._load();closed=next((rid,row) for rid,row in world.routes.items() if not row['is_open'] and planet in (row['from'],row['to']))
            route_id,route=closed;needed=route['distance']*r.catalog.phase3['route_cost_per_distance']
        finally:r.close()
        command(x,f'donate {route_id} {needed//2}');command(y,f'donate {route_id} {needed-needed//2}')
        repeated=command(x,f'donate {route_id} 1');assert b'ROUTE_ALREADY_OPEN' in repeated
        assert probes[0].call('routes')==probes[1].call('routes')
        command(y,'news');command(y,'rankings');command(y,'hall')
        # Confirm clean logout and restart; raw disconnect expires sessions, not player assets.
        before=probes[0].call('status');x.close();clients.remove(x)
        time.sleep(.2);assert probes[0].call('status')==before
        y.cmd('quit');results['B']={'bbs_servers':2,'shared_market':True,'shared_development':True,'shared_route_jackpot_once':True,'who':True,'disconnect_preserves_assets':True}
        for probe in probes:probe.logout()
        r=SQLiteRepository(database)
        try:results['integrity']=r.connection.execute('PRAGMA integrity_check').fetchone()[0];assert not r.connection.execute('PRAGMA foreign_key_check').fetchall()
        finally:r.close()
        assert results['integrity']=='ok';save(base/'result.json',results);print(json.dumps(results),flush=True)
    finally:
        for client in clients:
            try:client.close()
            except OSError:pass
        for server in servers:server.close()
        if master:master.shutdown();master.server_close()


if __name__=='__main__':main()
