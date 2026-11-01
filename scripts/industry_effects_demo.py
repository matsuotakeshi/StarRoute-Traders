"""ECON-05 CLI acceptance with a deterministic clock and saved period state."""
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from starroute.catalog import Catalog
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.adapters.cli import CLI

root=Path(__file__).resolve().parents[1]
for lang in ('ja','en'):
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'world.db';clock=ManualClock(100)
        r=SQLiteRepository(path,Catalog.load(root/'examples/industry-effects-trial.json'),now=100)
        try:
            a=Application(r,clock);cli=CLI(a,'p',language=lang)
            for cmd in ('register Captain','production','development','config-info'):
                assert cli.safe_execute(cmd)==(True,0)
            initial=a.get_production('p')['entries'][0]['available']
            rules=a.configuration_info()['sha256'];clock.advance(59)
            for cmd in ('request primary01 invest primary 1000','request primary01 invest primary 1000','invest tertiary 500','production'):
                assert cli.safe_execute(cmd)==(True,0)
            before=a.get_production('p')['entries'][0]
            assert before['production_per_tick']==6 and before['market_capacity']==10000
        finally:r.close()
        r=SQLiteRepository(path)
        try:
            a=Application(r,clock);cli=CLI(a,'p',language=lang);clock.advance(1)
            assert cli.safe_execute('production')==(True,0)
            row=a.get_production('p')['entries'][0]
            assert row['available']==initial+5
            assert (row['production_per_tick'],row['market_capacity'])==(12,11000)
            clock.advance(60);assert cli.safe_execute('production')==(True,0)
            assert a.get_production('p')['entries'][0]['available']==initial+16
            for cmd in ('trade-quote buy grain 1','buy grain 1','sell grain 1','investments','ledger','status'):
                assert cli.safe_execute(cmd)==(True,0)
            assert a.get_player('p')['cash']==3500
            assert a.configuration_info()['sha256']==rules
            assert len(a.investment_ledger('p'))==2
            assert r.connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            print(json.dumps(dict(language=lang,production_before=6,production_after=12,
                capacity_before=10000,capacity_after=11000,first_period_net=5,
                second_period_net=11,cash=3500,restart=True,retry=True),sort_keys=True))
        finally:r.close()
print('ECON-05 CLI, restart, timing, trade and hash: OK')
