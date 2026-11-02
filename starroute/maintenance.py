"""Explicit offline operations. Package scripts never call these commands."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

from .repository import SCHEMA_VERSION, SQLiteRepository
from .engine import Engine


def inspect(path, maximum=SCHEMA_VERSION, allowed_rules=None):
    p=Path(path).resolve(strict=True)
    c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)
    try:
        version=int(c.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0])
        if not 1<=version<=maximum:raise ValueError('unsupported schema')
        if c.execute('PRAGMA integrity_check').fetchall()!=[('ok',)] or c.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('database integrity')
        from .catalog import Catalog
        from .rules import fingerprint
        catalog=Catalog(json.loads(c.execute("SELECT value FROM metadata WHERE key='catalog'").fetchone()[0]))
        rules=fingerprint(catalog)['rules_version']
        if allowed_rules is not None and rules not in allowed_rules:raise ValueError('unsupported rules')
        return {'schema':version,'supported_max':maximum,'rules_version':rules,'integrity':'ok'}
    finally:c.close()


def backup(source,destination):
    inspect(source)
    destination=Path(destination)
    fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    c=sqlite3.connect(Path(source).resolve(strict=True).as_uri()+'?mode=ro',uri=True)
    out=sqlite3.connect(destination)
    try:c.backup(out)
    finally:out.close();c.close()
    return inspect(destination)


def migrate_copy(source,destination,backup_path,failpoint=None):
    """An operator activates the validated copy separately, with writers stopped."""
    failpoint=failpoint or (lambda step:None)
    before=backup(source,backup_path)
    destination=Path(destination)
    if destination.exists():raise FileExistsError(destination)
    stage=destination.with_name(destination.name+'.pending-'+uuid.uuid4().hex)
    audit=destination.with_name(destination.name+'.migration.json')
    if audit.exists():raise FileExistsError(audit)
    result={'before':before,'backup':str(backup_path),'state':'failed','started_at':int(time.time())}
    try:
        backup(backup_path,stage);failpoint('before_migration')
        r=SQLiteRepository(stage)
        try:r.connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        finally:r.close()
        failpoint('after_migration');result['after']=inspect(stage)
        # Exclusive publication; never replace a live destination.
        if os.name=='nt':os.rename(stage,destination)  # Windows rename refuses existing targets.
        else:os.link(stage,destination);stage.unlink()
        result.update(state='validated_copy',sha256=hashlib.sha256(destination.read_bytes()).hexdigest())
        return result
    finally:
        result['finished_at']=int(time.time())
        fd=os.open(audit,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w',encoding='utf8') as f:json.dump(result,f,indent=2);f.flush();os.fsync(f.fileno())


def advance(repo,now,guard=None,max_batches=100):
    """Lazy wall-clock recovery, serialized with trades and round transitions."""
    engine=Engine(repo.catalog)
    for _ in range(max_batches):
        with repo.transaction() as world:
            if guard:guard(world)
            row=repo.connection.execute('SELECT state,ends_at FROM p4_rounds WHERE round_id=?',(world.season_id,)).fetchone()
            if row and row['state']!='ACTIVE':return {'state':'round_inactive','game_time':world.game_time}
            target=min(now,row['ends_at']) if row else now
            before=world.game_time
            engine.update(world,target,partial=True)
            current=world.game_time
        if current>=target:return {'state':'current','game_time':current}
        if current<=before:raise ValueError('clock recovery made no progress')
    return {'state':'catchup_pending','game_time':current}


def main(argv=None):
    p=argparse.ArgumentParser(description='Explicit check, backup, migration-copy and time recovery; never activates a DB')
    p.add_argument('--db',required=True)
    sub=p.add_subparsers(dest='command',required=True)
    check=sub.add_parser('check');check.add_argument('--supported-max-schema',type=int,default=SCHEMA_VERSION);check.add_argument('--supported-rules-version',action='append')
    b=sub.add_parser('backup');b.add_argument('--output',required=True)
    m=sub.add_parser('migrate-copy');m.add_argument('--output',required=True);m.add_argument('--backup',required=True)
    t=sub.add_parser('tick')
    args=p.parse_args(argv)
    try:
        if args.command=='check':result=inspect(args.db,args.supported_max_schema,args.supported_rules_version)
        elif args.command=='backup':result=backup(args.db,args.output)
        elif args.command=='migrate-copy':result=migrate_copy(args.db,args.output,args.backup)
        else:
            inspect(args.db);r=SQLiteRepository(args.db)
            try:result=advance(r,int(time.time()))
            finally:r.close()
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except Exception as e:
        print(json.dumps({'state':'failed','error':type(e).__name__}));return 1


if __name__=='__main__':raise SystemExit(main())
