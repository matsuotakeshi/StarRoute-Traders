"""Isolated end-to-end administrator CLI and player menu exploration acceptance."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from starroute.repository import SQLiteRepository
from starroute.clock import ManualClock
from starroute import network_security as security
from starroute.local_door import LocalDoor
from starroute_bbs.client import save
from starroute_bbs.terminal import Terminal,width
from starroute_bbs.menu import Menu
from starroute.exploration import coordinates,HIDDEN

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',required=True);args=parser.parse_args()
    base=Path(args.directory).resolve();base.mkdir(mode=0o700,parents=True,exist_ok=False);package=base/'private-universe.json';db=base/'game.db'
    def run(module,*args):
        r=subprocess.run([sys.executable,'-m',module,*map(str,args)],cwd=ROOT,capture_output=True,text=True,encoding='utf8')
        if r.returncode:raise RuntimeError(module+' failed')
        return json.loads(r.stdout)
    generated=run('srt_universe_generator','--template','examples/exploration-trial.json','--parameters','examples/connected-universe-trial.json','--levels','examples/industry-levels-trial.json','--seed','exploration-demo','--output',package)
    uid=generated['universe_id'];admin=lambda *args:run('starroute.admin','--db',db,*args)
    for command in (('init',),('stage','--package',package),('validate','--universe',uid),('register','--universe',uid),('prepare','--universe',uid,'--round',1),('activate','--universe',uid,'--round',1)):admin(*command)
    clock=ManualClock(int(time.time()));key=os.urandom(32);save(base/'profile.json',{})
    r=SQLiteRepository(db)
    try:
        security.schema(r.connection);security.publish(r,key);profile=security.provision(r,key,'demo','Demo',clock.now())
        target=coordinates(r.catalog)[HIDDEN]
    finally:r.close()
    (base/'reference.key').write_bytes(key);os.chmod(base/'reference.key',0o600);save(base/'profile.json',profile)
    config={'database':str(db),'reference_key':str(base/'reference.key'),'profile':str(base/'profile.json')}
    b=LocalDoor(config,'1','Explorer',clock);b.connect();pid=b.call('status')['player_id']
    r=SQLiteRepository(db)
    try:
        with r.transaction() as w:w.players[pid].cash=2000000
    finally:r.close()
    terminal=Terminal(b,'en');menu=Menu(terminal);menu.refresh()
    def command(text):
        menu.handle(text)
        if menu.notice and menu.notice not in tuple(menu.text(k) for k in ('completed','review_remaining','departed','departed_rumor')):raise AssertionError(menu.notice)
    def confirm():
        while (menu.page+1)*max(1,menu.size()[0]-3)<len(menu.data):command('>')
        command('y');assert menu.state in ('TEXT','MAIN')
    command('e');command('1');confirm();assert b.call('explorer_info')['device']
    menu.main();command('e');command('4');confirm();assert len(b.call('notebook'))==1
    for lang in ('ja','en'):
        terminal.language=lang;menu.main();command('e');command('5')
        for cols,rows in ((80,24),(70,24),(50,24),(100,30)):
            terminal.columns=cols;terminal.rows=rows;lines=menu.render();assert len(lines)<rows and all(width(l)<cols for l in lines)
    terminal.columns=80;terminal.rows=24
    menu.main();command('e');command('2');command(str(target[0]));command(str(target[1]));command('1');confirm()
    flight=b.call('flight');assert flight['target']==target and flight['remaining_seconds']>0
    b.logout();clock.advance(flight['remaining_seconds']);b=LocalDoor(config,'1','Explorer',clock);b.connect()
    menu=Menu(Terminal(b,'ja'));menu.refresh();assert menu.info['exploration']['naming_pending']
    assert menu.state=='STAR_NAME';command('私のMiXeD星');confirm();assert b.call('status')['planet_name']=='私のMiXeD星'
    market=b.call('market');good=next(r['goods_id'] for r in market['entries'] if r['max_buy']>0)
    menu.main();command('buy '+good+' 1');confirm();menu.main();command('sell '+good+' 1');confirm()
    assert len(b.call('discoverers'))==1
    menu.main();command('e');command('3');command('1');command('1');confirm();clock.advance(b.call('flight')['remaining_seconds']);b.connect();b.call('status')
    check=admin('check')['result'];assert check['integrity']==['ok'] and not check['foreign_keys']
    result={'admin_generator_register_activate':'PASS','menu_device_guild_coordinates':'PASS','logout_arrival_resume_naming':'PASS','japanese_case_preserving_name':'PASS','hidden_market_buy_sell':'PASS','normal_planet_return':'PASS','ja_en_terminal_sizes':'PASS','database_integrity':'ok','secret_coordinates_logged':False,'time_source':'ManualClock on isolated demonstration only'}
    save(base/'result.json',result);print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
