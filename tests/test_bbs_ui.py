import copy,io,json,unittest
from unittest.mock import patch
from starroute_bbs.menu import Menu,KEYS
from starroute_bbs.terminal import Terminal,width,ANSI
from starroute_bbs.client import ClientError,MUTATIONS
from starroute_bbs.screen import starmap,wrap
import tests.test_phase5 as baseline

class Backend:
    def __init__(self):
        self.calls=[];self.mutations=[];self.price=100;self.fail=None;self.lang='en'
        self.status={'handle':'操縦士 Pilot','cash':5000,'ship_id':'normal_2','season_id':1,'capacity':40,'used_capacity':2,
                     'planet_id':'001','planet_name':'Alvera','destination_id':None,'remaining_seconds':0,
                     'cargo':[{'goods_id':'grain','name':'星穀','quantity':2}]}
        self.rows=[{'goods_id':'grain' if i==0 else 'goods_'+str(i),'name':'商品'+str(i),'price':100,'stock':10,'volume':1} for i in range(30)]
        self.routes=[{'route_id':'r1','destination_id':'002','name':'Selnoa','distance':5,'seconds':60,'is_open':True},{'route_id':'r2','destination_id':'003','name':'Cartis','distance':8,'seconds':90,'is_open':False}]
    def language(self,value=None):
        if value:self.lang=value
        return self.lang
    def heartbeat(self):return {}
    def logout(self):pass
    def who(self):return {'players':[{'player':'Pilot','bbs':'Liner'}],'count':1}
    def call(self,op,args=None,request_id=None):
        args=args or {};self.calls.append((op,copy.deepcopy(args),request_id))
        if self.fail:raise ClientError(self.fail)
        if op in MUTATIONS:
            if self.status['destination_id'] and op!='register':raise ClientError('IN_TRANSIT')
            if op in ('buy','sell') and args.get('expected_total',self.price*args['quantity'])!=self.price*args['quantity']:raise ClientError('PRICE_CHANGED')
            self.mutations.append((op,copy.deepcopy(args),request_id))
            if op=='navigate':self.status['destination_id']=args['destination_id'];self.status['remaining_seconds']=60
            return {'paid_credits':args.get('paid_credits',100),'quantity':args.get('quantity',1)}
        if op=='status':return copy.deepcopy(self.status)
        if op=='flight':return {'position':[120,60],'origin_id':'001','destination_id':self.status['destination_id'],'remaining_seconds':self.status['remaining_seconds']}
        if op=='map':return {'definition':{'planets':[{'planet_id':'001','name':'Alvera','coordinates':{'x':120,'y':60}},{'planet_id':'002','name':'Selnoa','coordinates':{'x':125,'y':62}}]}}
        if op=='ui_info':return {'bbs':'Liner','insured':False,'ships':[{'ship_id':'normal_2','ship_type':'normal','grade':'2','capacity':40,'normal_speed':10,'max_warp_speed':20,'insurance_premium':200}],
            'warp_options':{'002':[{'level':'fast','speed':20}]},'restart':{'restart_ship':'normal_2','restart_cash':100},'flight':{'mode':'warp','level':'fast'}}
        if op=='market':return {'entries':copy.deepcopy(self.rows)}
        if op=='quote_trade':return {'side':args['side'],'goods_id':args['goods_id'],'quantity':args['quantity'],'unit_price':self.price,'total':self.price*args['quantity']}
        if op=='routes':return copy.deepcopy(self.routes)
        if op=='quote_navigation':return {**args,'seconds':30 if args['mode']=='warp' else 60,'fuel_cost':100 if args['mode']=='warp' else 0}
        if op=='development':return {'industries':[{'industry':i,'level':n} for n,i in enumerate(('primary','secondary','tertiary','quaternary'))]}
        if op=='shipyard':return [{'ship_id':'normal_2','price':1000,'capacity':40,'available':True}]
        if op=='news':return [{'event_id':str(i),'game_time':i,'kind':'route_open','values':{'reward':i}} for i in range(20)]
        if op in ('rankings','hall'):return [{'category':cat,'rank':1,'display_name':'Pilot','score':100,'round_id':1} for cat in ('trade','planet','route','exploration')]
        if op=='score':return {'trade_profit':50}
        return []

class UITests(unittest.TestCase):
    def setUp(self):
        self.b=Backend();self.t=Terminal(self.b,'en');self.m=Menu(self.t);self.m.refresh()
    def confirm(self):
        while self.m.state=='CONFIRM' and (self.m.page+1)*max(1,self.m.size()[0]-3)<len(self.m.data):self.m.handle('>')
        self.m.handle('Y')
    def test_startup_two_columns_and_bounds(self):
        lines=self.m.render();self.assertEqual(len(lines),23);self.assertTrue(all(width(x)<80 for x in lines))
        self.assertTrue(any('1 Status' in x and x.count('|')==3 for x in lines));self.assertIn('\x1b[32m*','\n'.join(lines))
    def test_all_main_keys(self):
        for key,action in KEYS:
            with self.subTest(key=key):
                m=Menu(self.t);m.refresh();m.handle(key.upper())
                self.assertNotEqual(m.notice,m.text('invalid_input'))
                if key not in ('t','q'):self.assertNotEqual(m.state,'MAIN')
                if key=='q':self.assertFalse(m.running)
    def test_main_menu_pages_keep_key_meanings(self):
        self.m.handle('>');self.assertIn('Q Quit','\n'.join(self.m.render()));self.m.handle('N');self.assertEqual(self.m.action,'news')
    def test_back_main_aliases(self):
        for key in ('0','back','menu','main','m'):
            self.m.main();self.m.handle('2');self.m.handle(key);self.assertEqual(self.m.state,'MAIN')
    def test_empty_refresh_never_mutates(self):
        self.m.handle('3');self.m.handle('1');self.m.handle('2');self.m.handle('');self.assertEqual(self.m.state,'CONFIRM');self.assertEqual(self.b.mutations,[])
    def test_cancel_no_mutation(self):
        for cancel in ('n','0','back','menu','m','q'):
            m=Menu(self.t);m.refresh();m.handle('3');m.handle('1');m.handle('2');m.handle(cancel)
        self.assertEqual(self.b.mutations,[])
    def test_buy_by_number_with_request_id_and_once(self):
        for line in ('3','1','2'):self.m.handle(line)
        self.assertEqual(self.b.mutations,[]);self.confirm();self.assertEqual(self.b.mutations[0][1],{'goods_id':'grain','quantity':2,'expected_total':200});self.assertTrue(self.b.mutations[0][2]);self.m.handle('y');self.assertEqual(len(self.b.mutations),1)
    def test_market_selection_and_sell_holdings(self):
        self.m.handle('2');self.m.handle('1');self.assertEqual(self.m.state,'QUANTITY');self.m.main();self.m.handle('4');self.assertEqual(len(self.m.data),1);self.m.handle('1');self.m.handle('1');self.confirm();self.assertEqual(self.b.mutations[-1][0],'sell')
    def test_paging_preserves_global_product_identity(self):
        self.m.handle('3');self.m.handle('n');shown,_=self.m.paged();n,row=shown[0];self.m.handle(str(n));self.m.handle('1');self.confirm();self.assertEqual(self.b.mutations[-1][1]['goods_id'],row['goods_id'])
    def test_offpage_selection_rejected(self):
        self.m.handle('3');self.m.handle('30');self.assertEqual(self.m.state,'SELECT');self.assertFalse(self.b.mutations)
    def test_prices_reconfirmed(self):
        self.m.handle('3');self.m.handle('1');self.m.handle('2');self.b.price=200;self.confirm();self.assertEqual(self.m.state,'CONFIRM');self.assertFalse(self.b.mutations);self.assertEqual(self.m.draft['arguments']['expected_total'],400);self.confirm();self.assertEqual(len(self.b.mutations),1)
    def test_normal_navigation_uses_quote(self):
        self.m.handle('6');self.m.handle('1');self.assertEqual(self.m.draft['quote']['fuel_cost'],0);self.assertFalse(self.b.mutations);self.confirm();self.assertTrue(self.m.in_flight)
    def test_warp_options_use_server(self):
        for line in ('7','1','1'):self.m.handle(line)
        self.assertIn('Selnoa',' '.join(self.m.data))
        self.assertEqual(self.m.draft['arguments']['level'],'fast');self.assertEqual(self.m.draft['quote']['seconds'],30);self.confirm();self.assertEqual(self.b.mutations[-1][0],'navigate')
        self.m.main();self.assertEqual(self.m.panel()[0],'MAIN MENU')
    def test_invest_donate_confirm(self):
        for key,op in (('8','invest'),('9','donate')):
            self.m.main();self.m.handle(key);self.m.handle('1');self.m.handle('100');self.assertEqual(self.m.draft['operation'],op);self.confirm()
        self.assertEqual(len(self.b.mutations),2)
    def test_ship_insurance_bankruptcy_confirm(self):
        self.m.handle('s');self.m.handle('1');self.assertFalse(self.b.mutations);self.confirm();self.m.main();self.m.handle('i');self.confirm();self.m.main();self.m.handle('1');self.m.handle('b');self.assertIn('discards',' '.join(self.m.data));self.confirm();self.assertEqual([r[0] for r in self.b.mutations],['buy_ship','insure','bankrupt'])
    def test_bare_bankrupt_command_requires_confirmation(self):
        self.m.handle('bankrupt');self.assertFalse(self.b.mutations);self.assertEqual(self.m.state,'CONFIRM')
    def test_language_and_product_names(self):
        self.m.handle('l');self.m.handle('1');self.m.handle('2');text='\n'.join(self.m.render());self.assertIn('星穀',text);self.assertNotIn('grain',text);self.assertEqual(self.b.lang,'ja')
    def test_names_always_english(self):
        self.t.language='ja';self.m.handle('t');self.assertIn('Alvera','\n'.join(self.m.render()));self.m.handle('t');self.assertNotIn('Alvera','\n'.join(self.m.render()[:18]))
    def test_flight_menu_and_restrictions(self):
        self.b.status['destination_id']='002';self.b.status['remaining_seconds']=60;self.m.refresh()
        self.assertIn('W WHO','\n'.join(self.m.render()));self.assertIn('\x1b[32m+','\n'.join(self.m.render()))
        for line in ('3','8','9','s','i','bankrupt','buy grain 1','go 002'):
            self.m.handle(line);self.assertEqual(self.m.state,'MAIN')
        self.assertFalse(self.b.mutations);self.m.handle('w');self.assertIn('Liner',' '.join(self.m.data))
    def test_news_reverse_order_and_paging(self):
        self.m.handle('n');self.assertIn('19',' '.join(self.m.data[:2]));self.assertGreater(self.m.paged()[1],1)
    def test_ranking_and_hall_categories(self):
        for key in ('r','h'):
            self.m.main();self.m.handle(key);self.m.handle('2');self.assertTrue(any('Planet development' in r for r in self.m.data))
    def test_help_and_errors(self):
        self.m.handle('?');self.assertEqual(self.m.action,'help');self.assertTrue(any('Trade:' in x for x in self.m.data));self.m.main();self.m.handle('buy grain');self.assertIn('buy grain 5',self.m.notice);self.m.handle('nonsense');self.assertIn('?',self.m.notice)
    def test_cli_trade_preserved(self):
        self.m.handle('buy grain 2');self.assertEqual(self.m.state,'CONFIRM');self.confirm();self.assertEqual(self.b.mutations[0][1]['quantity'],2)
    def test_cli_display_legacy_commands(self):
        for cmd in ('status','market','routes','map','flight','news','WHO','score','rankings','hall','production','development','exploration','rounds','language en','color off','names on'):
            self.m.main();self.m.handle(cmd);self.assertNotEqual(self.m.notice,self.m.text('invalid_input'))
    def test_amount_validation(self):
        self.m.handle('3');self.m.handle('1')
        for x in ('-1','abc','1.5',str(2**63),'１'):self.m.handle(x);self.assertEqual(self.m.state,'QUANTITY')
        self.assertFalse(self.b.mutations)
        self.m.handle('0');self.assertEqual(self.m.state,'SELECT')
    def test_help_during_confirmation_preserves_unexecuted_draft(self):
        self.m.handle('3');self.m.handle('1');self.m.handle('1');self.m.handle('?');self.m.handle('0');self.assertEqual(self.m.state,'CONFIRM');self.assertFalse(self.b.mutations);self.confirm();self.assertEqual(len(self.b.mutations),1)
    def test_offline_confirm_keeps_backend_authority(self):
        self.m.handle('3');self.m.handle('1');self.m.handle('1');self.b.fail='MASTER_UNAVAILABLE';self.confirm();self.assertFalse(self.b.mutations);self.assertFalse(self.m.online)
    def test_all_sizes_languages_states(self):
        for cols,rows in ((80,24),(100,30),(60,24),(79,24),(59,24),(40,20),(20,12)):
            for lang in ('ja','en'):
                self.t.columns=cols;self.t.rows=rows;self.t.language=lang
                for action in ('status','market','buy','routes','news','rankings','help'):
                    self.m.main();self.m.open(action);lines=self.m.render();self.assertLessEqual(len(lines),rows-1);self.assertTrue(all(width(x)<cols for x in lines),(cols,rows,lines))
    def test_monochrome_has_no_escape_sequences(self):
        self.t.ansi=False;self.assertNotIn('\x1b','\n'.join(self.m.render()))
    def test_pure_render_does_not_call_api(self):
        before=len(self.b.calls)
        for _ in range(5):self.m.render()
        self.assertEqual(len(self.b.calls),before)
    def test_map_center_matches_ship(self):
        lines=starmap(self.m.definition,self.m.flight,{'destination_id':'002'},31,11,True,False)
        self.assertEqual(lines[5][17],'+')  # Four axis cells + centered 26-cell viewport.

class UIServerTests(unittest.TestCase):
    setUp=baseline.Phase5Tests.setUp
    stop_server=baseline.Phase5Tests.stop_server
    client=baseline.Phase5Tests.client
    logged=baseline.Phase5Tests.logged
    good=baseline.Phase5Tests.good
    @classmethod
    def setUpClass(cls):baseline.Phase5Tests.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):baseline.Phase5Tests.tearDownClass.__func__(cls)
    def test_ui_metadata_private_projection_and_rule_hash_unchanged(self):
        a=self.logged();ref=copy.deepcopy(a.reference);v=a.call('ui_info');self.assertIn('insurance_premium',v['ships'][0]);self.assertIn('warp_options',v)
        for secret in ('private_caps','maximum_level','seed','resources','probabilities'):self.assertNotIn(secret,json.dumps(v))
        self.assertEqual(a.reference,ref)
    def test_who_in_flight_is_readonly(self):
        a=self.logged();r=next(x for x in a.call('routes') if x['is_open']);a.call('navigate',{'destination_id':r['destination_id'],'mode':'normal','level':None})
        before=[tuple(x) for x in self.m.c.execute('SELECT * FROM player_state')];self.assertEqual(a.who()['count'],1)
        self.assertEqual(before,[tuple(x) for x in self.m.c.execute('SELECT * FROM player_state')]);a.call('ui_info')
    def test_atomic_total_changed_no_purchase(self):
        a=self.logged();good=self.good(a);q=a.call('quote_trade',{'goods_id':good,'quantity':1,'side':'buy'});before=a.call('status')
        with self.assertRaises(ClientError) as e:a.call('buy',{'goods_id':good,'quantity':1,'expected_total':q['total']+1},'stale-price')
        self.assertEqual(e.exception.code,'PRICE_CHANGED');self.assertEqual(a.call('status'),before)
    def test_confirmed_total_idempotent(self):
        a=self.logged();good=self.good(a);q=a.call('quote_trade',{'goods_id':good,'quantity':1,'side':'buy'});args={'goods_id':good,'quantity':1,'expected_total':q['total']}
        one=a.call('buy',args,'confirmed-buy');self.assertEqual(a.call('buy',args,'confirmed-buy'),one);self.assertEqual(a.call('status')['cargo'][0]['quantity'],1)
    def test_menu_real_buy_sell(self):
        a=self.logged();m=Menu(Terminal(a,'en'));m.refresh();m.handle('3');m.handle('1');m.handle('1');m.handle('y')
        self.assertEqual(m.state,'TEXT',m.notice);self.assertEqual(len(a.call('status')['cargo']),1)
        m.main();m.handle('4');m.handle('1');m.handle('1');m.handle('y');self.assertEqual(a.call('status')['cargo'],[])
    def test_metadata_requires_auth_and_target(self):
        a=self.logged();a.token='invalid'
        with self.assertRaises(ClientError):a.call('ui_info')
    def test_ui_info_does_not_advance_game_time(self):
        a=self.logged();before=self.m.repo._load();self.clock.advance(10);a.call('ui_info');after=self.m.repo._load();self.assertEqual(before.game_time,after.game_time)
