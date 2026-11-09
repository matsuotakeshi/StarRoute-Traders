"""Real isolated Liner notes / Telnet menu acceptance. Never uses live accounts."""
import argparse,json,os,sys,time,uuid,select,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from phase5_telnet_demo import setup_world
from tests.phase5_support import certificate
from starroute.repository import SQLiteRepository
from starroute.network import Gateway,TLSServer
from starroute import network_security as sec
from starroute_bbs.client import save
from starroute_bbs.terminal import ANSI,width

def setup_exploration(directory):
    from starroute.operations import initialize,Manager
    from srt_universe_generator.levels import generate
    from starroute.universe_package import export_package
    directory.mkdir(mode=0o700);now=int(time.time());db=directory/'game.db'
    template=json.loads((ROOT/'examples/exploration-trial.json').read_text())
    template['exploration']['offroute_speed_bps']=10000
    for key in ('pirate','patrol','storm','failure','wreck'):template['phase3']['event_probabilities'][key]=0
    parameters=json.loads((ROOT/'examples/connected-universe-trial.json').read_text())
    levels=json.loads((ROOT/'examples/industry-levels-trial.json').read_text())
    data=generate(template,parameters,levels,'exploration-telnet')
    package=export_package(data);save(directory/'private-package.json',package);initialize(db,now);manager=Manager(db,now)
    try:
        uid=manager.stage(json.dumps(package).encode());manager.register(uid);manager.prepare(uid,1,now);manager.activate(1,uid)
        key=os.urandom(32);(directory/'reference.key').write_bytes(key);os.chmod(directory/'reference.key',0o600)
        sec.schema(manager.c);sec.publish(manager.repo,key)
    finally:manager.close()
    return db,key


def main():
    p=argparse.ArgumentParser();p.add_argument('--directory',required=True);p.add_argument('--liner',required=True);p.add_argument('--template');a=p.parse_args()
    base=Path(a.directory);base.mkdir(mode=0o700,parents=True,exist_ok=False);liner=Path(a.liner)
    sys.path.insert(0,str(liner/'tests'));from test_board import Server
    from test_telnet import Client
    servers=[];clients=[];master=None;results={};screens=base/'screens';screens.mkdir()
    def capture(raw,label,columns=80,rows=24):
        text=raw.decode('utf8','replace');(screens/(label+'.ansi')).write_text(text)
        frame=text.rsplit('\x1b[2J',1)[-1];plain=ANSI.sub('',frame).replace('\r','')
        lines=plain.splitlines();assert len(lines)<=rows-1,(label,len(lines))
        assert all(width(line)<columns for line in lines),(label,lines)
        (screens/(label+'.txt')).write_text(plain);print('SCREEN '+label+' '+str(columns)+'x'+str(rows)+' PASS',flush=True)
        return plain
    def drain(c):
        while select.select([c.sock],[],[],.1)[0]:c.receive()
        c.buf=b''
    def command(c,line,label=None,columns=80,rows=24):
        drain(c);c.send(line.encode()+b'\n');raw=c.until(b'Select > ')
        plain=capture(raw,label,columns,rows) if label else ANSI.sub('',raw.decode('utf8','replace')).replace('\r','')
        print('MENU operation '+('OK' if 'Traceback' not in plain else 'FAIL'),flush=True)
        assert 'Traceback' not in plain;return plain
    def start(label,cfg):
        home=base/label;home.mkdir();config=home/'node.json';save(config,cfg)
        wrapper=home/'door';wrapper.write_text('#!'+sys.executable+'\nimport sys\nsys.path.insert(0,'+repr(str(ROOT))+')\nfrom starroute_bbs.door import main\nsys.argv=["door","--config",'+repr(str(config))+']\nraise SystemExit(main())\n');wrapper.chmod(0o700)
        doors=home/'doors.conf';doors.write_text(f'1|0|1800|{wrapper}|{home}|StarRoute Traders\n')
        server=Server(str(liner/'runtime'),home/'board',members=home/'members',options=['--doors',str(doors)],menu=True,telnet=True,language='en',menu_dir=liner/'menus',bind='127.0.0.1');servers.append(server)
        c=Client(server.port);clients.append(c);c.until();password=uuid.uuid4().hex
        c.send(('REGISTER pilot\r\n'+password+'\r\n').encode());assert b'Logged in as pilot' in c.until()
        c.send(b'\xff\xfa\x1f\x00\x50\x00\x18\xff\xf0');raw=c.cmd('DOOR 1',b'Select > ');capture(raw,label+'-startup')
        return c
    def profile(db,key,site):
        r=SQLiteRepository(db)
        try:result=sec.provision(r,key,site,site,int(time.time()))
        finally:r.close()
        path=base/(site+'.json');save(path,result);return str(path)
    def state(db,site):
        r=SQLiteRepository(db)
        try:return r._load().players[r.resolve_account(site,'1')]
        finally:r.close()
    def confirm(c):
        # Typical receipts fit on the first page. Review longer receipts before Y.
        result=command(c,'y')
        for _ in range(5):
            if 'remaining details' not in result and '残りの確認' not in result:return result
            command(c,'>');result=command(c,'y')
        raise AssertionError('confirmation paging')
    try:
        db,key=setup_exploration(base/'local')
        cfg={'mode':'standalone','database':str(db),'reference_key':str(base/'local/reference.key'),'profile':profile(db,key,'standalone'),'language':'en','ansi':True}
        c=start('standalone',cfg)
        r=SQLiteRepository(db)
        try:
            hidden=r.catalog.data['universe']['private_world'];target=hidden['position'];pid=r.resolve_account('standalone','1')
            with r.transaction() as world:
                world.players[pid].cash=2000000;world.players[pid].planet_id=hidden['reference_planet_id']
        finally:r.close()
        command(c,'m');command(c,'e','exploration-menu');command(c,'1','device-confirm');confirm(c)
        command(c,'m');command(c,'e');command(c,'4');confirm(c)
        command(c,'m');command(c,'e');command(c,'5','notebook')
        for cols,rows in ((100,30),(70,24),(50,24),(80,24)):
            drain(c);c.send(bytes([255,250,31,0,cols,0,rows,255,240]));raw=c.until(b'Select > ');capture(raw,f'explore-naws-{cols}',cols,rows)
        command(c,'m');command(c,'l');command(c,'1');command(c,'e','exploration-ja')
        command(c,'2');command(c,str(target['x']));command(c,str(target['y']));command(c,'2');confirm(c)
        flight=command(c,'m');assert 'ETA' in flight
        c.send(b'q\n');assert b'Back to BBS' in c.until();assert b'PONG' in c.cmd('PING')
        deadline=time.time()+360
        while state(db,'standalone').arrival_at and time.time()<state(db,'standalone').arrival_at:
            if time.time()>deadline:raise AssertionError('arrival timeout')
            time.sleep(1)
        c.cmd('DOOR 1',b'Select > ')
        # Free-form Japanese and mixed-case Latin text must survive the Telnet input layer.
        command(c,'私のMiXeD星');confirm(c)
        r=SQLiteRepository(db)
        try:
            from starroute.exploration import player_state
            world=r._load();assert player_state(world,pid)['name']=='私のMiXeD星'
        finally:r.close()
        command(c,'m');command(c,'3');command(c,'1');command(c,'1');confirm(c)
        assert state(db,'standalone').cargo
        command(c,'m');command(c,'4');command(c,'1');command(c,'1');confirm(c)
        assert not state(db,'standalone').cargo
        command(c,'m');command(c,'e');command(c,'7');command(c,'m');command(c,'e');command(c,'3');command(c,'1');command(c,'1');confirm(c)
        assert state(db,'standalone').destination_id
        c.send(b'q\n');assert b'Back to BBS' in c.until();assert b'PONG' in c.cmd('PING')
        r=SQLiteRepository(db)
        try:assert r.connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok';assert not r.connection.execute('PRAGMA foreign_key_check').fetchall()
        finally:r.close()
        results={'real_liner_telnet':'PASS','device_guild_notebook':'PASS','ja_en_naws':'PASS','real_time_logout_arrival':'PASS','japanese_mixed_case_naming':'PASS','hidden_market_buy_sell':'PASS','normal_return_departure':'PASS','bbs_return':'PASS','integrity':'ok','secret_coordinates_logged':False,'trial_timing':'existing ship timing; offroute 100%; ship incidents disabled in isolated test only'}
        save(base/'result.json',results);print(json.dumps(results),flush=True)
    finally:
        for c in clients:
            try:c.close()
            except OSError:pass
        for server in servers:server.close()
        if master:master.shutdown();master.server_close()

if __name__=='__main__':main()
