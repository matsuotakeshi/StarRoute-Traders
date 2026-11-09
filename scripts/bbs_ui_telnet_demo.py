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
        print('MENU '+line+' -> '+('OK' if 'Traceback' not in plain else 'FAIL'),flush=True)
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
        db,key=setup_world(base/'local','phase3-complete-demo',open_routes=1,template=a.template)
        cfg={'mode':'standalone','database':str(db),'reference_key':str(base/'local/reference.key'),'profile':profile(db,key,'standalone'),'language':'ja','ansi':True}
        c=start('standalone',cfg)
        drain(c);c.send(b'menu');raw=c.until(b'\x1b[KMENU');assert b'\x1b[KMENU' in raw
        c.send(b'\n');c.until(b'Select > ')
        command(c,'l','language-bilingual');command(c,'0')
        results['uppercase_live_echo']=True
        main=command(c,'m','main-ja');assert '1 ステータス' in main and '|' in main
        market=command(c,'2','market-ja');assert '星穀' in market
        command(c,'1');command(c,'0');command(c,'m');command(c,'3');command(c,'1');command(c,'1')
        before=state(db,'standalone');command(c,'','confirm-empty');assert state(db,'standalone').cash==before.cash
        confirm(c);assert state(db,'standalone').cargo
        command(c,'m');command(c,'5','routes');command(c,'m');command(c,'l');command(c,'2');command(c,'t','names-en')
        r=SQLiteRepository(db)
        try:
            world=r._load();pid=r.resolve_account('standalone','1');planet=world.players[pid].planet_id
            industries=('primary','secondary','tertiary','quaternary')
            industry=next(i for i in industries if world.developments[planet,i]<r.catalog.development_planets[planet]['private_caps'][i])
            cost=r.catalog.development['credits_per_unit'][industry];old_level=world.developments[planet,industry]
        finally:r.close()
        command(c,'8');command(c,str(industries.index(industry)+1));command(c,str(cost));confirm(c);command(c,'m')
        r=SQLiteRepository(db)
        try:assert r._load().developments[planet,industry]>old_level
        finally:r.close()
        cash=state(db,'standalone').cash
        command(c,'9');command(c,'1');command(c,'10');confirm(c);command(c,'m');assert state(db,'standalone').cash==cash-10
        for action in ('w','r','h'):
            command(c,action)
            if action in ('r','h'):command(c,'1')
            command(c,'m')
        command(c,'7');command(c,'1');command(c,'1','warp-confirm');confirm(c)
        flight=command(c,'m','flight');assert 'IN FLIGHT' in flight and 'ETA' in flight
        command(c,'n','flight-news');command(c,'m');command(c,'w','flight-who');command(c,'m')
        restricted=command(c,'3','flight-rejected');assert 'Unavailable in flight' in restricted
        # Leave and re-enter the Door while travelling; the server state is preserved.
        c.send(b'q\n');assert b'Back to BBS' in c.until();assert b'PONG' in c.cmd('PING')
        c.cmd('DOOR 1',b'Select > ');assert state(db,'standalone').destination_id
        while state(db,'standalone').arrival_at and time.time()<state(db,'standalone').arrival_at:
            print('WAIT actual arrival',flush=True);time.sleep(5)
        command(c,'m','arrived');command(c,'4');command(c,'1');command(c,'1');confirm(c);assert not state(db,'standalone').cargo;command(c,'m')
        for cols,rows in ((100,30),(70,24),(50,24),(80,24)):
            drain(c);c.send(bytes([255,250,31,0,cols,0,rows,255,240]));raw=c.until(b'Select > ');capture(raw,f'naws-{cols}',cols,rows)
        command(c,'?','help');command(c,'m');command(c,'buy grain 1');confirm(c)
        command(c,'m');mono=command(c,'color off');assert '\x1b' not in mono
        c.send(b'q\n');assert b'Back to BBS' in c.until();assert b'PONG' in c.cmd('PING')
        # Control-] returns to the BBS through its existing Door adapter.
        c.cmd('DOOR 1',b'Select > ');drain(c);c.send(b'\x1d');assert b'Back to BBS' in c.until();assert b'PONG' in c.cmd('PING')
        results['standalone']={'menu_trade_travel_invest_donate':True,'ja_en':True,'naws':[80,100,70,50],'flight_who':True,'return_and_resume':True,'control_bracket':True,'ansi_mono':True}
        shared,sign=setup_world(base/'shared','phase3-complete-demo',template=a.template);cert,tlskey=certificate(base)
        master=TLSServer(('127.0.0.1',0),Gateway(shared,sign),cert,tlskey,requests_per_minute=1000)
        threading.Thread(target=master.serve_forever,daemon=True).start()
        remote={'mode':'inter-bbs','url':f'https://127.0.0.1:{master.server_port}','profile':profile(shared,sign,'remote'),'ca_file':cert,'state_directory':str(base/'client-state'),'language':'en','ansi':True}
        d=start('inter-bbs',remote);command(d,'3');command(d,'1');command(d,'1');confirm(d);assert state(shared,'remote').cargo
        command(d,'m','remote-main');command(d,'w','remote-who');d.send(b'q\n');assert b'Back to BBS' in d.until()
        results['inter_bbs']={'tls_menu_purchase':True,'who':True,'bbs_return':True}
        for path in (db,shared):
            r=SQLiteRepository(path)
            try:assert r.connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok';assert not r.connection.execute('PRAGMA foreign_key_check').fetchall()
            finally:r.close()
        results['integrity']='ok';save(base/'result.json',results);print(json.dumps(results),flush=True)
    finally:
        for c in clients:
            try:c.close()
            except OSError:pass
        for server in servers:server.close()
        if master:master.shutdown();master.server_close()

if __name__=='__main__':main()
