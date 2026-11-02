"""Menu state machine layered over the existing authenticated Door backend."""
import copy,json,shlex,time,uuid,sys
from .client import ClientError,MUTATIONS
from .screen import geometry,starmap,compose,wrap
from .terminal import clip,width
from .input import Input

KEYS=[('1','status'),('2','market'),('3','buy'),('4','sell'),('5','routes'),('6','go'),('7','warp'),
      ('8','invest'),('9','donate'),('s','shipyard'),('i','insure'),('n','news'),('w','who'),
      ('r','rankings'),('h','hall'),('t','names'),('l','language'),('?','help'),('q','quit')]
CATEGORIES=('trade','planet','route','exploration')

class Menu:
    def __init__(self,terminal):
        self.ui=terminal;self.backend=terminal.backend;self.state='MAIN';self.stack=[];self.data=None;self.page=0
        self.action=None;self.selected=None;self.draft=None;self.notice='';self.running=True
        self.status={};self.flight={'position':[0,0]};self.definition={'planets':[]};self.info={};self.online=False
    def text(self,key,**values):
        text=self.ui.packs[self.ui.language].get('ui',{}).get(key,key)
        return text.format(**values)
    def name(self,row,kind='goods'):
        if kind=='goods':return self.ui.packs[self.ui.language]['goods_names'].get(row.get('goods_id'),row.get('name',self.text('unknown_product')))
        if kind=='ship':
            info=next((s for s in self.info.get('ships',[]) if s['ship_id']==row.get('ship_id')),row)
            return self.text('type_'+str(info.get('ship_type','normal')))+' '+str(info.get('grade') or info.get('ship_id',''))
        return row.get('name',row.get('destination_id',self.text('unknown')))
    def error(self,e):
        code=e.code if isinstance(e,ClientError) else 'INVALID_INPUT'
        self.notice=self.ui.packs[self.ui.language].get('error_messages',{}).get(code,self.text('error_code',code=code))
        if code in ('MASTER_UNAVAILABLE','AUTH_FAILED','SESSION_EXPIRED','WORLD_TARGET_MISMATCH','CONFIG_VERIFICATION_FAILED'):
            self.online=False;self.draft=None
        return code
    def refresh(self):
        try:
            # Existing engine settles only elapsed server-clock time, never a UI tick.
            self.status=self.backend.call('status');self.flight=self.backend.call('flight')
            self.definition=self.backend.call('map')['definition'];self.info=self.backend.call('ui_info');self.online=True
        except ClientError as e:self.error(e)
    @property
    def in_flight(self):return bool(self.status.get('destination_id'))
    def push(self,state,data=None,action=None):
        self.stack.append((self.state,self.data,self.page,self.action,self.selected))
        self.state=state;self.data=data;self.page=0;self.action=action
    def back(self):
        if not (self.state=='TEXT' and self.action=='help'):self.draft=None
        if self.stack:self.state,self.data,self.page,self.action,self.selected=self.stack.pop()
        else:self.main()
    def main(self):self.state='MAIN';self.stack=[];self.data=None;self.page=0;self.draft=None;self.action=None;self.selected=None;self.notice='';self.refresh()
    def size(self):
        w,h,lw,rw,stack=geometry(self.ui.columns,self.ui.rows)
        return (h-max(2,h//3) if stack else h),rw
    def page_size(self):return max(1,self.size()[0]-4)
    def options(self):
        if self.state=='MAIN':
            if self.in_flight:return [('n','news'),('w','who'),('m','refresh'),('?','help'),('q','quit')]
            return KEYS
        return []
    def items(self):
        if self.state in ('MARKET','SELECT','WARP','CATEGORY'):return self.data or []
        if self.state=='MAIN':return self.options()
        if isinstance(self.data,list):return self.data
        return []
    def paged(self):
        count=self.page_size();total=len(self.items());pages=max(1,(total+count-1)//count)
        self.page=max(0,min(self.page,pages-1));start=self.page*count
        return list(enumerate(self.items()[start:start+count],start+1)),pages
    def selected_row(self,line):
        if not line.isascii() or not line.isdigit():raise ClientError('INVALID_SELECTION')
        n=int(line);shown,_=self.paged()
        if n not in dict(shown):raise ClientError('INVALID_SELECTION')
        return dict(shown)[n]
    def facts(self,value):
        lines=[]
        if isinstance(value,list):
            for row in value:lines.extend(self.facts(row))
        elif isinstance(value,dict):
            for key,v in value.items():
                if key in ('player_id','season_id','pricing_mode','policy_status','public','event_id','quote_id'):continue
                if isinstance(v,(list,dict)):
                    lines.append(self.ui.packs[self.ui.language].get(key,key)+':');lines.extend(self.facts(v))
                else:
                    if key=='goods_id':v=self.name({'goods_id':v})
                    elif key in ('origin_id','destination_id','planet_id'):
                        v=next((p['name'] for p in self.definition.get('planets',[]) if p['planet_id']==v),v)
                    elif key in ('ship_id','old_ship_id'):v=self.name({'ship_id':v},'ship')
                    elif key=='category':v=self.text(v)
                    elif type(v) is bool:v=self.text('yes' if v else 'no')
                    lines.append(self.ui.packs[self.ui.language].get(key,key)+': '+str(v))
        else:lines.append(str(value))
        return [part for line in lines for part in wrap(line,self.size()[1])]
    def show(self,title,value):self.push('TEXT',self.facts(value),title)
    def allowed(self,action):
        if self.in_flight and action not in ('news','who','help','refresh','quit','map','status','flight','language','names'):
            raise ClientError('IN_TRANSIT')
    def open(self,action):
        self.allowed(action)
        if action=='quit':self.running=False;return
        if action=='refresh':self.main();return
        if action=='names':self.ui.names=not self.ui.names;return
        if action=='language':self.push('LANGUAGE');return
        if action=='help':self.push('TEXT',self.help_lines(), 'help');return
        if action=='status':
            self.refresh();lines=self.facts(self.status)+self.facts({'bbs':self.info.get('bbs',''), 'insured':self.info.get('insured',False)})
            self.push('STATUS',lines);return
        if action=='market':self.push('MARKET',self.backend.call('market')['entries']);return
        if action in ('buy','sell'):
            rows=self.backend.call('market')['entries'] if action=='buy' else self.backend.call('status')['cargo']
            self.push('SELECT',rows,action);return
        if action in ('routes','go','warp','donate'):
            rows=self.backend.call('routes')
            if action in ('go','warp'):rows=[r for r in rows if r['is_open']]
            if action=='donate':rows=[r for r in rows if not r['is_open']]
            self.push('SELECT',rows,action);return
        if action=='invest':self.push('SELECT',self.backend.call('development')['industries'],action);return
        if action=='shipyard':self.push('SELECT',[r for r in self.backend.call('shipyard') if r['available']],action);return
        if action in ('insure','bankrupt'):
            self.refresh();self.confirm(action,{},self.insurance_lines() if action=='insure' else self.bankruptcy_lines());return
        if action=='news':
            rows=sorted(self.backend.call('news'),key=lambda x:(x['game_time'],x['event_id']),reverse=True)
            lines=[]
            for r in rows:
                lines+=wrap(self.text('event_'+r['kind'])+' / '+str(r['game_time']),self.size()[1]);lines+=self.facts(r['values']);lines.append('')
            self.push('TEXT',lines,'news');return
        if action=='who':
            self.show('who',self.backend.who());return
        if action in ('rankings','hall'):self.push('CATEGORY',list(CATEGORIES),action);return
        if action=='score':self.show('score',self.backend.call('score'));return
        self.show(action,self.backend.call(action))
    def help_lines(self):
        topic=self.action or self.state.lower()
        lines=[self.text('context',name=self.text(topic))]
        for line in self.ui.packs[self.ui.language]['ui']['guide']:lines+=wrap(line,self.size()[1])
        return lines
    def insurance_lines(self):
        ship=next((r for r in self.info.get('ships',[]) if r['ship_id']==self.status.get('ship_id')), {})
        return self.facts({'insured':self.info.get('insured',False),'insurance_premium':ship.get('insurance_premium')})
    def bankruptcy_lines(self):
        restart=self.info.get('restart',{})
        return wrap(self.text('bankruptcy_warning'),self.size()[1])+self.facts({'ship_id':restart.get('restart_ship'),'cash':restart.get('restart_cash')})
    def confirm(self,operation,arguments,lines,quote=None):
        self.push('CONFIRM',lines,operation)
        self.draft={'operation':operation,'arguments':dict(arguments),'quote':quote,'request_id':uuid.uuid4().hex}
    def quantity(self,line):
        if not line.isascii() or not line.isdigit() or not 0<int(line)<=2**63-1:raise ClientError('INVALID_AMOUNT')
        amount=int(line);op=self.action;row=self.selected
        if op in ('buy','sell'):
            args={'goods_id':row['goods_id'],'quantity':amount}
            quote=self.backend.call('quote_trade',{**args,'side':op})
            # The quote total is checked again atomically by the existing operation.
            self.confirm(op,{**args,'expected_total':quote['total']},self.facts(quote)+self.facts({'cash':self.status.get('cash'), 'used_capacity':self.status.get('used_capacity'),'capacity':self.status.get('capacity')}),quote)
        else:
            args={('industry' if op=='invest' else 'route_id'):row['industry' if op=='invest' else 'route_id'],'paid_credits':amount}
            self.confirm(op,args,self.facts(args))
    def travel(self,mode,level=None):
        args={'destination_id':self.selected['destination_id'],'mode':mode,'level':level}
        quote=self.backend.call('quote_navigation',args)
        self.confirm('navigate',args,self.facts(quote),quote)
    def commit(self):
        draft=self.draft
        if not draft:raise ClientError('NO_CONFIRMATION')
        try:
            result=self.backend.call(draft['operation'],draft['arguments'],draft['request_id'])
        except ClientError as e:
            if e.code=='PRICE_CHANGED':
                args={k:v for k,v in draft['arguments'].items() if k!='expected_total'}
                q=self.backend.call('quote_trade',{**args,'side':draft['operation']})
                draft['arguments']['expected_total']=q['total'];draft['quote']=q;draft['request_id']=uuid.uuid4().hex
                self.data=self.facts(q);self.notice=self.text('price_changed');return
            self.draft=None;self.state='TEXT';self.data=[self.text('not_completed')];self.error(e);return
        self.draft=None;self.stack=[];self.state='TEXT';self.action='result';self.page=0;self.data=self.facts(result);self.notice=self.text('completed');self.refresh()
    def direct(self,line):
        parts=shlex.split(line);op=parts[0].lower()
        self.allowed(op)
        if op in ('bankrupt','insure') and len(parts)==1:self.open(op);return
        if op in ('buy','sell') and len(parts)==3:
            args={'goods_id':parts[1],'quantity':int(parts[2])};quote=self.backend.call('quote_trade',{**args,'side':op})
            self.confirm(op,{**args,'expected_total':quote['total']},self.facts(quote),quote);return
        # Keep all legacy parsers/arguments available; dangerous mutations get one explicit confirmation.
        if op in ('go','warp','invest','donate','ship-buy','dock'):
            specs={'go':1,'warp':2,'invest':2,'donate':2,'ship-buy':1,'dock':0}
            if len(parts)-1!=specs[op]:raise ValueError('arguments')
            if op in ('go','warp'):
                self.selected={'destination_id':parts[1]};self.travel('normal' if op=='go' else 'warp',parts[2] if op=='warp' else None);return
            args={'industry':parts[1],'paid_credits':int(parts[2])} if op=='invest' else {'route_id':parts[1],'paid_credits':int(parts[2])} if op=='donate' else {'ship_id':parts[1]} if op=='ship-buy' else {}
            self.confirm('buy_ship' if op=='ship-buy' else op,args,self.facts(args));return
        if op in ('buy','sell','go','warp','invest','donate','ship-buy'):
            raise ValueError('arguments')
        old=self.ui.output;lines=[];self.ui.output=lines.append
        try:self.running=self.ui.execute(line)
        finally:self.ui.output=old
        self.push('TEXT',[p for l in lines for p in wrap(l,self.size()[1])],op)
        if op in ('reconnect','language','color','names','map'):self.main()
    def handle(self,line):
        line=line.strip();key=line.lower();self.notice=''
        try:
            if key in ('q','quit','exit'):self.running=False;self.draft=None;return
            if key in ('menu','main','m'):self.main();return
            if key in ('0','back'):self.back();return
            if not key:self.refresh();return
            if key in ('?','help'):self.push('TEXT',self.help_lines(),'help');return
            if self.state=='MAIN':
                if key in ('>','<'):self.page+=1 if key=='>' else -1;return
                action=dict(KEYS).get(key)
                if action:self.open(action)
                elif key in dict(KEYS).values():self.open(key)
                else:self.direct(line)
            elif self.state=='CONFIRM':
                if key in ('>','<'):self.page+=1 if key=='>' else -1
                elif key=='y':
                    available=max(1,self.size()[0]-3)
                    if (self.page+1)*available<len(self.data):self.notice=self.text('review_remaining')
                    else:self.commit()
                elif key=='n':self.back()
                else:raise ClientError('CONFIRM_REQUIRED')
            elif self.state=='LANGUAGE':
                if key not in ('1','2','ja','en'):raise ClientError('INVALID_SELECTION')
                self.ui.language='ja' if key in ('1','ja') else 'en';self.backend.language(self.ui.language);self.main()
            elif self.state=='QUANTITY':self.quantity(line)
            elif key in ('n','p'):
                self.page+=1 if key=='n' else -1
            elif self.state=='STATUS':
                if key=='c':self.open('score')
                elif key=='b':self.open('bankrupt')
                else:raise ClientError('INVALID_SELECTION')
            elif self.state=='MARKET' and key in ('b','s'):self.open('buy' if key=='b' else 'sell')
            elif self.state in ('MARKET','SELECT','WARP','CATEGORY'):
                row=self.selected_row(key)
                if self.state=='CATEGORY':
                    self.show(self.action,[r for r in self.backend.call(self.action) if r['category']==row]);return
                if self.state=='WARP':self.travel('warp',row['level']);return
                if self.state=='MARKET':self.action='buy'
                self.selected=row
                if self.action in ('buy','sell','invest','donate'):self.push('QUANTITY',None,self.action)
                elif self.action=='shipyard':
                    details=next((s for s in self.info.get('ships',[]) if s['ship_id']==row['ship_id']),{})
                    self.confirm('buy_ship',{'ship_id':row['ship_id']},self.facts({**details,**row}))
                elif self.action=='go':self.travel('normal')
                elif self.action=='warp':self.push('WARP',self.info.get('warp_options',{}).get(row['destination_id'],[]),'warp')
                elif self.action=='routes':self.show('routes',row)
            else:raise ClientError('INVALID_SELECTION')
        except ClientError as e:self.error(e)
        except (ValueError,KeyError,TypeError):
            op=key.split(' ')[0];self.notice=self.text('usage_'+op) if op in ('buy','sell','warp','go','invest','donate','ship-buy') else self.text('invalid_input')
    def row_text(self,n,row):
        if self.state=='MAIN':return row[0].upper()+' '+self.text(row[1])
        if self.state=='CATEGORY':return str(n)+' '+self.text(row)
        if self.state=='WARP':return str(n)+' '+str(row['level'])+' / '+str(row['speed'])
        if isinstance(row,str):return row
        if self.state=='MARKET' or self.action in ('buy','sell'):
            tail=f" {row.get('price','-')}Cr/{row.get('stock',row.get('quantity',0))}"
            return str(n)+' '+clip(self.name(row),max(4,self.size()[1]-len(str(n))-1-len(tail)))+tail
        if self.action=='invest':return str(n)+' '+self.text(row['industry'])+' Lv'+str(row.get('level',row.get('progress',0)))
        if self.action=='shipyard':return str(n)+' '+self.name(row,'ship')+' '+str(row['price'])+'Cr'
        if self.action in ('routes','go','warp','donate'):return str(n)+' '+self.name(row,'planet')+' '+str(row['distance'])+' / '+str(row['seconds'])+'s '+('+' if row['is_open'] else '-')
        return str(row)
    def panel(self):
        h,w=self.size();title=self.text(self.action or self.state.lower());lines=[title]
        if self.state=='LANGUAGE':return [self.text('language'),'1 日本語','2 English',self.text('back_keys')]
        if self.state=='QUANTITY':return [title,self.name(self.selected) if self.action in ('buy','sell') else self.text('amount'),self.text('quantity' if self.action in ('buy','sell') else 'amount'),self.text('back_keys')]
        if self.state=='CONFIRM':
            available=max(1,h-3);pages=max(1,(len(self.data)+available-1)//available);self.page=max(0,min(self.page,pages-1))
            return [title]+self.data[self.page*available:(self.page+1)*available]+[self.text('confirm_keys'),self.text('confirm_page',page=self.page+1,pages=pages)]
        shown,pages=self.paged()
        if self.state=='MARKET':lines.append(self.text('market_columns'))
        lines.extend(self.row_text(n,row) for n,row in shown)
        if not shown:lines.append(self.text('empty'))
        lines.append(self.text('page',page=self.page+1,pages=pages))
        if self.state=='MAIN':lines.append(self.text('main_keys'))
        elif self.state=='MARKET':lines.append(self.text('market_keys'))
        elif self.state=='STATUS':lines.append(self.text('status_keys'))
        else:lines.append(self.text('list_keys'))
        return lines[:h]
    def render(self,buffer=''):
        w,h,lw,rw,stacked=geometry(self.ui.columns,self.ui.rows)
        map_h=max(2,h//3) if stacked else h
        chart=starmap(self.definition,self.flight,self.status,lw,map_h,self.ui.names,self.ui.ansi)
        title='STARROUTE TRADERS - '+self.text('in_flight' if self.in_flight else 'bbs_edition')
        ship=self.name({'ship_id':self.status.get('ship_id')},'ship')
        summary=f"{self.status.get('handle','-')} | {ship} | {self.status.get('cash',0):,} Cr | {self.text('round')} {self.status.get('season_id','-')}"
        if self.in_flight:
            mode=self.info.get('flight',{});seconds=self.flight.get('remaining_seconds',0)
            names={p['planet_id']:p['name'] for p in self.definition.get('planets',[])}
            footer=f"{names.get(self.flight.get('origin_id'),'-')} -> {names.get(self.flight.get('destination_id'),'-')}  ETA {seconds//3600:02}:{seconds//60%60:02}:{seconds%60:02}  {mode.get('mode','')} {mode.get('level') or ''}"
        else:footer=f"{self.status.get('planet_name','-')} | {self.text('cargo')} {self.status.get('used_capacity',0)}/{self.status.get('capacity',0)} | {self.text('docked')}"
        notice=self.notice or (self.text('welcome_guide') if self.state=='MAIN' else self.text('back_keys'))
        if not self.online:notice=self.text('offline')+' '+notice
        return compose(self.ui.columns,self.ui.rows,title,summary,chart,self.panel(),footer,notice,'Select > '+buffer)
    def draw(self,buffer=''):
        lines=self.render(buffer)
        if self.ui.ansi:
            sys.stdout.write('\x1b[0m\x1b[H\x1b[2J'+'\r\n'.join(lines)+'\x1b[0m');sys.stdout.flush()
        else:
            sys.stdout.write('\n'.join(lines)+'\n');sys.stdout.flush()
    def run(self,stream):
        self.ui.resize(stream);self.refresh();self.draw();last_refresh=time.monotonic();last_heartbeat=last_refresh
        config=getattr(self.backend,'config',{})
        refresh_seconds=max(1,config.get('ui_refresh_seconds',5));heartbeat_seconds=max(5,config.get('heartbeat_seconds',30))
        try:
            with Input(stream) as reader:
                oldbuffer=''
                while self.running:
                    line=reader.read();now=time.monotonic();oldsize=(self.ui.columns,self.ui.rows);self.ui.resize(stream)
                    if line is None:break
                    if line is not False:
                        self.handle(line)
                        if self.running:self.draw()
                        oldbuffer='';last_refresh=now
                    elif oldsize!=(self.ui.columns,self.ui.rows) or (self.in_flight and now-last_refresh>=refresh_seconds):
                        self.refresh();self.draw(reader.buffer);last_refresh=now
                    elif reader.buffer!=oldbuffer:
                        if self.ui.ansi:sys.stdout.write(f'\x1b[{len(self.render())};10H\x1b[K'+clip(reader.buffer,self.ui.columns-10))
                        else:sys.stdout.write('\r'+clip('Select > '+reader.buffer,self.ui.columns-1)+' ')
                        sys.stdout.flush();oldbuffer=reader.buffer
                    if now-last_heartbeat>=heartbeat_seconds:
                        try:self.backend.heartbeat()
                        except ClientError as e:self.error(e)
                        last_heartbeat=now
        finally:
            if self.ui.ansi:sys.stdout.write('\x1b[0m\r\n')
            try:self.backend.logout()
            except ClientError:pass
            self.ui.emit(self.ui.text('goodbye'))
