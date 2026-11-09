"""Isolated deterministic multi-leg trade measurement; never accepts an existing DB."""
import argparse
import copy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from starroute.application import Application
from starroute.catalog import Catalog
from starroute.clock import ManualClock
from starroute.repository import SQLiteRepository
from starroute.engine import Engine
from starroute.model import GameError


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',required=True);args=parser.parse_args()
    base=Path(args.directory);base.mkdir(parents=True,exist_ok=False)
    data=json.loads((ROOT/'examples/phase3c-trial.json').read_text(encoding='utf-8'))
    data['market_buyback']={'mode':'recovering_v1','status':'provisional','capacity':100,'initial':100,'recovery_units':10,'interval_seconds':60}
    # Test-only opening, no installed catalogue is changed.
    for route in data['routes']:route['is_open']=True
    clock=ManualClock(100);repo=SQLiteRepository(base/'game.db',Catalog(data),now=100)
    try:
        app=Application(repo,clock);app.create_player('pilot','Trade Pilot');initial=app.get_player('pilot')['cash'];legs=[]
        for leg in range(2):
            candidates=[]
            for route in app.get_routes('pilot'):
                if not route['is_open']:continue
                for row in app.get_market('pilot')['entries']:
                    quantity=min(3,row['max_buy'])
                    if not quantity:continue
                    # Administrator-only simulation selects a reproducible trial route.
                    world=copy.deepcopy(repo._load());engine=Engine(repo.catalog)
                    try:
                        purchase=engine.buy_goods(world,'pilot',row['goods_id'],quantity)
                        journey=engine.navigate(world,'pilot',route['destination_id'],'normal',None)
                        engine.update(world,world.players['pilot'].arrival_at)
                        sale=engine.sell_goods(world,'pilot',row['goods_id'],quantity)
                    except GameError:continue
                    candidates.append((sale['total']-purchase['total'],row['goods_id'],quantity,route['destination_id']))
            profit,good,quantity,destination=max(candidates)
            assert profit>0,'No profitable trial leg'
            before=app.get_player('pilot');purchase=app.buy_goods('pilot',good,quantity,request_id=f'buy-{leg}')
            voyage=app.navigate('pilot',destination,'normal',None,request_id=f'go-{leg}')
            clock.value=app.get_player('pilot')['arrival_at']
            sale=app.sell_goods('pilot',good,quantity,request_id=f'sell-{leg}')
            after=app.get_player('pilot')
            assert after['cash']-before['cash']==sale['total']-purchase['total']>0
            assert not after['cargo'] and after['used_capacity']==0
            legs.append({'from':before['planet_id'],'to':destination,'goods_id':good,'quantity':quantity,
                         'purchase_cr':purchase['total'],'sale_cr':sale['total'],'profit_cr':sale['total']-purchase['total'],
                         'cash_after':after['cash'],'cargo_after':after['cargo']})
        result={'initial_cash':initial,'final_cash':app.get_player('pilot')['cash'],'legs':legs,'rules':app.configuration_info()}
        (base/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False))
    finally:repo.close()


if __name__=='__main__':main()
