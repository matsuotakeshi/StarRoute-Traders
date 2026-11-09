import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_connected_universe import inputs
from srt_universe_generator.levels import generate
from starroute.catalog import Catalog
from starroute.universe_package import export_package,to_catalog
from starroute.repository import SQLiteRepository
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.model import GameError
from starroute.exploration import player_state,coordinates,distance,HIDDEN
ROOT=Path(__file__).resolve().parents[1]

def exploration_data(seed='exploration-tests'):
    _,params,levels=inputs()
    template=json.loads((ROOT/'examples/exploration-trial.json').read_text(encoding='utf8'))
    # Deterministic tests disable unrelated ship events; storm interpolation is injected separately.
    for key in ('pirate','patrol','storm','failure','wreck'):template['phase3']['event_probabilities'][key]=0
    return generate(template,params,levels,seed)

class ExplorationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.data=exploration_data()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'game.db';self.clock=ManualClock(100)
        self.repo=SQLiteRepository(self.path,Catalog(self.data),now=100);self.addCleanup(self.repo.close)
        self.a=Application(self.repo,self.clock)
        with patch('secrets.choice',return_value='001'):self.a.create_player('p','Pilot')
        with self.repo.transaction() as w:w.players['p'].cash=2000000
        self.a.engine.random_below=lambda n:n-1
    def call(self,op,*args,**kw):return self.a._call(op,'p',*args,**kw)
    def device(self):return self.call('buy_device',request_id='device')
    def quote(self,xy,mode='normal',level=None):return self.call('coordinate_quote',*xy,mode,level)
    def depart(self,xy,mode='normal',level=None):
        q=self.quote(xy,mode,level)
        return self.call('coordinate_depart',*xy,mode,level,q['quote_id'],request_id='voyage-'+str(self.clock.now()))
    def arrive(self,xy):
        q=self.depart(xy);self.clock.value=q['arrival_at'];self.a.get_player('p');return self.repo._load()
    def hidden(self):return coordinates(self.repo.catalog)[HIDDEN]
    def test_package_four_and_runtime_market_separation(self):
        p=export_package(self.data);c=to_catalog(p)
        self.assertEqual(len(c.data['planets']),48);self.assertEqual(len(c.planets),49)
        self.assertEqual(len(self.repo._load().markets),49*30)
    def test_device_exact_price_replay_and_duplicate(self):
        result=self.device();self.assertEqual(result['paid_credits'],1000000)
        self.assertEqual(self.device(),result);self.assertEqual(self.a.get_player('p')['cash'],1000000)
        with self.assertRaises(GameError):self.call('buy_device',request_id='again')
    def test_device_insufficient_and_all_ship_types(self):
        for sid in self.repo.catalog.ships:
            with self.repo.transaction() as w:
                w.players['p'].cash=999999;w.players['p'].ship_id=sid;player_state(w,'p')['device']=False
            with self.assertRaises(GameError):self.call('buy_device')
            with self.repo.transaction() as w:w.players['p'].cash=1000000
            self.call('buy_device');self.assertEqual(self.a.get_player('p')['cash'],0)
    def test_device_required_and_invalid_coordinates(self):
        with self.assertRaises(GameError):self.quote([0,0])
        self.device()
        for xy in ([-1,0],[240,0],[0,120],[True,1],[1.5,2],['1',2]):
            with self.subTest(xy=xy),self.assertRaises((GameError,ValueError)):self.quote(xy)
    def test_offroute_half_speed_and_warp_independent_goods(self):
        self.device();xy=[0,0];q=self.quote(xy)
        p=self.repo._load().players['p'];plan=next(r for r in self.data['universe']['template']['navigation']['plans'] if r['ship_id']==p.ship_id)
        units=sum(abs(v) for v in q['origin']);self.assertEqual(q['seconds'],plan['normal_seconds']*max(units,5)*2);self.assertEqual(q['fuel_cost'],0)
        option=plan['warp_options'][0];before=self.quote(xy,'warp',option['level'])
        with self.repo.transaction() as w:
            for (pid,g),m in w.markets.items():
                if 'fuel' in g:m.stock=0;m.price=9999
            w.players['p'].cargo['fusion_fuel']=1
        self.assertEqual(before,self.quote(xy,'warp',option['level']))
        self.depart(xy,'warp',option['level']);self.assertEqual(self.repo._load().players['p'].cargo['fusion_fuel'],1)
    def test_empty_space_zero_cash_return_and_reopen(self):
        self.device();self.arrive([0,0]);self.assertIsNone(self.a.get_player('p')['planet_id'])
        with self.assertRaises(GameError):self.a.get_market('p')
        with self.repo.transaction() as w:w.players['p'].cash=0
        xy=coordinates(self.repo.catalog)['001'];q=self.depart(xy)
        self.repo.close();self.clock.value=q['arrival_at'];self.repo=SQLiteRepository(self.path);self.addCleanup(self.repo.close);self.a=Application(self.repo,self.clock)
        self.assertEqual(self.a.get_player('p')['planet_id'],'001');self.assertEqual(self.a.get_player('p')['cash'],0)
    def test_arrival_discovery_and_personal_name_reopen(self):
        self.device();self.arrive(self.hidden());self.assertTrue(self.call('explorer_info')['naming_pending'])
        self.repo.close();self.repo=SQLiteRepository(self.path);self.addCleanup(self.repo.close);self.a=Application(self.repo,self.clock)
        self.assertTrue(self.call('explorer_info')['naming_pending'])
        self.call('name_star','私のMiXeD星',request_id='name');self.assertEqual(self.a.get_player('p')['planet_name'],'私のMiXeD星')
        self.assertEqual(self.call('name_star','私のMiXeD星',request_id='name'),{'personal_name':'私のMiXeD星'})
        with self.assertRaises(GameError):self.call('name_star','Other')
        self.arrive(coordinates(self.repo.catalog)['001']);self.arrive(self.hidden());self.assertEqual(len(self.call('discoverers')),1)
    def test_name_validation_and_twenty_japanese_characters(self):
        self.device();self.arrive(self.hidden())
        for name in ('',' ','a'*21,'a\n','x\x1b','x\u202e'):
            with self.assertRaises(GameError):self.call('name_star',name)
        self.call('name_star','星'*20)
    def test_hints_chebyshev_boundaries(self):
        self.device();x,y=self.hidden()
        for d,want in ((1,'bright'),(2,'strong'),(3,'strong'),(4,'faint'),(5,'faint'),(6,None)):
            xy=[x+(d if x+d<240 else -d),y+(d if y+d<120 else -d)]
            self.arrive(xy);self.assertEqual(self.call('explorer_info')['hint'],want);self.assertFalse(self.call('explorer_info')['found'])
    def test_no_discovery_while_passing_hidden(self):
        self.device();x,y=self.hidden()
        with self.repo.transaction() as w:player_state(w,'p').update(space=True,position=[x-1 if x else x+1,y])
        target=[x+1 if x else x+2,y];q=self.depart(target);self.clock.advance(q['seconds']//2)
        self.a.get_player('p');self.assertFalse(player_state(self.repo._load(),'p')['found_at'])
        self.clock.value=q['arrival_at'];self.a.get_player('p');self.assertFalse(self.call('explorer_info')['found'])
    def test_storm_position_does_not_reverse(self):
        self.device();q=self.depart([239,119]);self.clock.advance(q['seconds']//2);self.a.get_player('p')
        with self.repo.transaction() as w:
            before=self.a.engine.flight(w,'p')['position'];__import__('starroute.mechanics',fromlist=['apply_event']).apply_event(self.a.engine,w,'storm-test','storm','p');after=self.a.engine.flight(w,'p')['position']
        self.assertEqual(before,after)
    def test_guild_truth_boundary_cost_replay_and_notebook(self):
        for draw,expected in ((1999,True),(2000,False)):
            self.a.engine.random_below=lambda n,v=draw:v if n==10000 else 0
            result=self.call('guild',request_id='guild'+str(draw));self.assertNotIn('truth',result['rumor'])
            self.assertEqual(result,self.call('guild',request_id='guild'+str(draw)))
            row=player_state(self.repo._load(),'p')['notebook'][-1];self.assertEqual(row['truth'],expected)
            self.assertEqual(distance(coordinates(self.repo.catalog)[row['planet_id']],self.hidden())<=40,expected)
        self.assertEqual(self.a.get_player('p')['cash'],1999800)
        self.assertEqual([r['id'] for r in self.call('notebook')],[2,1])
    def test_guild_insufficient_funds_no_draw(self):
        with self.repo.transaction() as w:w.players['p'].cash=99
        self.a.engine.random_below=lambda n:(_ for _ in ()).throw(AssertionError('draw'))
        with self.assertRaises(GameError):self.call('guild')
    def test_trade_rumor_only_success_and_replay(self):
        draws=[]
        def draw(n):draws.append(n);return 0
        self.a.engine.random_below=draw
        with self.assertRaises(GameError):self.a.buy_goods('p','grain',999999)
        self.assertEqual(draws,[])
        result=self.a.buy_goods('p','grain',1,request_id='buy');count=len(draws)
        self.assertIn('rumor',result);self.assertEqual(self.a.buy_goods('p','grain',1,request_id='buy'),result);self.assertEqual(len(draws),count)
    def test_bankruptcy_loses_device(self):
        self.device();self.call('bankrupt');self.assertFalse(self.call('explorer_info')['device'])
    def test_undiscovered_market_rejected(self):
        with self.assertRaises(GameError):self.a.get_market('p',HIDDEN)
    def test_two_players_shared_market_and_all_arrivals(self):
        self.device();self.arrive(self.hidden());self.call('name_star','Same')
        for n in range(4):
            pid='other'+str(n);self.a.create_player(pid,pid)
            with self.repo.transaction() as w:w.players[pid].cash=2000000
            self.a._call('buy_device',pid)
            q=self.a._call('coordinate_quote',pid,*self.hidden(),'normal',None)
            self.a._call('coordinate_depart',pid,*self.hidden(),'normal',None,q['quote_id']);self.clock.advance(q['seconds']);self.a.get_player(pid)
            self.a._call('name_star',pid,'Same')
        self.assertEqual(len(self.call('discoverers')),5)
        row=next(r for r in self.a.get_market('p')['entries'] if r['stock']>0);good=row['goods_id'];stock=row['stock']
        self.a.buy_goods('other0',good,1)
        self.assertEqual(next(r for r in self.a.get_market('p')['entries'] if r['goods_id']==good)['stock'],stock-1)
    def test_changed_hint_thresholds_and_rules_hash(self):
        from starroute.rules import fingerprint
        template,params,levels=inputs();template=json.loads((ROOT/'examples/exploration-trial.json').read_text(encoding='utf8'))
        before=fingerprint(Catalog(template));template['exploration']['hint_thresholds']=[2,4,6]
        self.assertNotEqual(before['sha256'],fingerprint(Catalog(template))['sha256'])
        self.a.engine.catalog.exploration['hint_thresholds']=[2,4,6]
        self.device();x,y=self.hidden();self.arrive([x+2 if x+2<240 else x-2,y]);self.assertEqual(self.call('explorer_info')['hint'],'bright')
    def test_ship_purchase_preserves_device(self):
        self.device()
        with self.repo.transaction() as w:
            w.players['p'].cash=100000000
            planet=w.players['p'].planet_id
            for ind in ('primary','secondary','tertiary','quaternary'):w.developments[planet,ind]=self.repo.catalog.development_planets[planet]['private_caps'][ind]
        row=next(r for r in self.call('shipyard') if r['available'] and r['ship_id']!=self.a.get_player('p')['ship_id'])
        self.call('buy_ship',row['ship_id']);self.assertTrue(self.call('explorer_info')['device'])
    def test_departure_rumor_replay_and_quote_no_draw(self):
        self.device();draws=[]
        def draw(n):draws.append(n);return 0
        self.a.engine.random_below=draw;q=self.quote([0,0]);self.assertEqual(draws,[])
        args=(0,0,'normal',None,q['quote_id']);r=self.call('coordinate_depart',*args,request_id='departure')
        self.assertIn('rumor',r);count=len(draws);self.assertEqual(self.call('coordinate_depart',*args,request_id='departure'),r);self.assertEqual(len(draws),count)
    def test_duplicate_rumors_retained_and_other_player_isolated(self):
        self.a.engine.random_below=lambda n:0
        self.call('guild');self.call('guild');rows=self.call('notebook');self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['template'],rows[1]['template']);self.assertEqual(rows[0]['planet_id'],rows[1]['planet_id'])
        self.a.create_player('other','Other');self.assertEqual(self.a._call('notebook','other'),[])
    def test_quote_cannot_be_used_after_ship_or_origin_change(self):
        self.device();q=self.quote([0,0])
        with self.repo.transaction() as w:w.players['p'].ship_id=next(s for s in self.repo.catalog.ships if s!=w.players['p'].ship_id)
        with self.assertRaises(GameError):self.call('coordinate_depart',0,0,'normal',None,q['quote_id'])
    def test_simultaneous_arrivals_are_recorded_once_in_stable_order(self):
        import concurrent.futures
        self.device();self.a.create_player('a','Other')
        with self.repo.transaction() as w:
            w.players['a'].cash=2000000;w.players['a'].planet_id=w.players['p'].planet_id
        self.a._call('buy_device','a')
        for pid in ('p','a'):
            q=self.a._call('coordinate_quote',pid,*self.hidden(),'normal',None)
            self.a._call('coordinate_depart',pid,*self.hidden(),'normal',None,q['quote_id'])
        self.clock.advance(q['seconds'])
        def settle(pid):
            r=SQLiteRepository(self.path)
            try:return Application(r,self.clock).get_player(pid)
            finally:r.close()
        with concurrent.futures.ThreadPoolExecutor(2) as pool:list(pool.map(settle,('p','a')))
        rows=self.call('discoverers');self.assertEqual([r['player_id'] for r in rows],['a','p']);self.assertEqual([r['rank'] for r in rows],[1,2])
