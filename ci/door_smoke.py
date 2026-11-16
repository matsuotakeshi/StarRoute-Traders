"""Short real Telnet/PTY Door lifecycle check, without a trading/flight scenario."""
import argparse,json,os,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from phase5_telnet_demo import setup_world
from starroute.repository import SQLiteRepository
from starroute import network_security as security
from starroute_bbs.client import save

def main():
    p=argparse.ArgumentParser();p.add_argument('--directory',required=True);p.add_argument('--liner',required=True);a=p.parse_args()
    base=Path(a.directory).resolve();base.mkdir(mode=0o700,parents=True,exist_ok=False)
    liner=Path(a.liner).resolve();sys.path.insert(0,str(liner/'tests'))
    from test_board import Server
    from test_telnet import Client
    db,key=setup_world(base/'world','os-door-smoke')
    repo=SQLiteRepository(db)
    try:profile=security.provision(repo,key,'smoke','Smoke',int(time.time()))
    finally:repo.close()
    save(base/'profile.json',profile)
    save(base/'door.json',dict(mode='standalone',database=str(db),reference_key=str(base/'world/reference.key'),profile=str(base/'profile.json'),language='en',ansi=True))
    wrapper=base/'door';wrapper.write_text('#!'+sys.executable+'\nimport sys\nsys.path.insert(0,'+repr(str(ROOT))+')\nfrom starroute_bbs.door import main\nsys.argv=["door","--config",'+repr(str(base/'door.json'))+']\nraise SystemExit(main())\n');wrapper.chmod(0o700)
    doors=base/'doors.conf';doors.write_text(f'1|0|180|{wrapper}|{base}|StarRoute Traders\n')
    server=Server(str(liner/'runtime'),base/'board',members=base/'members',options=['--doors',str(doors)],menu=True,telnet=True,language='en',menu_dir=liner/'menus',bind='127.0.0.1')
    client=None
    try:
        client=Client(server.port);client.until()
        client.send(('REGISTER pilot\r\n'+uuid.uuid4().hex+'\r\n').encode());assert b'Logged in as pilot' in client.until()
        client.send(bytes([255,250,31,0,80,0,24,255,240]))
        assert b'STARROUTE' in client.cmd('DOOR 1',b'Select > ')
        client.send(bytes([255,250,31,0,70,0,24,255,240]));client.until(b'Select > ')
        client.send(b'q\n');assert b'Back to BBS' in client.until();assert b'PONG' in client.cmd('PING')
        client.cmd('DOOR 1',b'Select > ');client.send(b'\x1d');assert b'Back to BBS' in client.until()
        assert b'PONG' in client.cmd('PING')
        save(base/'result.json',dict(telnet_pty=True,naws=[80,70],quit_and_control_bracket=True,bbs_return=True,scope='OS compatibility only'))
        print('Door compatibility: PASS')
    finally:
        if client:client.close()
        server.close()
if __name__=='__main__':main()
