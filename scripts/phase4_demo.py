"""A-E integration rehearsal. Real CLI entry points with an injected test clock.

Uses only a NEW directory, disposable signing key and local Git repository.
"""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from starroute.clock import ManualClock
from starroute import admin
from starroute.__main__ import main as game_main
from starroute.operations import Manager
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.distribution import run


def rehearsal(directory,lang):
    directory=Path(directory).resolve();directory.mkdir(mode=0o700,parents=True,exist_ok=False)
    clock=ManualClock(100);db=directory/'game.db'
    def adm(*args):
        print('admin> '+' '.join(args));out=io.StringIO()
        with patch('starroute.admin.SystemClock',return_value=clock),contextlib.redirect_stdout(out):code=admin.main(['--db',str(db),'--lang',lang,*args])
        print(out.getvalue());assert code==0,args
        return json.loads(out.getvalue())['result']
    def game(pid,command):
        print(pid+'> '+command)
        with patch('starroute.__main__.SystemClock',return_value=clock),patch.object(sys,'argv',['starroute','--db',str(db),'--player',pid,'--lang',lang,'--command',command]):
            assert game_main()==0,command
    def view(fn):
        r=SQLiteRepository(db)
        try:return fn(Application(r,clock))
        finally:r.close()
    def generate(label):
        p=directory/(label+'.json')
        result=run([sys.executable,'-m','srt_universe_generator','--template',str(ROOT/'examples/phase3-trial.json'),'--parameters',str(ROOT/'examples/phase3-generator.json'),
                    '--levels',str(ROOT/'examples/industry-levels-trial.json'),'--seed','phase3-complete-demo' if label=='A' else 'phase4-'+label,
                    '--created-at','2026-11-02T00:00:00+00:00','--output',str(p)])
        print(result.decode());return p
    adm('init');a=generate('A');uid=adm('stage','--package',str(a))['universe_id']
    adm('validate','--universe',uid);adm('register','--universe',uid);adm('prepare','--universe',uid,'--round','1','--start','100');adm('activate','--universe',uid,'--round','1')
    for pid in ('alice','bob','carol','dave'):game(pid,'register '+pid)
    good=view(lambda a:next(r['goods_id'] for r in a.get_market('alice')['entries'] if r['stock']>=5))
    for pid in ('alice','bob','carol','dave'):game(pid,'buy '+good+' 1');game(pid,'sell '+good+' 1')
    dest=view(lambda a:next(r['destination_id'] for r in a.get_routes('alice') if r['is_open']))
    game('alice','go '+dest);clock.value=view(lambda a:a.latest_voyage('alice')['arrival_at']);game('alice','dock')
    def investment(a):
        w=a.repository._load();p=w.players['alice'];c=a.engine.catalog
        i=next(i for i in c.development['credits_per_unit'] if w.developments[p.planet_id,i]<c.development_planets[p.planet_id]['private_caps'][i])
        return i,c.development['credits_per_unit'][i]
    industry,paid=view(investment);game('alice',f'invest {industry} {paid}')
    def frontier(a):
        w=a.repository._load();start=w.players['alice'].planet_id;queue=[(start,[])];seen={start}
        for node,path in queue:
            for rid,row in w.routes.items():
                if node not in (row['from'],row['to']):continue
                if not row['is_open']:return path,rid
                dest=row['to'] if node==row['from'] else row['from']
                if dest not in seen:seen.add(dest);queue.append((dest,path+[dest]))
        raise AssertionError('frontier')
    path,rid=view(frontier)
    for dest in path:
        game('alice','go '+dest);clock.value=view(lambda a:a.latest_voyage('alice')['arrival_at']);game('alice','dock')
    game('alice',f'donate {rid} 10')
    before=view(lambda a:a.get_player('alice'));game('alice','score');assert before==view(lambda a:a.get_player('alice'))
    # B: signed local Git exercises the same blob/manifest validation as GitHub SSH.
    b=generate('B');repo=directory/'distribution';repo.mkdir();target=repo/'universe.json';target.write_bytes(b.read_bytes())
    key=directory/'TEST_ONLY_signer';run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)])
    trust=directory/'allowed_signers';trust.write_text('test-issuer '+Path(str(key)+'.pub').read_text(),encoding='utf8')
    manifest=Path(str(target)+'.manifest.json');manifest.write_text(json.dumps({'format':'srt-signed-manifest-v1','universe_id':json.loads(b.read_bytes())['metadata']['universe_id'],
        'package_sha256':hashlib.sha256(b.read_bytes()).hexdigest()}),encoding='utf8')
    run(['ssh-keygen','-Y','sign','-f',str(key),'-n','starroute-universe',str(manifest)])
    git=['git','-C',str(repo)];run(git+['init']);run(git+['add','.']);run(git+['-c','user.name=Test','-c','user.email=test@example.invalid','-c','commit.gpgsign=false','commit','-m','universe B test'])
    commit=run(git+['rev-parse','HEAD']).decode().strip()
    nextid=adm('fetch','--repository',str(repo),'--commit',commit,'--package-path','universe.json','--allowed-signers',str(trust),'--identity','test-issuer','--local-test')['universe_id']
    key.unlink()  # only the test key just created above, never an existing credential
    adm('register','--universe',nextid);assert before==view(lambda a:a.get_player('alice'))
    # C: close twice, read final scores and immutable hall through both CLIs.
    game('alice','rankings');adm('finish','--universe',uid,'--round','1');adm('finish','--universe',uid,'--round','1')
    hall=adm('hall');assert len(hall)==12;game('alice','hall');game('alice','score 1')
    # D/E: failed activation rolls back; identical retry starts a clean round.
    adm('prepare','--universe',nextid,'--round','2','--start',str(clock.now()))
    m=Manager(db,clock.now(),lambda name:(_ for _ in ()).throw(RuntimeError('injected')) if name=='activate' else None)
    try:
        try:m.activate(2,nextid)
        except RuntimeError:pass
        else:raise AssertionError('missing fault')
        assert m.c.execute('SELECT state FROM p4_rounds WHERE round_id=2').fetchone()[0]=='PREPARED'
        assert m.inspect()['integrity']==['ok']
    finally:m.close()
    adm('activate','--universe',nextid,'--round','2');assert view(lambda a:a.get_player('alice')['cash'])==5000
    assert hall==adm('hall');game('alice','buy '+good+' 1');game('alice','score 2');game('alice','rankings 1');adm('archive-check','--round','1')
    c=generate('C');m=Manager(db,clock.now())
    try:
        cid=m.stage(c.read_bytes());m.failpoint=lambda name:(_ for _ in ()).throw(RuntimeError('injected')) if name=='register' else None
        try:m.register(cid)
        except RuntimeError:pass
        else:raise AssertionError('missing fault')
        assert m.item(cid)['state']=='VALIDATED';assert m.repo._load().season_id==2
    finally:m.close()
    result=adm('check');assert result['integrity']==['ok'] and not result['foreign_keys']
    summary=dict(scenarios=['A','B','C','D','E'],language=lang,hall_records=12,rounds=2,integrity='ok',git_commit=commit,real_github='not_tested',clock='injected test clock; real CLI parsers and operations')
    (directory/'result.json').write_text(json.dumps(summary,indent=2),encoding='utf8');print(json.dumps(summary));return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',required=True);p.add_argument('--lang',choices=('ja','en'),default='ja');args=p.parse_args()
    rehearsal(args.directory,args.lang)
