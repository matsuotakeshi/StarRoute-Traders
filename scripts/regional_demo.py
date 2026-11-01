"""Controlled stock scenarios through the CLI; no production data or random event."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from starroute.catalog import Catalog
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.adapters.cli import CLI
r=SQLiteRepository(':memory:',Catalog.load(Path(__file__).resolve().parents[1]/'examples/regional-trial.json'),now=100)
try:
    a=Application(r,ManualClock(100));a.create_player('captain','Captain');cli=CLI(a,'captain',language='en')
    print('Controlled scenario: source shortage and distant oversupply')
    with r.transaction() as w:
        w.markets['aurora','grain'].stock=150;w.markets['haven','grain'].stock=500
    cli.execute('region');cli.execute('trade-quote buy grain 1')
    near=a.quote_trade('captain','grain',1,'buy')['total']
    with r.transaction() as w:w.players['captain'].planet_id='haven'
    cli.execute('region');cli.execute('trade-quote buy grain 1')
    far=a.quote_trade('captain','grain',1,'buy')['total']
    assert far<near
    print('Source buy price:',near,'Distant buy price:',far,'Reversal verified')
    cli.execute('buy grain 1');cli.execute('ledger')
finally:r.close()
