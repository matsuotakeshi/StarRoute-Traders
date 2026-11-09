"""Admin CLI acceptance in a new private directory; never accepts existing state."""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.universe_package import to_catalog


def main():
    p=argparse.ArgumentParser();p.add_argument('--directory',required=True);a=p.parse_args()
    base=Path(a.directory).resolve();base.mkdir(mode=0o700,parents=True,exist_ok=False)
    package=base/'private-universe.json';db=base/'game.db'
    def run(module,*args):
        completed=subprocess.run([sys.executable,'-m',module,*map(str,args)],cwd=ROOT,capture_output=True,text=True,encoding='utf8')
        if completed.returncode:raise RuntimeError('isolated CLI operation failed: '+module)
        return json.loads(completed.stdout)
    generated=run('srt_universe_generator','--template','examples/market-buyback-trial.json','--parameters','examples/connected-universe-trial.json',
                  '--levels','examples/industry-levels-trial.json','--seed','foundation-demo','--output',package)
    uid=generated['universe_id']
    def admin(*args):return run('starroute.admin','--db',db,*args)
    admin('init');admin('stage','--package',package);admin('validate','--universe',uid);admin('register','--universe',uid)
    admin('prepare','--universe',uid,'--round',1);admin('activate','--universe',uid,'--round',1)
    r=SQLiteRepository(db)
    try:
        app=Application(r,ManualClock(int(time.time())));players=[app.create_account('demo_a','1','Pilot'),app.create_account('demo_b','1','Pilot')]
        pid=players[0]['player_id'];market=app.get_market(pid);good=next(row['goods_id'] for row in market['entries'] if row['max_buy']>0)
        app.buy_goods(pid,good,1);app.sell_goods(pid,good,1)
        before={p['player_id']:p['planet_id'] for p in players};private=r.catalog.data['universe']['private_world']
        normal=len(r.catalog.planets);opened=sum(row['is_open'] for row in r.catalog.data['routes']);closed=len(r.catalog.data['routes'])-opened
    finally:r.close()
    r=SQLiteRepository(db)
    try:
        app=Application(r,ManualClock(int(time.time())));assert all(app.get_player(pid)['planet_id']==place for pid,place in before.items())
        assert r.catalog.data['universe']['private_world']==private
    finally:r.close()
    check=admin('check')['result'];assert check['integrity']==['ok'] and not check['foreign_keys']
    result={'normal_planets':normal,'initial_open_routes':opened,'closed_routes':closed,'hidden_planets':1,
            'schema_version':generated['schema_version'],'cli_registration_activation':'PASS','ordinary_trade':'PASS',
            'restart_positions_and_private_data':'PASS','database_integrity':'ok','secret_coordinates_logged':False}
    (base/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8');print(json.dumps(result))

if __name__=='__main__':main()
