import unittest,copy
from tests.test_bbs_ui import Backend
from starroute_bbs.menu import Menu
from starroute_bbs.terminal import Terminal,width
class ExplorerBackend(Backend):
    def call(self,op,args=None,request_id=None):
        if op=='ui_info':
            return {**super().call(op,args,request_id),'exploration':{'device':True,'device_price':1000000,'guild_price':100,'coordinate_warps':['fast'],'naming_pending':getattr(self,'pending_name',False)}}
        if op=='coordinate_quote':return {**args,'quote_id':'quote','seconds':20,'fuel_cost':0}
        if op=='nearby':return [{'name':'Alvera','planet_id':'001','x':0,'y':0,'distance':1}]
        if op=='notebook':return [{'id':i,'at':i,'template':0,'planet_id':'001','planet_name':'Alvera'} for i in range(20,0,-1)]
        return super().call(op,args,request_id)
class ExplorationUITests(unittest.TestCase):
    def setUp(self):self.b=ExplorerBackend();self.t=Terminal(self.b,'en');self.m=Menu(self.t);self.m.refresh()
    def confirm(self):
        while (self.m.page+1)*max(1,self.m.size()[0]-3)<len(self.m.data):self.m.handle('>')
        self.m.handle('y')
    def test_zero_coordinates_confirm_cancel_and_single_call(self):
        for value in ('E','2','0','0','1'):self.m.handle(value)
        self.assertEqual(self.m.state,'CONFIRM');self.assertEqual(self.b.mutations,[])
        self.confirm();self.assertEqual(self.b.mutations[-1][0],'coordinate_depart')
        self.assertEqual(self.b.mutations[-1][1]['x'],0);self.assertEqual(self.b.mutations[-1][1]['y'],0)
    def test_case_sensitive_name_and_command_words_are_literal(self):
        self.m.handle('e');self.m.handle('6');self.assertEqual(self.m.echo('MiXeD星'),'MiXeD星')
        self.m.handle('MiXeD星');self.confirm();self.assertEqual(self.b.mutations[-1][1],{'value':'MiXeD星'})
        self.m.main();self.m.handle('e');self.m.handle('6');self.m.handle('quit');self.assertTrue(self.m.running);self.assertEqual(self.m.draft['arguments']['value'],'quit')
    def test_pending_name_notice_and_bilingual_bounds(self):
        for lang in ('en','ja'):
            self.t.language=lang
            for columns,rows in ((80,24),(60,24),(40,24),(120,40)):
                self.t.columns=columns;self.t.rows=rows
                for action in ('explore','coordinates','notebook','return_planet','name_star'):
                    self.m.main();self.m.open(action);lines=self.m.render();self.assertLess(len(lines),rows);self.assertTrue(all(width(l)<columns for l in lines))
    def test_notebook_paging_and_cancel_no_charge(self):
        self.m.open('notebook');self.m.handle('n');self.assertEqual(self.m.page,1)
        self.m.main();self.m.open('guild');self.m.handle('');self.assertEqual(self.b.mutations,[]);self.m.handle('n');self.assertEqual(self.b.mutations,[])
    def test_exploration_blocked_in_flight(self):
        self.b.status['destination_id']='coordinates';self.m.refresh();self.m.handle('e');self.assertEqual(self.b.mutations,[]);self.assertNotEqual(self.m.state,'EXPLORE')

    def test_arrival_and_reconnect_open_naming_without_repeating_after_cancel(self):
        self.b.pending_name=True;self.m.refresh();self.assertEqual(self.m.state,'STAR_NAME')
        self.m.handle(':cancel');self.m.main();self.assertEqual(self.m.state,'MAIN')
        fresh=Menu(self.t);fresh.refresh();self.assertEqual(fresh.state,'STAR_NAME')

    def test_japanese_star_name_does_not_overwrite_ship_or_exceed_cells(self):
        from starroute_bbs.screen import starmap
        rows=starmap({'planets':[{'planet_id':'hidden-001','name':'星'*20,'coordinates':{'x':110,'y':60}}]}, {'position':[112,60]}, {'destination_id':'coordinates'},40,12,True,False)
        self.assertTrue(all(width(row)==40 for row in rows));self.assertEqual(sum(row.count('+') for row in rows),1)
