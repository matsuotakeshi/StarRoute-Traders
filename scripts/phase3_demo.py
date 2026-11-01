"""Isolated end-to-end CLI play, using an external generator and controlled clock.

Event injection below is a test harness only; no injection command is exposed to players.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from starroute.import_local import initialize
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.adapters.cli import CLI
from starroute.mechanics import apply_event
from starroute.rules import fingerprint


def run(directory,language):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    package=directory/'private-universe.json';database=directory/'demo.db'
    command=[sys.executable,'-m','srt_universe_generator','--template','examples/phase3-trial.json',
             '--parameters','examples/phase3-generator.json','--levels','examples/industry-levels-trial.json',
             '--seed','phase3-complete-demo','--created-at','2026-11-01T00:00:00+00:00','--output',str(package)]
    result=subprocess.run(command,cwd=ROOT,encoding='utf8',capture_output=True)
    if result.returncode:raise RuntimeError(result.stderr)
    print(result.stdout)
    print(json.dumps(initialize(package,database,100)))
    clock=ManualClock(100);r=SQLiteRepository(database);a=Application(r,clock);cli=CLI(a,'demo',language=language)
    def execute(command,expected=0):
        print('srt> '+command)
        code=cli.safe_execute(command)[1]
        if code!=expected:raise AssertionError((command,code,expected))
    try:
        execute('register Demo');execute('map 60 12');execute('map-names on');execute('map-names off')
        c=r.catalog;options=[]
        with r.transaction() as w:
            for route in a.engine.get_routes(w,'demo'):
                if not route['is_open']:continue
                for gid in c.goods:
                    buy=a.engine.quote_trade(w,'demo',gid,1,'buy')
                    from starroute.economy import quote
                    sale=quote(c,w.markets[route['destination_id'],gid],route['destination_id'],gid,1,False)
                    if sale['total']>buy['total'] and buy['total']<=w.players['demo'].cash:
                        options.append((sale['total']-buy['total'],route,gid))
        if not options:raise AssertionError('No profitable initial adjacent trade')
        _,route,gid=max(options,key=lambda x:x[0])
        execute('buy '+gid+' 1');execute('go '+route['destination_id'])
        execute('map 60 12');execute('news');execute('buy '+gid+' 1',expected=1)
        receipt=a.latest_voyage('demo');clock.advance(max(1,(receipt['arrival_at']-clock.now())//2))
        execute('status');execute('news');clock.advance(receipt['arrival_at']-clock.now());execute('status');execute('sell '+gid+' 1')
        profit=a.get_player('demo')['cash']-5000
        if profit<=0:raise AssertionError('Trade must realize a profit')
        execute('development')
        pid=a.get_player('demo')['planet_id']
        # Find a damaged/recoverable industry without exposing the private maximum in CLI output.
        with r.transaction() as w:
            candidates=[i for i in c.development['credits_per_unit'] if w.developments[pid,i]<c.development_planets[pid]['private_caps'][i]]
        if not candidates:
            with r.transaction() as w:apply_event(a.engine,w,'demo-prior-cyclone','cyclone',pid)
            candidates=['primary']
        industry=candidates[0];execute(f'invest {industry} {c.development["credits_per_unit"][industry]}')
        # Walk only existing open routes to reach an undeveloped edge, without teleporting.
        def find_path():
            with r.transaction() as w:
                start=w.players['demo'].planet_id;queue=[(start,[])];seen={start}
                for node,path in queue:
                    closed=[(rid,row) for rid,row in w.routes.items() if not row['is_open'] and node in (row['from'],row['to'])]
                    if closed:return path,closed[0]
                    for row in w.routes.values():
                        if row['is_open'] and node in (row['from'],row['to']):
                            dest=row['to'] if node==row['from'] else row['from']
                            if dest not in seen:seen.add(dest);queue.append((dest,path+[dest]))
            raise AssertionError('No frontier')
        path,(rid,row)=find_path()
        for dest in path:
            execute('go '+dest);trip=a.latest_voyage('demo');clock.advance(trip['arrival_at']-clock.now());execute('status')
        execute(f'request open-frontier donate {rid} {row["distance"]*c.phase3["route_cost_per_distance"]}')
        execute(f'request open-frontier donate {rid} {row["distance"]*c.phase3["route_cost_per_distance"]}')
        execute('shipyard');execute('ship-buy engineering_1');execute('insure')
        pid=a.get_player('demo')['planet_id']
        # A controlled, real committed event; do not change configured probabilities.
        local_source=next(row for (planet,good),row in c.production_sources.items() if planet==pid)
        industry=local_source['industry'];good=local_source['goods_id']
        with r.transaction() as w:level=w.developments[pid,industry]
        if level==0:execute(f'invest {industry} {c.development["credits_per_unit"][industry]}')
        clock.advance(c.economy['tick_seconds']);a.update()
        with r.transaction() as w:before_output=w.markets[pid,good].production_rate;before_level=w.developments[pid,industry]
        kind='cyclone' if industry=='primary' else 'factory_accident' if industry=='secondary' else 'planet_raid'
        with r.transaction() as w:apply_event(a.engine,w,'demo-planet-disaster',kind,pid)
        execute('development');execute('production');execute('market');execute('news')
        clock.advance(c.economy['tick_seconds']);execute('production');execute('market');execute('news')
        with r.transaction() as w:
            after_output=w.markets[pid,good].production_rate;after_level=w.developments[pid,industry]
        assert after_level<before_level and after_output<before_output
        damage=dict(industry=industry,goods_id=good,level_before=before_level,level_after=after_level,
                    production_before=before_output,production_after=after_output)
        before=a.get_player('demo');news=a._call('news','demo');rules=fingerprint(c)
        r.close();r=SQLiteRepository(database);a=Application(r,clock);cli=CLI(a,'demo',language=language)
        execute('status');execute('news')
        assert a.get_player('demo')==before
        assert a._call('news','demo')==news
        result={'language':language,'initial_trade_profit':profit,'cash':before['cash'],'ship':before['ship_id'],
                'damage':damage,'news_count':len(news),'rules':rules,'saved_reopened':True}
        print(json.dumps(result,ensure_ascii=False));return result
    finally:r.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',required=True);p.add_argument('--lang',choices=('ja','en'),default='ja');args=p.parse_args()
    run(args.directory,args.lang)
