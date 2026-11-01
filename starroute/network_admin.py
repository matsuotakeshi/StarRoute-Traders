"""Offline administrator provisioning; no credentials on stdout."""
import argparse,json,os,secrets
from pathlib import Path
from .operations import Manager
from . import network_security as sec
from .clock import SystemClock


def private_json(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf8') as f:json.dump(value,f,ensure_ascii=False,indent=2)


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--reference-key',required=True)
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('init');sub.add_parser('publish');sub.add_parser('sites');sub.add_parser('audit')
    for name in ('add','rotate','approve','disable'):
        s=sub.add_parser(name);s.add_argument('--bbs-id',required=True)
        if name=='add':s.add_argument('--name',required=True)
        if name in ('add','rotate','approve'):s.add_argument('--output',required=True)
        if name=='approve':s.add_argument('--configuration')
    args=p.parse_args(argv);now=SystemClock().now();m=Manager(args.db,now)
    try:
        if args.command=='init':
            m.backup('network-init')
            fd=os.open(args.reference_key,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as f:f.write(secrets.token_bytes(32))
            with m.atomic():sec.schema(m.c);sec.publish(m.repo,Path(args.reference_key).read_bytes())
        else:
            key=Path(args.reference_key).read_bytes()
            if len(key)<32:raise ValueError('reference key')
            if args.command=='publish':
                with m.atomic():sec.publish(m.repo,key);sec.audit(m.c,now,None,None,'publish_reference','OK')
            elif args.command=='sites':
                print(json.dumps([dict(r) for r in m.c.execute('SELECT bbs_id,name,state,verified_at FROM p5_sites')]));return 0
            elif args.command=='audit':
                print(json.dumps([dict(r) for r in m.c.execute('SELECT * FROM p5_audit ORDER BY sequence')],ensure_ascii=False));return 0
            else:
                if args.command!='disable' and Path(args.output).exists():raise FileExistsError('output exists')
                with m.atomic():
                    if args.command=='add':profile=sec.provision(m.repo,key,args.bbs_id,args.name,now)
                    else:
                        row=m.c.execute('SELECT * FROM p5_sites WHERE bbs_id=?',(args.bbs_id,)).fetchone()
                        if not row:raise ValueError('site not found')
                        m.c.execute('DELETE FROM p5_sessions WHERE bbs_id=?',(args.bbs_id,))
                        if args.command=='disable':m.c.execute("UPDATE p5_sites SET state='DISABLED' WHERE bbs_id=?",(args.bbs_id,))
                        elif args.command=='rotate':
                            token=secrets.token_urlsafe(32);m.c.execute('UPDATE p5_sites SET credential_hash=? WHERE bbs_id=?',(sec.digest(token),args.bbs_id))
                            profile={'bbs_id':args.bbs_id,'credential':token,'attestation':json.loads(row['approved']),'configuration':json.loads(row['approved'])['value']['configuration']}
                        else:
                            claim=json.loads(Path(args.configuration).read_text()) if args.configuration else sec.reference(m.repo,key)
                            if set(claim)!=set(sec.CONFIG_FIELDS):raise ValueError('configuration fields')
                            envelope=sec.seal(key,{'bbs_id':args.bbs_id,'configuration':claim})
                            m.c.execute('UPDATE p5_sites SET approved=?,verified_config=NULL,verified_at=NULL WHERE bbs_id=?',(json.dumps(envelope),args.bbs_id))
                            profile={'bbs_id':args.bbs_id,'attestation':envelope,'configuration':claim}
                        sec.audit(m.c,now,args.bbs_id,None,args.command,'OK')
                    if args.command!='disable':private_json(args.output,profile)
        print(json.dumps({'state':'complete','command':args.command}));return 0
    finally:m.close()


if __name__=='__main__':raise SystemExit(main())
