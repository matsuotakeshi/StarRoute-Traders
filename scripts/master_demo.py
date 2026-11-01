"""In-process master boundary demonstration; does not simulate authentication/TLS."""
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from starroute.catalog import Catalog
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.master import MasterService,ServerContext,Visibility,WorldTarget,target_for
from starroute.presentation import Presentation
from starroute.model import GameError

root=Path(__file__).resolve().parents[1]
for lang in ('ja','en'):
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'world.db';clock=ManualClock(100)
        r=SQLiteRepository(path,Catalog.load(root/'examples/industry-effects-trial.json'),now=100)
        try:
            a=Application(r,clock);m=MasterService(a)
            with r.transaction() as world:target=target_for(r,world)
            v=Visibility({'aurora','forge'},set(),{'aurora-forge'})
            ca=ServerContext(target,'bbs_a','user1',v);cb=ServerContext(target,'bbs_b','user1',v)
            for c in (ca,cb):m.execute(c,'register',{'handle':c.bbs_id},request_id='register')
            public=m.manifest(ca);assert public==m.manifest(cb)
            print('Public projection:',json.dumps(public,ensure_ascii=False))
            buy=m.execute(ca,'buy',{'goods_id':'grain','quantity':1},request_id='buy')
            assert buy==m.execute(ca,'buy',{'goods_id':'grain','quantity':1},request_id='buy')
            inv=m.execute(ca,'invest',{'industry':'primary','paid_credits':100},request_id='invest')
            assert inv==m.execute(ca,'invest',{'industry':'primary','paid_credits':100},request_id='invest')
            assert m.execute(cb,'status',{})['cash']==5000
            nav=m.execute(ca,'navigate',{'destination_id':'forge','mode':'warp','level':'fast'},request_id='trip')
            assert nav['fuel_cost']==20 and 'quote_id' not in nav
            clock.advance(nav['seconds']);m.execute(ca,'dock',{},request_id='dock')
            for stale in (WorldTarget('stale-universe',target.round_id),WorldTarget(target.universe_id,target.round_id+1)):
                try:m.execute(ServerContext(stale,'bbs_a','user1',v),'buy',{'goods_id':'grain','quantity':1},request_id='buy')
                except GameError as error:
                    assert error.code=='WORLD_TARGET_MISMATCH';print(Presentation(lang).error(error.code))
                else:raise AssertionError('stale target accepted')
            before=m.execute(ca,'status',{});assert before['cash']==4779
        finally:r.close()
        r=SQLiteRepository(path)
        try:
            m=MasterService(Application(r,clock));assert m.execute(ca,'status',{})==before
            result=m.result(ca,'buy','buy');assert result=={'status':'committed','result':buy}
            assert m.result(cb,'buy','buy')=={'status':'unknown'}
            assert m.manifest(ca)==public
            assert r.connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            print(json.dumps(dict(language=lang,site_a_cash=4779,site_b_cash=5000,
                shared_market=True,unknown_result_not_failure=True,committed_result_recovered=True,
                network_implemented=False,authentication_implemented=False)))
        finally:r.close()
print('Master-local boundary, scoped identity, safe projection and retries: OK')
