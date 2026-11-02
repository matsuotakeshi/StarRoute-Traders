"""Run only in the disposable pkg acceptance jail; creates synthetic game data."""
import argparse,hashlib,json,os,sqlite3,sys,time
from pathlib import Path
sys.path.insert(0,'/usr/local/libexec/starroute-traders')

def snapshot(db):
    c=sqlite3.connect(db)
    try:
        tables=['metadata','world_identity','player_state','cargo','planet_development','p4_rounds','p4_hall','p4_rankings','routes']
        return {t:hashlib.sha256(repr(c.execute('SELECT * FROM '+t+' ORDER BY 1,2').fetchall()).encode()).hexdigest() for t in tables}
    finally:c.close()

def create(root,fixtures):
    from starroute.operations import Manager,initialize
    from starroute.application import Application
    from starroute.clock import ManualClock
    from starroute.repository import SQLiteRepository
    from starroute.catalog import Catalog
    from starroute.universe_package import export_package
    from starroute import network_security as sec
    from starroute_bbs.client import save
    from srt_universe_generator.levels import generate
    root.mkdir(parents=True,exist_ok=False);db=root/'game.db';now=int(time.time());initialize(db,now)
    m=Manager(db,now)
    template=Catalog.load(fixtures/'phase3-trial.json').data
    params=json.loads((fixtures/'phase3-generator.json').read_text());levels=json.loads((fixtures/'industry-levels-trial.json').read_text())
    app=None
    for round_id in (1,2):
        package=export_package(generate(template,params,levels,'pkg-round-'+str(round_id)))
        uid=m.stage(json.dumps(package).encode());m.register(uid);m.prepare(uid,round_id,now);m.activate(round_id,uid)
        app=Application(m.repo,ManualClock(now))
        if round_id==1:app.create_player('pilot','Package Pilot')
        app.buy_goods('pilot','grain',1)
        p=m.repo._load().players['pilot']
        industry=next(i for i in ('primary','secondary','tertiary','quaternary') if m.repo._load().developments[p.planet_id,i]<m.repo.catalog.development_planets[p.planet_id]['private_caps'][i])
        app._call('invest','pilot',industry,m.repo.catalog.development['credits_per_unit'][industry])
        if round_id==1:m.finish(1,uid)
    key=os.urandom(32);(root/'reference.key').write_bytes(key);os.chmod(root/'reference.key',0o600)
    sec.schema(m.c);sec.publish(m.repo,key);save(root/'site-profile.json',sec.provision(m.repo,key,'pkgtest','Pkg Test BBS',now))
    assert m.c.execute('SELECT count(*) FROM p4_hall').fetchone()[0]>0
    m.close()
    config=Path('/usr/local/etc/starroute-traders/standalone.json')
    config.write_text(json.dumps({'mode':'standalone','database':str(db),'reference_key':str(root/'reference.key'),'profile':str(root/'site-profile.json'),'language':'en','ansi':True,'operator_note':'must survive pkg upgrade/delete'}))
    os.chmod(config,0o600)
    result={'tables':snapshot(db),'config_hash':hashlib.sha256(config.read_bytes()).hexdigest(),'key_hash':hashlib.sha256((root/'reference.key').read_bytes()).hexdigest(),'at':now}
    (root/'expected.json').write_text(json.dumps(result))
    print('CREATED: traded, invested, two rounds, rankings and hall populated')

def check(root):
    saved=json.loads((root/'expected.json').read_text())
    assert snapshot(root/'game.db')==saved['tables'],'game state changed'
    assert hashlib.sha256(Path('/usr/local/etc/starroute-traders/standalone.json').read_bytes()).hexdigest()==saved['config_hash'],'edited config changed'
    assert hashlib.sha256((root/'reference.key').read_bytes()).hexdigest()==saved['key_hash'],'key changed'
    c=sqlite3.connect(root/'game.db')
    assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok';assert not c.execute('PRAGMA foreign_key_check').fetchall();c.close()
    print('PRESERVED: assets, coordinates/catalog, industries, rounds, hall, config and keys; DB integrity OK')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('operation',choices=('create','check'));p.add_argument('--root',default='/var/db/starroute-traders/world');p.add_argument('--fixtures',default='/verification/examples');a=p.parse_args()
    if a.operation=='create':create(Path(a.root),Path(a.fixtures))
    else:check(Path(a.root))
