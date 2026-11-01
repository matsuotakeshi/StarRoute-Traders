"""Master-administrator-only generation. Never distribute the output to BBS sites.

Existing output files are never overwritten.
"""
import argparse
import json
import os
import sys
from .catalog import Catalog
from .settings import read_json
from .universe import generate,public_info
from .rules import fingerprint
from .model import GameError


def main(argv=None):
    parser=argparse.ArgumentParser(description='Generate and freeze a new 48-planet trial universe; never edits a running DB.')
    parser.add_argument('--template',required=True)
    parser.add_argument('--parameters',required=True)
    parser.add_argument('--seed',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args(argv)
    try:
        data=generate(Catalog.load(args.template).data,read_json(args.parameters,'INVALID_CONFIG'),args.seed)
        encoded=(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
        # Private definitions include hidden caps and the seed; restrictive creation mode.
        fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(encoded)
        catalog=Catalog(data)
        print(json.dumps({'output':args.output,'universe':public_info(catalog),'rules':fingerprint(catalog)},ensure_ascii=False,indent=2))
        return 0
    except (GameError,ValueError,OSError,ImportError) as exc:
        print('Generation failed: '+(exc.code if isinstance(exc,GameError) else str(exc)),file=sys.stderr)
        return 1


if __name__=='__main__':raise SystemExit(main())
