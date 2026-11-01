"""Trusted local administrator CLI. Never runs an API or publishes data."""
import argparse
import json
import sqlite3
from .clock import SystemClock
from .operations import Manager,initialize,restore_copy
from .distribution import read_limited,fetch
from .model import GameError
from .statistics import read_scores,calculate


def main(argv=None):
    p=argparse.ArgumentParser(description='StarRoute universe / round administrator')
    p.add_argument('--db',required=True);p.add_argument('--lang',choices=('ja','en'),default='en')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('init')
    s=sub.add_parser('restore-copy');s.add_argument('--backup',required=True)
    s=sub.add_parser('stage');s.add_argument('--package',required=True)
    s=sub.add_parser('fetch')
    for k in ('repository','commit','package-path','allowed-signers','identity'):s.add_argument('--'+k,required=True)
    for k in ('key','known-hosts'):s.add_argument('--'+k)
    s.add_argument('--local-test',action='store_true')
    for name in ('validate','register','universe'):
        s=sub.add_parser(name);s.add_argument('--universe',required=True)
    s=sub.add_parser('prepare');s.add_argument('--universe',required=True);s.add_argument('--round',type=int,required=True)
    s.add_argument('--start',type=int);s.add_argument('--policy')
    for name in ('activate','finish'):
        s=sub.add_parser(name);s.add_argument('--universe',required=True);s.add_argument('--round',type=int,required=True)
        if name=='activate':s.add_argument('--previous-round',type=int);s.add_argument('--previous-universe')
    for name in ('list','rounds','history','check','hall'):sub.add_parser(name)
    for name in ('rankings','scores','archive-check'):
        s=sub.add_parser(name);s.add_argument('--round',type=int,required=True)
    args=p.parse_args(argv);m=None
    try:
        now=SystemClock().now();cmd=args.command
        if cmd=='init':initialize(args.db,now);result={'state':'initialized'}
        elif cmd=='restore-copy':result=restore_copy(args.backup,args.db)
        else:
            m=Manager(args.db,now)
            if cmd=='stage':result={'universe_id':m.stage(read_limited(args.package))}
            elif cmd=='fetch':
                raw,source=fetch(args.repository,args.commit,args.package_path,allowed_signers=args.allowed_signers,identity=args.identity,key=args.key,known_hosts=args.known_hosts,local_test=args.local_test)
                result={'universe_id':m.stage(raw,source),'source':source}
            elif cmd=='validate':m.validate(args.universe);result={'state':'validated'}
            elif cmd=='register':result={'universe_id':m.register(args.universe)}
            elif cmd=='prepare':result={'round_id':m.prepare(args.universe,args.round,args.start if args.start is not None else now,json.loads(read_limited(args.policy)) if args.policy else None)}
            elif cmd=='activate':m.activate(args.round,args.universe,args.previous_round,args.previous_universe);result={'state':'ACTIVE'}
            elif cmd=='finish':m.finish(args.round,args.universe);result={'state':'CLOSED'}
            elif cmd=='check':result=m.inspect()
            elif cmd=='archive-check':result={'round_id':args.round,'tables':len(m.archive(args.round)['tables']),'integrity':'ok'}
            elif cmd=='universe':result={k:v for k,v in m.item(args.universe).items() if k!='package_json'}
            elif cmd=='list':result=[dict(r) for r in m.c.execute('SELECT universe_id,state,package_hash,source_type,registered_at FROM p4_universes ORDER BY universe_id')]
            elif cmd=='rankings':result=read_scores(m.c,args.round)
            elif cmd=='scores':
                saved=m.c.execute('SELECT stats_json FROM p4_statistics WHERE round_id=?',(args.round,)).fetchall()
                result=[json.loads(r[0]) for r in saved] if saved else list(calculate(m.c,args.round).values())
            else:result=[dict(r) for r in m.c.execute('SELECT * FROM '+{'rounds':'p4_rounds','history':'p4_audit','hall':'p4_hall'}[cmd])]
        print(json.dumps({'message':'完了' if args.lang=='ja' else 'Completed','result':result},ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error,GameError) as e:
        # No transport stderr, credentials or private package values in errors.
        print(json.dumps({'error':'管理操作を拒否しました' if args.lang=='ja' else 'Administrative operation rejected','type':type(e).__name__}));return 1
    finally:
        if m:m.close()


if __name__=='__main__':raise SystemExit(main())
