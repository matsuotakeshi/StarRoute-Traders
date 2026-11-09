import copy,json,tempfile,unittest,concurrent.futures
from pathlib import Path
from unittest.mock import patch
from srt_universe_generator.levels import generate
from starroute.catalog import Catalog
from starroute.universe import seal_manifest
from starroute.universe_package import export_package,to_catalog,digest
from starroute.rules import fingerprint
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.model import GameError
from starroute.master import public_definition,WorldTarget,Visibility
from starroute.hidden_world import economic_catalog
from starroute.operations import Manager,initialize
ROOT=Path(__file__).resolve().parents[1]

def inputs():
    return tuple(json.loads((ROOT/'examples'/n).read_text(encoding='utf8')) for n in ('market-buyback-trial.json','connected-universe-trial.json','industry-levels-trial.json'))

def reachable(data,opened=True):
    seen={data['planets'][0]['id']}
    while True:
        old=len(seen)
        for r in data['routes']:
            if (not opened or r['is_open']) and ({r['from'],r['to']} & seen):seen.update((r['from'],r['to']))
        if len(seen)==old:return seen

class ConnectedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=generate(*inputs(),'connected-tests')
        cls.package=export_package(cls.data)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'game.db'
    def app(self,data=None):
        r=SQLiteRepository(self.path,Catalog(data or self.data),now=100);self.addCleanup(r.close)
        return Application(r,ManualClock(100))
    def test_connected_across_seeds(self):
        for seed in range(8):
            d=generate(*inputs(),'connected-'+str(seed))
            self.assertEqual(len(d['planets']),48)
            self.assertEqual(len(reachable(d)),48)
            self.assertEqual(sum(r['is_open'] for r in d['routes']),47)
            self.assertTrue(any(not r['is_open'] for r in d['routes']))
            self.assertEqual(len({r['id'] for r in d['planets']}),48)
    def test_shortcut_reduces_tree_detour(self):
        graph={p['id']:[] for p in self.data['planets']}
        for r in self.data['routes']:
            if r['is_open']:
                graph[r['from']].append((r['to'],r['distance']));graph[r['to']].append((r['from'],r['distance']))
        def path(a,b):
            todo=[(a,None,0)]
            while todo:
                node,parent,n=todo.pop()
                if node==b:return n
                todo.extend((q,node,n+w) for q,w in graph[node] if q!=parent)
        self.assertTrue(any(r['distance']<path(r['from'],r['to']) for r in self.data['routes'] if not r['is_open']))
    def test_closed_route_denied_and_donation_opens_once(self):
        a=self.app();r=next(r for r in self.data['routes'] if not r['is_open'])
        with patch('secrets.choice',return_value=r['from']):a.create_player('p','P')
        with self.assertRaises(GameError):a.navigate('p',r['to'])
        with a.repository.transaction() as w:w.players['p'].cash=100000000
        result=a._call('donate','p',r['id'],1000000,request_id='donate-once')
        self.assertTrue(result['opened'])
        self.assertEqual(result,a._call('donate','p',r['id'],1000000,request_id='donate-once'))
        self.assertTrue(next(x for x in a.get_routes('p') if x['route_id']==r['id'])['is_open'])
    def test_random_all_normal_candidates_and_saved(self):
        a=self.app()
        with patch('secrets.choice',return_value='048') as choose:
            result=a.create_player('p','P',request_id='register-once')
            self.assertEqual(choose.call_args.args[0],[f'{n:03}' for n in range(1,49)])
            self.assertEqual(result,a.create_player('p','P',request_id='register-once'));choose.assert_called_once()
        self.assertEqual(a.get_player('p')['planet_id'],'048')
        self.assertEqual(a.repository._load().phase3_state['initial_planets']['p'],'048')
        a.repository.close();r=SQLiteRepository(self.path);self.addCleanup(r.close)
        self.assertEqual(Application(r,ManualClock(100)).get_player('p')['planet_id'],'048')
    def test_independent_players_and_sites(self):
        a=self.app()
        with patch('secrets.choice',side_effect=['001','048']) as choose:
            one=a.create_account('bbs_a','1','Same');two=a.create_account('bbs_b','1','Same')
        self.assertEqual(choose.call_count,2);self.assertNotEqual(one['player_id'],two['player_id'])
        self.assertEqual((one['planet_id'],two['planet_id']),('001','048'))
        self.assertEqual(a.get_player(one['player_id'])['planet_id'],'001')
    def test_concurrent_registration_one_draw(self):
        a=self.app();a.repository.close()
        def register(_):
            r=SQLiteRepository(self.path)
            try:return Application(r,ManualClock(100)).create_account('bbs','same','P',request_id='same')
            finally:r.close()
        with patch('secrets.choice',return_value='024') as choose:
            with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(register,range(2)))
        self.assertEqual(results[0],results[1]);choose.assert_called_once()
    def test_legacy_start_and_hash_unchanged(self):
        template,params,levels=inputs();params=json.loads((ROOT/'examples/phase3-generator.json').read_text())
        d=generate(template,params,levels,'legacy');a=self.app(d)
        before=fingerprint(a.repository.catalog)
        with patch('secrets.choice',side_effect=AssertionError('legacy draw')):a.create_player('p','P')
        self.assertEqual(a.get_player('p')['planet_id'],d['starting']['planet_id'])
        self.assertEqual(before,fingerprint(a.repository.catalog))
    def test_hidden_placement_and_configurable_distances(self):
        for minimum,maximum in [(10,40),(15,30)]:
            t,p,l=inputs();p.update(hidden_min_distance=minimum,hidden_reference_max_distance=maximum)
            d=generate(t,p,l,'distance');h=d['universe']['private_world'];xy=h['position']
            distances={r['planet_id']:max(abs(xy['x']-r['x']),abs(xy['y']-r['y'])) for r in d['universe']['coordinates']}
            self.assertGreaterEqual(min(distances.values()),minimum)
            self.assertLessEqual(distances[h['reference_planet_id']],maximum)
            self.assertNotIn(h['planet_id'],{r['id'] for r in d['planets']})
    def test_impossible_constraints_fail(self):
        t,p,l=inputs();p.update(hidden_min_distance=41,hidden_reference_max_distance=40,max_attempts=1)
        with self.assertRaises(ValueError):generate(t,p,l,'impossible')
    def test_hidden_economy_uses_ordinary_engine(self):
        c=economic_catalog(self.data);d=copy.deepcopy(c.data);d['starting']['planet_id']='hidden-001'
        a=self.app(d);a.create_player('p','P')
        self.assertEqual(len(a.get_market('p')['entries']),30)
        row=next(r for r in a.get_market('p')['entries'] if r['max_buy']>0)
        a.buy_goods('p',row['goods_id'],1);a.sell_goods('p',row['goods_id'],1)
        self.assertEqual(a.get_player('p')['cargo'],[])
        self.assertEqual(len(a.get_development('p')['industries']),4)
    def test_hidden_api_and_public_hash_exclusion(self):
        c=Catalog(self.data);target=WorldTarget(c.data['universe']['universe_id'],1)
        ids=frozenset(c.planets)|{'hidden-001'};v=Visibility(ids,ids,frozenset(r['id'] for r in c.data['routes']))
        public=public_definition(c,target,v);encoded=json.dumps(public)
        for forbidden in ('hidden-001','private_world','private_caps','seed','reference_planet_id'):self.assertNotIn(forbidden,encoded)
        modified=copy.deepcopy(self.data);h=modified['universe']['private_world'];ind='primary'
        h['development']['initial_progress'][ind]=(h['development']['initial_progress'][ind]+1)%(h['development']['private_caps'][ind]+1)
        coords={r['planet_id']:(r['x'],r['y']) for r in modified['universe']['coordinates']}
        ref=coords[h['reference_planet_id']];old=h['position']
        point=next((x,y) for x in range(240) for y in range(120)
                   if (x,y)!=(old['x'],old['y']) and max(abs(x-ref[0]),abs(y-ref[1]))<=40
                   and all(max(abs(x-a),abs(y-b))>=10 for a,b in coords.values()))
        h['position']={'x':point[0],'y':point[1]}
        seal_manifest(modified);other=Catalog(modified)
        self.assertEqual(public,public_definition(other,target,v));self.assertEqual(fingerprint(c),fingerprint(other))
        self.assertNotEqual(c.data['universe']['definition_hash'],other.data['universe']['definition_hash'])
        a=self.app();a.create_player('p','P')
        with self.assertRaises(GameError):a.get_market('p','hidden-001')
        with self.assertRaises(GameError):a.navigate('p','hidden-001')
    def test_package_roundtrip_and_tamper_rejection(self):
        self.assertEqual(self.package['schema_version'],3)
        self.assertEqual(to_catalog(self.package).data,self.data)
        for part in ('position','buyback'):
            p=copy.deepcopy(self.package)
            if part=='position':p['private_world']['position']['x']=-1
            else:p['private_world']['buyback']['grain']=-1
            p['integrity']['sha256']=digest(p)
            with self.assertRaises((ValueError,GameError)):to_catalog(p)
    def test_invalid_connected_policy_rejected(self):
        for key,value in [('initial_open_routes',46),('extra_neighbors',0),('hidden_min_distance',True)]:
            t,p,l=inputs();p[key]=value
            with self.assertRaises((ValueError,GameError)):generate(t,p,l,'invalid')
    def test_registry_and_round_switch_preserve_private_data(self):
        initialize(self.path,100);m=Manager(self.path,100);self.addCleanup(m.close)
        uid=m.stage(json.dumps(self.package).encode());m.register(uid);m.prepare(uid,1,100);m.activate(1,uid)
        self.assertEqual(m.repo.catalog.data['universe']['private_world'],self.data['universe']['private_world'])
        r=SQLiteRepository(self.path);a=Application(r,ManualClock(100));a.create_account('bbs','1','P');r.close()
        second=export_package(generate(*inputs(),'round-two'));uid2=m.stage(json.dumps(second).encode());m.register(uid2)
        self.assertEqual(m.repo.catalog.data['universe']['universe_id'],uid)
        m.prepare(uid2,2,100);m.activate(2,uid2,1,uid)
        self.assertEqual(m.repo.catalog.data['universe']['private_world'],to_catalog(second).data['universe']['private_world'])
        self.assertEqual(m.archive(1)['catalog'],Catalog(self.data).canonical())
        self.assertEqual(m.inspect()['integrity'],['ok'])

if __name__=='__main__':unittest.main()
