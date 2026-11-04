"""Measure actual Telnet NAWS -> Liner notes PTY -> StarRoute dimensions.

Only an isolated copy of Liner notes, loopback listener and fresh test user.
"""
import argparse
import json
from pathlib import Path
import sys
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--liner', required=True)
    parser.add_argument('--directory', required=True)
    args = parser.parse_args()
    liner = Path(args.liner).resolve()
    if not (liner / 'STARROUTE_ISOLATED_COPY').is_file():
        raise SystemExit('isolated Liner notes copy marker required')
    base = Path(args.directory).resolve()
    base.mkdir(mode=0o700, parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(liner / 'tests'))
    from test_board import Server
    from test_telnet import Client
    door = base / 'probe-door'
    door.write_text('#!' + sys.executable + '\n' + f'''import os,sys,select,time
sys.path.insert(0,{str(root)!r})
from starroute_bbs.terminal import Terminal
os.environ['COLUMNS']='80'
os.environ['LINES']='24'
ui=Terminal(None)
previous=None
end=time.monotonic()+120
while time.monotonic()<end:
    size=os.get_terminal_size(sys.stdin.fileno())
    ui.resize(sys.stdin)
    current=(size.columns,size.lines,ui.columns,ui.rows)
    if current!=previous:
        print('SIZE='+','.join(map(str,current)),flush=True)
        previous=current
    if select.select([sys.stdin],[],[],0.1)[0]:
        if sys.stdin.readline().strip()=='q':break
''', encoding='utf-8')
    door.chmod(0o700)
    doors = base / 'doors.conf'
    doors.write_text(f'1|0|180|{door}|{base}|NAWS Test\n', encoding='utf-8')
    server = Server(str(liner / 'runtime'), base / 'board', members=base / 'members',
                    options=['--doors', str(doors)], menu=True, telnet=True,
                    language='en', menu_dir=liner / 'menus', bind='127.0.0.1')
    client = None
    records = []
    try:
        client = Client(server.port)
        client.until()
        client.send(('REGISTER resizepilot\r\n' + uuid.uuid4().hex + '\r\n').encode())
        assert b'Logged in as resizepilot' in client.until()
        for i, (columns, rows) in enumerate(((80,24),(100,30),(70,24),(50,24),(80,24))):
            client.send(bytes([255,250,31,0,columns,0,rows,255,240]))
            expected = f'SIZE={columns},{rows},{columns},{rows}'.encode()
            if i == 0:
                raw = client.cmd('DOOR 1', expected)
            else:
                raw = client.until(expected)
            assert expected in raw
            records.append({'naws':[columns,rows], 'pty':[columns,rows], 'starroute':[columns,rows]})
        client.send(b'q\n')
        assert b'Back to BBS' in client.until()
        assert b'PONG' in client.cmd('PING')
        result = {'passed':True,'records':records,'stale_environment_ignored':True,'bbs_return':True}
        (base / 'result.json').write_text(json.dumps(result,indent=2), encoding='utf-8')
        print(json.dumps(result))
    finally:
        if client:
            client.close()
        server.close()


if __name__ == '__main__':
    main()
