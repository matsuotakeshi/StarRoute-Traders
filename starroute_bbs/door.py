"""Liner notes native PTY Door. Identity comes ONLY from BBS-owned environment."""
import argparse,os,sys
from .node import door_config
from .client import Client,ClientError
from .terminal import Terminal


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);args=p.parse_args()
    user=os.environ.get('LINER_USER_ID','');name=os.environ.get('LINER_USER','')
    if not user.isascii() or not user.isdigit() or int(user)<=0 or not name:
        print('Authenticated Liner notes Door environment required.');return 1
    try:
        cfg = door_config(args.config)
    except ClientError:
        print('サイト切り替え中です。 Site transition pending. Please try again later.')
        return 1
    if cfg['mode']=='standalone':
        from starroute.local_door import LocalDoor
        backend=LocalDoor(cfg,user,name)
    elif cfg['mode']=='inter-bbs':backend=Client(cfg,user,name)
    else:raise ValueError('mode')
    ui=Terminal(backend,cfg.get('language','ja'),cfg.get('ansi',True),os.environ.get('COLUMNS','80'),os.environ.get('LINES','24'))
    try:backend.connect();ui.language=backend.language()
    except ClientError as e:ui.emit(ui.text('error')+': '+e.code)
    ui.run(sys.stdin);return 0


if __name__=='__main__':raise SystemExit(main())
