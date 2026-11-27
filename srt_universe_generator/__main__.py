"""External offline package generator. No server or database access."""
import argparse
import json
import os
import sys
from starroute.catalog import Catalog
from starroute.settings import read_json
from starroute.model import GameError
from starroute.universe_package import export_package
from .levels import generate


def main(argv=None):
    p=argparse.ArgumentParser(description='Offline universe package generator; never registers or activates a world.')
    for name in ('template','parameters','levels','output'):p.add_argument('--'+name,required=True)
    seed = p.add_mutually_exclusive_group(required=True)
    seed.add_argument('--seed', help='Public test seed')
    seed.add_argument('--seed-stdin', action='store_true', help='Read a private seed from standard input')
    p.add_argument('--created-at')
    args=p.parse_args(argv)
    try:
        value = sys.stdin.readline(4097).rstrip('\r\n') if args.seed_stdin else args.seed
        if args.seed_stdin and (not value or len(value) > 4096):
            raise ValueError('invalid seed')
        data=generate(Catalog.load(args.template).data,read_json(args.parameters,'INVALID_CONFIG'),read_json(args.levels,'INVALID_CONFIG'),value)
        package=export_package(data,args.created_at)
        encoded=(json.dumps(package,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
        fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(encoded)
        print(json.dumps({'state':'generated','output':args.output,'universe_id':package['metadata']['universe_id'],
            'schema_version':package['schema_version'],'sha256':package['integrity']['sha256'],'authenticity':'not_verified'},indent=2))
        return 0
    except (GameError,ValueError,TypeError,KeyError,OSError):
        print('Universe package generation failed; no existing file was overwritten.',file=sys.stderr)
        return 1


if __name__=='__main__':raise SystemExit(main())
