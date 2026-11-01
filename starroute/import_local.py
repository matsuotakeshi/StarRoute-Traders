"""Explicit local NEW-game initialization. Never replaces an existing database."""
import argparse
import os
from pathlib import Path
from .settings import read_json
from .universe_package import to_catalog
from .repository import SQLiteRepository
from .clock import SystemClock
from .model import GameError


def initialize(package_path,db_path,now=None):
    if Path(package_path).stat().st_size>32*1024*1024:raise ValueError('package too large')
    catalog=to_catalog(read_json(package_path,'INVALID_CONFIG'))
    # Reserve exclusively only AFTER validation; no in-place replacement is offered.
    fd=os.open(db_path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    r=SQLiteRepository(db_path,catalog,now=SystemClock().now() if now is None else now)
    try:
        return {'universe_id':catalog.data['universe']['universe_id'],'state':'local_game_initialized',
                'authenticity':'not_verified','db':str(db_path)}
    finally:r.close()


def main():
    import json
    p=argparse.ArgumentParser(description='Initialize a new local game from a private universe package')
    p.add_argument('--package',required=True);p.add_argument('--db',required=True);args=p.parse_args()
    try:print(json.dumps(initialize(args.package,args.db)));return 0
    except (OSError,ValueError,GameError):print('LOCAL_IMPORT_REJECTED');return 1


if __name__=='__main__':raise SystemExit(main())
