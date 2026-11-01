"""Separate read-only import preflight. Registration/activation belong to Phase 4."""
import argparse
import json
import os
from pathlib import Path
from datetime import datetime,timezone
from .settings import read_json
from .model import GameError
from .universe_package import to_catalog


def inspect(path):
    result={'checked_at':datetime.now(timezone.utc).isoformat(),'state':'rejected',
            'registered':False,'activated':False,'authenticity':'not_verified'}
    try:
        if Path(path).stat().st_size>32*1024*1024:raise ValueError('package size')
        package=read_json(path,'INVALID_CONFIG');catalog=to_catalog(package)
        result.update(state='validated',integrity='valid',schema_version=package['schema_version'],
                      universe_id=package['metadata']['universe_id'],universe_data_version=package['metadata']['universe_data_version'],
                      planet_count=len(catalog.planets),industry_pairs=192)
    except (GameError,ValueError,TypeError,KeyError,OSError):
        result['error']='INVALID_UNIVERSE_PACKAGE'
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description='Validate a private universe package without registering, activating or modifying a game database.')
    p.add_argument('--input',required=True);p.add_argument('--report')
    args=p.parse_args(argv);result=inspect(args.input)
    encoded=(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    if args.report:
        try:
            fd=os.open(args.report,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as stream:stream.write(encoded)
        except OSError:
            print('Validation report could not be created; existing files were not changed.')
            return 1
    print(encoded.decode('utf-8'),end='')
    return 0 if result['state']=='validated' else 1


if __name__=='__main__':raise SystemExit(main())
