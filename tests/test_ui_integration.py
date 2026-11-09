import copy,json,tempfile,unittest
from pathlib import Path
from tests.test_bbs_ui import Backend
from tests.test_exploration_ui import ExplorerBackend
from starroute_bbs.menu import Menu
from starroute_bbs.terminal import Terminal,width,ANSI
from starroute_bbs.screen import starmap
from starroute.catalog import Catalog
from starroute.phase4_db import policy
from starroute.rules import fingerprint
ROOT=Path(__file__).resolve().parents[1]
class IntegratedBackend(ExplorerBackend):
    def call(self,op,args=None,request_id=None):
        if op=='trade_history':
            self.calls.append((op,args,request_id))
            return {'entries':[{'sequence':2,'game_time':100,'planet_name':'Alvera','goods_id':'grain','side':'sell','quantity':2,'first_unit_price':10,'last_unit_price':9,'total':19}], 'next_before':2 if args['before'] is None else None}
        if op=='quote_navigation':return {**super().call(op,args,request_id),'origin_id':'001','distance':5,'estimated_arrival_at':160}
        if op=='coordinate_quote':return {**super().call(op,args,request_id),'origin':[120,60],'distance':12,'estimated_arrival_at':120}
        return super().call(op,args,request_id)
class IntegratedUITests(unittest.TestCase):
    def setUp(self):self.b=IntegratedBackend();self.t=Terminal(self.b,'en');self.m=Menu(self.t);self.m.refresh()
    def confirm(self):
        while (self.m.page+1)*max(1,self.m.size()[0]-3)<len(self.m.data):self.m.handle('>')
        self.m.handle('y')
    def test_axes_absolute_and_reserved(self):
        rows=starmap({'planets':[]},{'position':[132,67]},{'destination_id':'x'},40,16)
        self.assertTrue(rows[0].startswith('X'));self.assertIn('120',rows[0]);self.assertIn('135',rows[0])
        self.assertEqual(rows[-1].strip(),'POS X=132 Y=67');self.assertTrue(any(r.startswith(' 65 ') for r in rows));self.assertEqual(sum(r.count('+') for r in rows),1)
    def test_jump_does_not_mutate_or_contact_server_and_follow_restores(self):
        before=copy.deepcopy(self.b.status);calls=len(self.b.calls)
        for command in ('v','1','0','0'):self.m.handle(command)
        self.assertEqual(self.m.view_center,[0,0]);self.assertEqual(self.b.status,before);self.assertEqual(len(self.b.calls),calls);self.assertEqual(self.b.mutations,[])
        self.assertIn('POS X=120 Y=60','\n'.join(self.m.render()))
        self.m.handle('2');self.assertIsNone(self.m.view_center)
    def test_view_without_device_and_departure_gate(self):
        self.m.info['exploration']['device']=False
        for command in ('v','1','239','119'):self.m.handle(command)
        self.assertEqual(self.m.view_center,[239,119]);self.m.handle('3');self.assertEqual(self.b.mutations,[])
        self.assertEqual(self.m.state,'MAP_VIEW')
    def test_invalid_coordinate_rejected_no_ship_change(self):
        for command in ('v','1','240'):self.m.handle(command)
        self.assertIsNone(self.m.view_center);self.assertEqual(self.m.state,'VIEW_X')
        self.m.handle('239');self.m.handle('120');self.assertEqual(self.m.state,'VIEW_Y');self.assertEqual(self.b.mutations,[])
    def test_view_coordinate_common_controls_and_literal_zero(self):
        self.m.handle('v');self.m.handle('1');self.m.handle('?');self.assertEqual(self.m.state,'TEXT')
        self.m.handle('back');self.assertEqual(self.m.state,'VIEW_X')
        self.m.handle('0');self.assertEqual(self.m.state,'VIEW_Y')
        self.m.handle('m');self.assertEqual(self.m.state,'MAIN')
        self.m.handle('v');self.m.handle('1');self.m.handle('q');self.assertFalse(self.m.running)
        self.assertEqual(self.b.mutations,[])
    def test_view_target_departure_requires_confirmation_cancel_main(self):
        for command in ('v','1','0','0','3','1'):self.m.handle(command)
        self.assertEqual(self.m.state,'CONFIRM');self.assertEqual(self.b.mutations,[])
        self.assertEqual(self.m.draft['arguments']['x'],0);self.m.handle('n');self.assertEqual(self.m.state,'MAIN');self.assertEqual(self.b.mutations,[])
    def test_navigation_confirmation_y_main_zero_back(self):
        self.m.open('go');self.m.handle('1');self.m.handle('0');self.assertEqual(self.m.state,'SELECT')
        self.m.handle('1');self.confirm();self.assertEqual(self.m.state,'MAIN');self.assertEqual(self.b.mutations[-1][0],'navigate')
    def test_coordinate_departure_y_main(self):
        for command in ('e','2','0','0','1'):self.m.handle(command)
        self.confirm();self.assertEqual(self.m.state,'MAIN');self.assertEqual(self.b.mutations[-1][0],'coordinate_depart')
    def test_history_own_endpoint_cursor_newest(self):
        self.m.handle('b');self.assertEqual(self.m.state,'HISTORY');self.assertIn('19','\n'.join(self.m.data))
        self.assertIn('Alvera','\n'.join(self.m.data));self.m.handle('o');self.assertEqual(self.b.calls[-1][1],{'before':2,'limit':20})
        self.assertIsNone(self.m.history_cursor);self.m.handle('back');self.assertEqual(self.m.history_cursor,2)
        self.m.handle('o');self.assertEqual(self.b.calls[-1][1],{'before':2,'limit':20})
        self.assertEqual(self.b.mutations,[])
    def test_layout_edges_resizing_and_secret_not_in_definition(self):
        for lang in ('ja','en'):
            self.t.language=lang
            for columns,rows in ((80,24),(100,30),(70,24),(50,24)):
                self.t.columns=columns;self.t.rows=rows
                for xy in ([0,0],[239,119],[132,67]):
                    self.m.view_center=xy;lines=self.m.render();self.assertLess(len(lines),rows);self.assertTrue(all(width(line)<columns for line in lines))
                    self.assertNotIn('hidden-001','\n'.join(lines))
    def test_flight_details_and_readonly_view(self):
        self.b.status['destination_id']='002';self.b.status['remaining_seconds']=60;self.m.refresh();self.m.flight['arrival_at']=160
        lines='\n'.join(self.m.render());self.assertIn('ETA',lines);self.assertIn('Remaining',lines);self.assertIn('POS X=',lines)
        self.assertNotIn('2 Market',lines);self.assertIn('N News / W WHO',lines)
        for value in ('v','1','1','1'):self.m.handle(value)
        self.m.handle('3');self.assertEqual(self.b.mutations,[])
    def test_menu_echo_free_name_and_bilingual_language(self):
        self.m.handle('v');self.assertEqual(self.m.echo('menu'),'MENU')
        self.m.state='STAR_NAME';self.assertEqual(self.m.echo('MiXeD星'),'MiXeD星')
        self.m.main();self.m.handle('l');self.assertIn('Japanese','\n'.join(self.m.render()));self.assertIn('日本語','\n'.join(self.m.render()))
    def test_buyback_and_stock_separate_both_trade_sides(self):
        row={'buy_price':101,'sell_price':99,'stock':11,'buyback_available':7,'owned':3,'free_capacity':6,'max_buy':6,'max_sell':3}
        for side in ('buy','sell'):
            text='\n'.join(self.m.trade_details(row,side));self.assertIn('11',text);self.assertIn('7',text);self.assertIn('3',text)
    def test_operational_settings_separate_from_trial(self):
        trial=json.loads((ROOT/'examples/exploration-trial.json').read_text(encoding='utf8'));ops=json.loads((ROOT/'examples/exploration-operations.json').read_text(encoding='utf8'))
        self.assertNotIn('world_events',trial['phase3']);self.assertEqual(ops['phase3']['world_events']['interval_seconds'],7200)
        self.assertLess(ops['phase3']['world_events']['probability_bps'],10000);self.assertEqual(policy()['round_seconds'],365*86400)
        self.assertNotEqual(fingerprint(Catalog(trial))['sha256'],fingerprint(Catalog(ops))['sha256'])
    def test_edge_ticks_never_leave_world_and_empty_views_have_no_ghost_ship(self):
        for center in ([0,0],[239,119]):
            lines=starmap({'planets':[]},{'position':[120,60]},{'destination_id':'x'},46,16,center=center)
            import re
            self.assertTrue(all(0<=int(n)<240 for n in re.findall(r'\d+',lines[0])))
            self.assertTrue(all(0<=int(row[:3])<120 for row in lines[1:-1] if row[:3].strip()))
            self.assertNotIn('+','\n'.join(lines))
    def test_donation_details_page_at_narrow_width_and_history_command(self):
        self.t.columns=50;self.m.state='QUANTITY';self.m.action='donate';self.m.selected={'origin_name':'Alvera','name':'Selnoa','distance':8,'donated_credits':100,'development_effect':125,'required_effect':8000,'remaining_credits':6300,'is_open':False}
        self.m.handle('n');self.assertGreater(self.m.page,0);self.assertTrue(all(width(row)<50 for row in self.m.render()))
        self.m.main();self.m.handle('history');self.assertEqual(self.m.state,'HISTORY')
