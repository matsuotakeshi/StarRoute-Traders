"""Deterministic CLI production demonstration in a temporary world."""
import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from starroute.catalog import Catalog
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.adapters.cli import CLI
with tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/'world.db';clock=ManualClock(100)
    r=SQLiteRepository(path,Catalog.load(Path(__file__).resolve().parents[1]/'examples/production-trial.json'),now=100)
    try:
        a=Application(r,clock);cli=CLI(a,'captain',language='en')
        for command in ('register Captain','production','buy grain 3','production'):
            assert cli.safe_execute(command)==(True,0)
        old={(x['planet_id'],x['goods_id']):x['stock'] for x in r.connection.execute('SELECT * FROM markets')}
        clock.advance(60);print('> advance test clock 60 seconds');cli.execute('production')
        now={(x['planet_id'],x['goods_id']):x['stock'] for x in r.connection.execute('SELECT * FROM markets')}
        for key,delta in [(('aurora','grain'),5),(('forge','grain'),1),(('aurora','alloy'),-1),(('haven','grain'),1)]:
            assert now[key]-old[key]==delta;print(key,'stock change',delta)
        world=r.world_id
    finally:r.close()
    r=SQLiteRepository(path)
    try:
        a=Application(r,clock);assert r.world_id==world
        CLI(a,'captain',language='en').execute('production')
        assert now=={(x['planet_id'],x['goods_id']):x['stock'] for x in r.connection.execute('SELECT * FROM markets')}
    finally:r.close()
print('Production, imports, demand and restart verification: OK')
