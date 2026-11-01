import copy
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from starroute.catalog import Catalog
from starroute.clock import ManualClock
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.master import MasterService,ServerContext,Visibility,target_for
from starroute.model import GameError
from starroute.rules import fingerprint
from starroute.universe_package import export_package,to_catalog,digest
from starroute.package_check import inspect
from srt_universe_generator.levels import generate

ROOT=Path(__file__).resolve().parents[1]
STAMP='2026-11-01T00:00:00+00:00'
UID='00000000-0000-0000-0000-000000000007'

class PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template=Catalog.load(ROOT/'examples/industry-effects-trial.json').data
        cls.params=json.loads((ROOT/'examples/universe-generator-trial.json').read_text())
        cls.levels=json.loads((ROOT/'examples/industry-levels-trial.json').read_text())
        cls.data=generate(cls.template,cls.params,cls.levels,'package-tests',UID)
        cls.package=export_package(cls.data,STAMP)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'world.db';self.clock=ManualClock(100)

    def zero(self,policy='zero_v1'):
        levels=copy.deepcopy(self.levels);levels['initial_policy']=policy
        levels['maximum_ranges']={i:dict(min=1,max=1) for i in levels['maximum_ranges']}
        return generate(self.template,self.params,levels,'zero',UID)

    def open(self,data):
        r=SQLiteRepository(self.path,Catalog(data),now=100);self.addCleanup(r.close)
        return r,Application(r,self.clock)

    def test_192_independent_level_pairs(self):
        rows=self.package['world']['planets'];pairs=[v for p in rows for v in p['industries'].values()]
        self.assertEqual(len(rows),48);self.assertEqual(len(pairs),192)
        self.assertTrue(all(1<=v['maximum_level'] and 0<=v['initial_level']<=v['maximum_level'] for v in pairs))
        self.assertTrue(any(v['initial_level']==0 for v in pairs));self.assertTrue(any(v['maximum_level']==1 for v in pairs))
        self.assertTrue(any(v['initial_level']==v['maximum_level'] for v in pairs))
        self.assertGreater(len({tuple(v['maximum_level'] for v in p['industries'].values()) for p in rows}),1)

    def test_per_industry_ranges_are_independent(self):
        config=copy.deepcopy(self.levels)
        for n,ind in enumerate(config['maximum_ranges'],1):config['maximum_ranges'][ind]={'min':n,'max':n}
        data=generate(self.template,self.params,config,'different-ranges',UID)
        self.assertTrue(all(list(r['private_caps'].values())==[1,2,3,4] for r in data['development']['planets']))

    def test_all_zero_and_maximum_one_are_supported(self):
        data=self.zero();r,a=self.open(data);a.create_player('p','P')
        self.assertTrue(all(v==0 for row in data['development']['planets'] for v in row['initial_progress'].values()))
        self.assertTrue(all(v==1 for row in data['development']['planets'] for v in row['private_caps'].values()))
        self.assertTrue(all(x['level']==0 for x in a.get_development('p')['industries']))
        receipt=a.invest('p','primary',10);self.assertEqual(receipt['level'],1)
        cash=a.get_player('p')['cash']
        with self.assertRaises(GameError):a.invest('p','primary',10)
        self.assertEqual(cash,a.get_player('p')['cash'])

    def test_initial_equal_maximum_rejects_investment_without_charge(self):
        r,a=self.open(self.zero('maximum_v1'));a.create_player('p','P');cash=a.get_player('p')['cash']
        with self.assertRaises(GameError):a.invest('p','primary',10)
        self.assertEqual(a.get_player('p')['cash'],cash);self.assertEqual(a.investment_ledger('p'),[])

    def test_roundtrip_preserves_definition_and_reproduction(self):
        restored=to_catalog(json.loads(json.dumps(self.package)))
        self.assertEqual(restored.data['universe']['definition_hash'],self.data['universe']['definition_hash'])
        self.assertEqual(restored.development,Catalog(self.data).development)
        again=export_package(generate(self.template,self.params,self.levels,'package-tests',UID),STAMP)
        self.assertEqual(self.package,again)

    def test_different_seed_changes_levels_but_not_shared_rules(self):
        other=generate(self.template,self.params,self.levels,'other-levels',UID)
        self.assertNotEqual(other['development']['planets'],self.data['development']['planets'])
        self.assertEqual(fingerprint(Catalog(other)),fingerprint(Catalog(self.data)))
        changed=copy.deepcopy(self.levels);changed['maximum_ranges']['primary']['max']=6
        self.assertNotEqual(fingerprint(Catalog(generate(self.template,self.params,changed,'package-tests',UID))),fingerprint(Catalog(self.data)))

    def test_package_is_versioned_exchange_not_catalog_dump(self):
        self.assertNotIn('format_version',self.package)
        self.assertIn('industries',self.package['world']['planets'][0])
        self.assertNotIn('private_caps',self.package['world']['planets'][0])
        self.assertEqual(self.package['world']['planets'][0]['names'],{'ja':'アルヴェラ','en':'Alvera'})

    def test_invalid_levels_rejected_even_with_recomputed_package_checksum(self):
        for patch in ({'maximum_level':0},{'initial_level':-1},{'initial_level':999},{'maximum_level':True},{'initial_level':0.5}):
            data=copy.deepcopy(self.package);data['world']['planets'][0]['industries']['primary'].update(patch)
            with self.subTest(patch=patch),self.assertRaises((GameError,ValueError)):
                data['integrity']['sha256']=digest(data)
                to_catalog(data)

    def test_every_industry_pair_is_validated(self):
        for index in (0,17,47):
            for industry in self.levels['maximum_ranges']:
                data=copy.deepcopy(self.package);data['world']['planets'][index]['industries'][industry]['maximum_level']=0
                data['integrity']['sha256']=digest(data)
                with self.subTest(index=index,industry=industry),self.assertRaises((GameError,ValueError)):to_catalog(data)

    def test_bad_names_duplicates_schema_and_integrity_rejected(self):
        edits=[lambda d:d.update(schema_version=99),lambda d:d['world']['planets'][0]['names'].update(en='Other'),
               lambda d:d['world']['planets'].__setitem__(1,copy.deepcopy(d['world']['planets'][0])),
               lambda d:d['world']['planets'].pop(),lambda d:d['world']['planets'][0]['industries'].pop('primary')]
        for edit in edits:
            data=copy.deepcopy(self.package);edit(data);data['integrity']['sha256']=digest(data)
            with self.assertRaises((GameError,ValueError)):to_catalog(data)
        data=copy.deepcopy(self.package);data['metadata']['created_at']='2026-11-02T00:00:00+00:00'
        with self.assertRaises(ValueError):to_catalog(data)

    def test_generator_rejects_zero_maximum(self):
        levels=copy.deepcopy(self.levels);levels['maximum_ranges']['primary']={'min':0,'max':0}
        with self.assertRaises((GameError,ValueError)):generate(self.template,self.params,levels,'bad',UID)

    def test_runtime_and_checker_do_not_import_generator(self):
        path=Path(self.tmp.name)/'package.json';path.write_text(json.dumps(self.package),encoding='utf-8')
        code='''import sys,importlib.abc
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,name,*args):
  if name.startswith('srt_universe_generator'):raise AssertionError('runtime imported generator')
sys.meta_path.insert(0,Block())
from starroute.package_check import inspect
assert inspect(sys.argv[1])['state']=='validated'
from starroute.universe_package import to_catalog
import json
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
c=to_catalog(json.load(open(sys.argv[1],encoding='utf-8')))
r=SQLiteRepository(sys.argv[2],c,now=100);a=Application(r,ManualClock(100));a.create_player('p','P');r.close()
r=SQLiteRepository(sys.argv[2]);assert len(r.catalog.planets)==48;r.close()
'''
        result=subprocess.run([sys.executable,'-c',code,str(path),str(self.path)],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_external_algorithm_does_not_import_game_engine_or_database(self):
        code='''import sys,importlib.abc,json
from pathlib import Path
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,name,*args):
  if name in ('starroute.engine','starroute.application','starroute.repository','sqlite3'):raise AssertionError('generator imported runtime')
sys.meta_path.insert(0,Block())
from srt_universe_generator.levels import generate
from starroute.catalog import Catalog
d=generate(Catalog.load('examples/industry-effects-trial.json').data,json.loads(Path('examples/universe-generator-trial.json').read_text()),json.loads(Path('examples/industry-levels-trial.json').read_text()),'isolated')
assert len(d['planets'])==48
'''
        result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_standalone_bundle_runs_without_game_server(self):
        from scripts.build_generator_bundle import build
        archive=Path(self.tmp.name)/'tool.zip';build(archive);folder=Path(self.tmp.name)/'tool'
        with zipfile.ZipFile(archive) as bundle:bundle.extractall(folder)
        for name in ('engine','repository','application','master'):
            self.assertFalse((folder/'starroute'/(name+'.py')).exists())
        args=[sys.executable,'-m','srt_universe_generator','--template','examples/industry-effects-trial.json',
              '--parameters','examples/universe-generator-trial.json','--levels','examples/industry-levels-trial.json',
              '--seed','standalone','--output','private.json']
        result=subprocess.run(args,cwd=folder,capture_output=True,text=True,env={**os.environ,'PYTHONPATH':''})
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(to_catalog(json.loads((folder/'private.json').read_text(encoding='utf-8'))).planets),48)
        before=(folder/'private.json').read_bytes()
        self.assertEqual(subprocess.run(args,cwd=folder,capture_output=True,env={**os.environ,'PYTHONPATH':''}).returncode,1)
        self.assertEqual(before,(folder/'private.json').read_bytes())

    def test_validation_has_no_registration_or_activation_side_effect(self):
        r,a=self.open(self.zero());a.create_player('p','P');before=r.catalog.canonical();cash=a.get_player('p')['cash']
        path=Path(self.tmp.name)/'package.json';path.write_text(json.dumps(self.package),encoding='utf-8')
        result=inspect(path);self.assertEqual(result['state'],'validated')
        self.assertFalse(result['registered']);self.assertFalse(result['activated']);self.assertEqual(result['authenticity'],'not_verified')
        path.write_text('{}');self.assertEqual(inspect(path)['state'],'rejected')
        self.assertEqual(r.catalog.canonical(),before);self.assertEqual(a.get_player('p')['cash'],cash)

    def test_public_projection_has_current_level_not_maximum_or_seed(self):
        data=self.zero();r,a=self.open(data);m=MasterService(a)
        with r.transaction() as w:target=target_for(r,w)
        pid=data['starting']['planet_id'];ctx=ServerContext(target,'bbs','u',Visibility({pid},set(),set()))
        m.execute(ctx,'register',{'handle':'P'},request_id='register')
        view=m.execute(ctx,'development',{});self.assertTrue(all(set(x)=={'industry','level'} for x in view['industries']))
        result=m.execute(ctx,'invest',{'industry':'primary','paid_credits':10},request_id='invest')
        self.assertEqual(result['level'],1);self.assertNotIn('progress',result)
        text=json.dumps([view,result,m.manifest(ctx)])
        for field in ('maximum_level','private_caps','seed','template','initial_progress'):self.assertNotIn('"'+field+'"',text)

    def test_two_sites_cannot_exceed_last_level(self):
        data=self.zero();r,a=self.open(data);m=MasterService(a)
        with r.transaction() as w:target=target_for(r,w)
        v=Visibility({data['starting']['planet_id']},set(),set())
        contexts=[ServerContext(target,site,'u',v) for site in ('site_a','site_b')]
        for ctx in contexts:m.execute(ctx,'register',{'handle':'P'},request_id='register')
        r.close();results=[]
        def invest(ctx):
            repo=SQLiteRepository(self.path)
            try:results.append(MasterService(Application(repo,ManualClock(100))).execute(ctx,'invest',{'industry':'primary','paid_credits':10},request_id='one'))
            except GameError as e:results.append(e.code)
            finally:repo.close()
        threads=[threading.Thread(target=invest,args=(ctx,)) for ctx in contexts]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(sum(isinstance(x,dict) for x in results),1);self.assertIn('INVESTMENT_UNAVAILABLE',results)
        repo=SQLiteRepository(self.path);self.addCleanup(repo.close)
        self.assertEqual(repo.connection.execute('SELECT count(*) FROM investment_records').fetchone()[0],1)
        self.assertEqual(repo.connection.execute('SELECT sum(cash) FROM player_state').fetchone()[0],9990)

    def test_save_reload_preserves_current_levels_and_hash(self):
        cat=to_catalog(export_package(self.zero(),STAMP));r,a=self.open(cat.data);a.create_player('p','P')
        a.invest('p','primary',10);self.clock.advance(120);a.get_production('p');before=a.get_development('p');h=fingerprint(r.catalog);r.close()
        r=SQLiteRepository(self.path);self.addCleanup(r.close);a=Application(r,self.clock)
        self.assertEqual(a.get_development('p'),before);self.assertEqual(fingerprint(r.catalog),h)

    def test_public_definition_is_not_an_encoding_of_private_maxima(self):
        from starroute.universe import seal_manifest
        from starroute.master import public_definition,WorldTarget
        levels=copy.deepcopy(self.levels);levels['initial_policy']='zero_v1'
        first=generate(self.template,self.params,levels,'private-ambiguity',UID)
        second=copy.deepcopy(first);row=second['development']['planets'][0]
        row['private_caps']['primary']=1 if row['private_caps']['primary']!=1 else 2
        seal_manifest(second)
        a,b=Catalog(first),Catalog(second);target=WorldTarget(UID,1);visibility=Visibility(set(a.planets),set(a.planets),set())
        self.assertNotEqual(a.data['universe']['definition_hash'],b.data['universe']['definition_hash'])
        self.assertEqual(fingerprint(a),fingerprint(b))
        self.assertEqual(public_definition(a,target,visibility),public_definition(b,target,visibility))

if __name__=='__main__':unittest.main()
