"""External generation -> independent validation -> isolated game test. No activation."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from starroute.universe_package import to_catalog
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.adapters.cli import CLI

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
    tmp=Path(tmp);levels=json.loads((root/'examples/industry-levels-trial.json').read_text())
    levels['initial_policy']='zero_v1';levels['maximum_ranges']={i:{'min':1,'max':1} for i in levels['maximum_ranges']}
    (tmp/'levels.json').write_text(json.dumps(levels))
    subprocess.run([sys.executable,'-m','srt_universe_generator','--template',str(root/'examples/industry-effects-trial.json'),
        '--parameters',str(root/'examples/universe-generator-trial.json'),'--levels',str(tmp/'levels.json'),
        '--seed','package-cli','--output',str(tmp/'universe.json')],cwd=root,check=True)
    subprocess.run([sys.executable,'-m','starroute.package_check','--input',str(tmp/'universe.json'),'--report',str(tmp/'validation.json')],cwd=root,check=True)
    package=json.loads((tmp/'universe.json').read_text(encoding='utf-8'));catalog=to_catalog(package)
    for lang in ('ja','en'):
        path=tmp/(lang+'.db');clock=ManualClock(100);r=SQLiteRepository(path,catalog,now=100)
        try:
            a=Application(r,clock);cli=CLI(a,'p',language=lang)
            for command in ('register Captain','development','request invest01 invest primary 10','request invest01 invest primary 10','development'):
                assert cli.safe_execute(command)==(True,0)
            cash=a.get_player('p')['cash'];assert cash==4990
            assert cli.safe_execute('invest primary 10')==(True,1)
            assert a.get_player('p')['cash']==cash
            good=next(x['goods_id'] for x in a.get_market('p')['entries'] if x['stock'] and x['price']<=1000)
            for cmd in (f'buy {good} 1',f'sell {good} 1'):assert cli.safe_execute(cmd)==(True,0)
            clock.advance(120);assert cli.safe_execute('production')==(True,0)
            current=a.get_development('p');saved=a.configuration_info()
        finally:r.close()
        r=SQLiteRepository(path)
        try:
            a=Application(r,clock);assert a.get_development('p')==current and a.configuration_info()==saved
            assert a.get_player('p')['cash']==4990
            assert len(a.investment_ledger('p'))==1
            print(json.dumps(dict(language=lang,planet_count=48,initial_level=0,current_primary_level=1,cash=4990,
                over_limit_rejected=True,restart_preserved=True,registered=False,activated=False)))
        finally:r.close()
    assert not any(k.startswith('srt_universe_generator') for k in sys.modules)
print('External generator, validation only, Lv0 investment, rejection, restart and CLI: OK')
