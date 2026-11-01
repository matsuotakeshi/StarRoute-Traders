"""Deterministic CLI supply/demand demo using an isolated in-memory world."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from starroute.catalog import Catalog
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.adapters.cli import CLI

clock=ManualClock(100)
r=SQLiteRepository(':memory:',Catalog.load(Path(__file__).resolve().parents[1]/'examples/phase3c-trial.json'),now=100)
try:
    app=Application(r,clock);cli=CLI(app,'captain',language='en')
    for command in ('register Captain','market','trade-quote buy grain 3','request trade01 buy grain 3','request trade01 buy grain 3','ledger'):
        print('>',command);assert cli.safe_execute(command)==(True,0)
    before=app.quote_trade('captain','grain',1,'buy')['total']
    clock.advance(120);print('> advance test clock by 120 seconds')
    cli.execute('market');cli.execute('trade-quote buy grain 1')
    after=app.quote_trade('captain','grain',1,'buy')['total']
    assert before-after==4
    assert len(app.trade_ledger('captain'))==1
    print('Supply/demand and retry verification: OK')
finally:r.close()
