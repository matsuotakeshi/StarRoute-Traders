"""Generated 48-planet universe: Japanese/English CLI and persistent economics."""
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from starroute.catalog import Catalog
from starroute.universe import generate
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.adapters.cli import CLI

root=Path(__file__).resolve().parents[1]
template=Catalog.load(root/'examples/industry-effects-trial.json').data
params=json.loads((root/'examples/universe-generator-trial.json').read_text())
data=generate(template,params,'cli-demo')
for lang in ('ja','en'):
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'world.db';clock=ManualClock(100)
        r=SQLiteRepository(path,Catalog(data),now=100)
        try:
            a=Application(r,clock);cli=CLI(a,'p',language=lang)
            for cmd in ('register Captain','status','config-info','region','production','development','routes'):
                assert cli.safe_execute(cmd)==(True,0)
            before=a.configuration_info();fixed=r.catalog.canonical()
            good=next(x['goods_id'] for x in a.get_market('p')['entries'] if x['stock'] and x['price']<=1000)
            destination=next(x for x in a.get_routes('p') if x['is_open'])
            for cmd in (f'request buy01 buy {good} 1',f'request buy01 buy {good} 1',f'go {destination["destination_id"]}'):
                assert cli.safe_execute(cmd)==(True,0)
            clock.advance(destination['seconds'])
            for cmd in (f'sell {good} 1','invest primary 100','invest tertiary 100','production','status'):
                assert cli.safe_execute(cmd)==(True,0)
            clock.advance(120);a.get_production('p');progress=a.get_development('p')
            cash=a.get_player('p')['cash']
        finally:r.close()
        r=SQLiteRepository(path)
        try:
            a=Application(r,clock);cli=CLI(a,'p',language=lang)
            for cmd in ('status','production','development','ledger','investments','config-info'):
                assert cli.safe_execute(cmd)==(True,0)
            assert r.catalog.canonical()==fixed and a.configuration_info()==before
            assert a.get_development('p')==progress and a.get_player('p')['cash']==cash
            assert len(a.trade_ledger('p'))==2 and len(a.investment_ledger('p'))==2
            assert r.connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            print(json.dumps(dict(language=lang,planets=len(r.catalog.planets),cash=cash,
                restart_preserved=True,duplicate_buy_once=True,universe_hash=before['universe']['definition_hash'])))
        finally:r.close()
print('48 planets, CLI trade, investment, production, replay and restart: OK')
