"""Trusted local terminal adapter; locale selection never changes game rules."""
import json
import shlex
import sqlite3
import time
from ..model import GameError
from ..presentation import Presentation

def __getattr__(name):
    # Preserve old imports without reading configurable resources at module import.
    if name == 'ERRORS':return Presentation().data['errors']
    if name == 'HELP':return Presentation().text('help')
    raise AttributeError(name)

class CLI:
    def __init__(self, app, player_id, output=print, language=None, language_files=None):
        self.app, self.player_id, self.output = app, player_id, output
        self.language_files = language_files
        self.view = Presentation(language or app.get_language(player_id), files=language_files)
        self.quotes = {}
        self.map_names = False

    def emit(self, key, **params):
        self.output(self.view.text(key, **params))

    def execute(self, line):
        tokens = shlex.split(line)
        if not tokens:
            return True
        cmd, *args = tokens
        request_id = None
        if cmd == 'request':
            if len(args) < 2:
                raise ValueError('request')
            request_id, cmd, *args = args
            if cmd not in ('register', 'buy', 'sell', 'go', 'warp', 'dock', 'invest', 'ship-buy', 'donate', 'insure', 'bankrupt'):
                raise ValueError('request operation')
        if cmd in ('quit','exit') and not args:
            return False
        if cmd in ('rankings','score','hall','rounds','exploration'):
            if len(args)>2 or (cmd in ('hall','rounds') and args):raise ValueError('records arguments')
            rid=int(args[0]) if args else None
            category=args[1] if len(args)==2 and cmd=='rankings' else None
            if len(args)==2 and category is None:raise ValueError('records arguments')
            if category is not None and category not in ('trade','planet','route','exploration'):raise ValueError('category')
            from pathlib import Path
            labels=json.loads((Path(__file__).parents[1]/'locales'/('phase4-'+self.view.language+'.json')).read_text(encoding='utf8'))
            self.output(labels[cmd]);self.output(json.dumps(self.app.records(cmd,self.player_id,rid,category),ensure_ascii=False,indent=2))
            return True
        if self.app.engine.catalog.phase3 is not None and cmd not in ('register','quit','exit','news','status','map','wait'):
            if self.app.get_player(self.player_id)['destination_id']:raise GameError('IN_TRANSIT')
        if cmd == 'news' and not args:
            rows=self.app._call('news',self.player_id)
            if not rows:self.emit('news_empty')
            for row in rows:
                self.emit('news_row',event_id=row['event_id'],game_time=row['game_time'],
                    label=self.view.text('news_'+row['kind']),planet=self.view.name('planets',row['planet_id'],self.app.engine.catalog.planets[row['planet_id']]['name']) if row['planet_id'] else '-',
                    details=json.dumps(row['values'],ensure_ascii=False,sort_keys=True))
        elif cmd == 'map-names' and args in (['on'],['off']):
            self.map_names=args[0]=='on';self.show_map()
        elif cmd == 'map' and len(args) in (0,2):
            self.show_map(*(map(int,args) if args else (None,None)))
        elif cmd == 'shipyard' and not args:
            for row in self.app._call('shipyard',self.player_id):self.emit('ship_offer',**row)
        elif cmd == 'ship-buy' and len(args)==1:
            self.emit('ship_bought',**self.app._call('buy_ship',self.player_id,args[0],request_id=request_id))
        elif cmd == 'donate' and len(args)==2:
            self.emit('donated',**self.app._call('donate',self.player_id,args[0],int(args[1]),request_id=request_id))
        elif cmd == 'insure' and not args:
            self.emit('insured',**self.app._call('insure',self.player_id,request_id=request_id))
        elif cmd == 'bankrupt' and not args:
            self.emit('restarted',**self.app._call('bankrupt',self.player_id,request_id=request_id))
        elif cmd == 'help' and not args:
            self.emit('help')
        elif cmd == 'config-info' and not args:
            self.output(json.dumps(self.app.configuration_info(),sort_keys=True))
        elif cmd == 'events-sync' and not args:
            self.emit('events_sync',**self.app.events_sync(self.player_id))
        elif cmd in ('events','events-history') and len(args)<=(1 if cmd=='events-history' else 0):
            rows=self.app.get_events(self.player_id) if cmd=='events' else self.app.event_history(self.player_id,int(args[0]) if args else 0)
            if not rows:self.emit('events_empty')
            for row in rows:self.emit('event_row',record_id=row.get('sequence','-'),label=self.view.text('event_'+row['kind']),**row)
        elif cmd == 'region' and not args:
            result=self.app.get_region(self.player_id)
            self.emit('region_header',**result)
            if not result['enabled']:self.emit('region_disabled')
            for row in result['entries']:
                self.emit('region_row',goods_id=row['goods_id'],base_price=row['base_price'],distance=row['distance'] if row['distance'] is not None else self.view.text('unknown'),basis=self.view.text('region_'+row['basis']))
        elif cmd == 'production' and not args:
            result=self.app.get_production(self.player_id)
            if not result['enabled']:self.emit('production_disabled')
            else:
                self.emit('production_header',**result)
                for row in result['entries']:
                    self.emit('production_row',label=self.view.text('industry_'+row['industry']) if row['industry'] else self.view.text('none'),**row)
                    if 'market_capacity' in row:self.emit('production_capacity',**row)
        elif cmd == 'development' and not args:
            result=self.app.get_development(self.player_id)
            self.emit('development_header',planet_id=result['planet_id'])
            if not result['enabled']:self.emit('development_disabled')
            for row in result['industries']:
                self.emit('industry_level' if 'level' in row else 'industry_progress',label=self.view.text('industry_'+row['industry']),**row)
            self.emit('resources',items=', '.join(self.view.name('resources',r['resource_id'],r['resource_id']) for r in result['resources']) or self.view.text('none'))
        elif cmd == 'invest' and len(args)==2:
            result=self.app.invest(self.player_id,args[0],int(args[1]),request_id=request_id)
            self.emit('invested_level' if 'level' in result else 'invested',label=self.view.text('industry_'+result['industry']),**result)
        elif cmd == 'investments' and len(args)<=1:
            rows=self.app.investment_ledger(self.player_id,int(args[0]) if args else 0)
            if not rows:self.emit('investment_empty')
            for row in rows:self.emit('investment_row',label=self.view.text('industry_'+row['industry']),**row)
        elif cmd == 'trade-quote' and len(args)==3:
            self.emit('trade_quote',**self.app.quote_trade(self.player_id,args[1],int(args[2]),args[0]))
        elif cmd == 'ledger' and len(args)<=1:
            rows=self.app.trade_ledger(self.player_id,int(args[0]) if args else 0)
            if not rows:self.emit('ledger_empty')
            for row in rows:self.emit('ledger_row',**row)
        elif cmd == 'language' and len(args) == 1:
            view = Presentation(args[0], files=self.language_files)
            self.app.set_language(self.player_id, args[0])
            self.view = view
            self.emit('language', language=args[0])
        elif cmd == 'register' and args:
            p = self.app.create_player(self.player_id, ' '.join(args), request_id=request_id)
            self.emit('registered', **p)
        elif cmd == 'status' and not args:
            p = self.app.get_player(self.player_id)
            self.emit('status', **p)
            p['ship_name'] = self.view.name('ships', p['ship_id'], p['ship_name'])
            self.emit('ship', **p)
            self.location(p)
            items = ', '.join(f"{self.view.name('goods',v['goods_id'],v['name'])}[{v['goods_id']}] x{v['quantity']}" for v in p['cargo'])
            self.emit('cargo', items=items or self.view.text('none'))
            if self.app.engine.catalog.phase3 is not None:self.show_map()
        elif cmd == 'ship' and not args:
            p = self.app.get_ship(self.player_id)
            p['name'] = self.view.name('ships',p['ship_id'],p['name'])
            p['type_label'] = self.view.text('type_' + p['ship_type']) if p['ship_type'] else self.view.text('undecided')
            p['state_label'] = self.view.text('spec_' + p['specification_status'])
            for field in ('grade_id','grade_rank','normal_speed','max_warp_speed','purchase_price','insurance_premium'):
                if p[field] is None:
                    p[field] = self.view.text('undecided')
            self.emit('ship_profile', **p)
        elif cmd == 'market' and not args:
            market = self.app.get_market(self.player_id)
            self.emit('market', **market)
            if market.get('pricing_mode')!='fixed':self.emit('market_curve_notice')
            for row in market['entries']:
                row['name'] = self.view.name('goods',row['goods_id'],row['name'])
                self.emit('entry', **row)
        elif cmd in ('buy','sell') and len(args) == 2:
            operation = self.app.buy_goods if cmd == 'buy' else self.app.sell_goods
            self.emit(cmd, **operation(self.player_id,args[0],int(args[1]),request_id=request_id))
        elif cmd == 'routes' and not args:
            for row in self.app.get_routes(self.player_id):
                row['name'] = self.view.name('planets',row['destination_id'],row['name'])
                self.emit('route',state=self.view.text('opened' if row['is_open'] else 'closed'),**row)
        elif cmd == 'quote' and 1 <= len(args) <= 3:
            mode=args[1] if len(args)>1 else 'normal'
            level=args[2] if len(args)>2 else None
            q=self.app.quote_navigation(self.player_id,args[0],mode,level)
            self.quotes[(args[0],mode,level)]=q['quote_id']
            self.emit('navigation_quote',mode_label=self.view.text('mode_'+mode),policy_label=self.view.text('policy_'+q['policy_status']),**q)
        elif cmd == 'warp' and len(args) in (2,3):
            token=args[2] if len(args)==3 else self.quotes.get((args[0],'warp',args[1]))
            if token is None:raise GameError('QUOTE_REQUIRED')
            result=self.app.navigate(self.player_id,args[0],'warp',args[1],token,request_id=request_id)
            self.emit('depart',**result)
            if self.app.engine.catalog.phase3 is not None:self.show_map()
        elif cmd == 'dock' and not args:
            self.emit('docked',**self.app.dock(self.player_id,request_id=request_id))
        elif cmd == 'voyage' and not args:
            trip=self.app.latest_voyage(self.player_id)
            if trip is None:
                self.emit('no_voyage')
            else:
                if trip['fuel_cost'] is None:trip['fuel_cost']=self.view.text('unknown')
                self.emit('voyage',mode_label=self.view.text('mode_'+trip['mode']),state_label=self.view.text('arrived' if trip['arrived'] else 'travelling'),**trip)
        elif cmd == 'go' and len(args) == 1:
            self.emit('depart', **self.app.depart(self.player_id,args[0],request_id=request_id))
            if self.app.engine.catalog.phase3 is not None:self.show_map()
        elif cmd == 'wait' and not args:
            while True:
                p = self.app.get_player(self.player_id)
                if not p['destination_id']:
                    break
                if self.app.engine.catalog.phase3 is not None:self.show_map()
                time.sleep(min(1,p['remaining_seconds']))
            self.location(p)
        else:
            raise ValueError('command')
        return True

    def show_map(self,width=None,height=None):
        import shutil
        terminal=shutil.get_terminal_size((80,24))
        width=max(1,min(240,terminal.columns-2)) if width is None else width
        height=max(1,min(120,terminal.lines-5)) if height is None else height
        from ..starmap import render
        from ..mechanics import coordinates
        from ..universe import normal_planets
        c=self.app.engine.catalog;trip=self.app._call('flight',self.player_id)
        coords=coordinates(c);names={r['id']:r['en'] for r in normal_planets()}
        planets=[dict(planet_id=pid,position=pos,name_en=names.get(pid,pid)) for pid,pos in coords.items()]
        bounds=c.data.get('universe',{}).get('parameters',{'width':240,'height':120})
        self.emit('flight_frame',origin=trip['origin_id'],destination=trip['destination_id'] or '-',
                  x=trip['position'][0],y=trip['position'][1],eta=trip['arrival_at'] or '-',seconds=trip['remaining_seconds'])
        self.output(render(planets,trip['position'],width=width,height=height,names=self.map_names,
                           bounds=(bounds['width'],bounds['height']),docked_id=trip['origin_id'] if trip['destination_id'] is None else None))

    def location(self,p):
        p['planet_name'] = self.view.name('planets',p['planet_id'],p['planet_name'])
        self.emit('travel' if p['destination_id'] else 'location', **p)

    def safe_execute(self,line):
        try:
            return self.execute(line),0
        except GameError as exc:
            self.output(self.view.error(exc.code))
        except ValueError:
            self.emit('invalid')
        except sqlite3.OperationalError:
            self.emit('db_error')
        return True,1

    def run(self,input_fn=input):
        self.emit('help')
        try:
            while True:
                try:
                    line = input_fn('srt> ')
                except EOFError:
                    break
                keep_going,_ = self.safe_execute(line)
                if not keep_going:
                    break
        except KeyboardInterrupt:
            self.emit('bye')
