"""UTF-8 line-oriented Telnet Door UI shared by local and remote backends."""
import json,re,shlex,os,unicodedata
from pathlib import Path
from .client import ClientError

ANSI=re.compile(r'\x1b\[[0-9;]*[A-Za-z]')


def width(text):return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in ANSI.sub('',text))


def clean(text):return ''.join(c for c in str(text) if c>=' ' and c!='\x7f' and c!='\x9b')


def clip(text,columns):
    result='';used=0
    for c in clean(text):
        w=0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1
        if used+w>columns:break
        result+=c;used+=w
    return result


class Terminal:
    def __init__(self,backend,language='ja',ansi=True,columns=80,rows=24,output=print):
        self.backend=backend;self.language=language;self.ansi=ansi;self.columns=columns;self.rows=rows;self.output=output;self.names=False
        self.packs={lang:json.loads((Path(__file__).parent/'locales'/(lang+'.json')).read_text(encoding='utf8')) for lang in ('ja','en')}

    def text(self,key):return self.packs[self.language][key]
    def resize(self,input_stream):
        # COLUMNS/LINES describe the initial Door environment, not live NAWS.
        try:size=os.get_terminal_size(input_stream.fileno())
        except (OSError,ValueError,AttributeError):return
        if size.columns and size.lines:
            self.columns=max(20,min(240,size.columns));self.rows=max(12,min(120,size.lines))
    def emit(self,text):self.output(clip(text,self.columns))
    def show(self,data):
        if isinstance(data,list):
            for row in data:self.show(row)
        elif isinstance(data,dict):
            for key,value in data.items():
                if isinstance(value,(list,dict)):self.emit(self.packs[self.language].get(key,key)+':');self.show(value)
                else:self.emit(self.packs[self.language].get(key,key)+': '+str(value))
        else:self.emit(str(data))

    def map(self):
        data=self.backend.call('map')['definition'];flight=self.backend.call('flight');status=self.backend.call('status')
        w=max(20,min(240,self.columns));h=max(5,min(120,self.rows-8));pos=flight['position']
        left=max(0,min(240-w,pos[0]-w//2));top=max(0,min(120-h,pos[1]-h//2));grid=[[' ']*w for _ in range(h)]
        highlights=set()
        for p in data['planets']:
            if 'coordinates' not in p:continue
            x=p['coordinates']['x']-left;y=p['coordinates']['y']-top
            if 0<=x<w and 0<=y<h:
                grid[y][x]='*'
                if not status['destination_id'] and p['planet_id']==status['planet_id']:highlights.add((x,y))
                if self.names:
                    for i,ch in enumerate(' '+clean(p['name'])):
                        if x+1+i<w:grid[y][x+1+i]=ch
        x=pos[0]-left;y=pos[1]-top
        if status['destination_id'] and 0<=x<w and 0<=y<h:grid[y][x]='+';highlights.add((x,y))
        self.emit(f"STARROUTE 240x120  [{left},{top}]  {pos[0]},{pos[1]}")
        for y,row in enumerate(grid):
            self.output(''.join(('\x1b[32m'+ch+'\x1b[0m') if self.ansi and (x,y) in highlights else ch for x,ch in enumerate(row)))
        self.emit(self.text('eta')+': '+str(flight['remaining_seconds'])+'s  '+str(flight['origin_id'])+' -> '+str(flight['destination_id'] or '-'))
        if status['destination_id']:self.emit(self.text('in_flight'))

    def execute(self,line):
        parts=shlex.split(line)
        if not parts:return True
        cmd,*args=parts;cmd=cmd.lower()
        if cmd in ('quit','exit'):return False
        if cmd=='language' and args in (['ja'],['en']):self.language=args[0];self.backend.language(self.language);self.emit(self.text('welcome'));return True
        if cmd=='color' and args in (['on'],['off']):self.ansi=args[0]=='on';return True
        if cmd=='names' and args in (['on'],['off']):self.names=args[0]=='on';self.map();return True
        if cmd=='help':
            for line in ('status / market [page] / buy GOODS QTY / sell GOODS QTY',
                         'routes [page] / go PLANET / warp PLANET LEVEL / flight / map',
                         'development / invest INDUSTRY Cr / donate ROUTE Cr',
                         'news [page] / rankings [page] / hall [page] / score / WHO',
                         'shipyard / ship-buy SHIP / insure / bankrupt / dock',
                         'rounds / exploration / names on|off / color on|off',
                         'language ja|en / reconnect / result / retry / cache OP / quit'):self.emit(line)
            return True
        if cmd=='reconnect':self.show(self.backend.connect());return True
        if cmd=='result':self.show(self.backend.resolve());return True
        if cmd=='retry':self.show(self.backend.retry_pending());return True
        if cmd=='cache' and len(args)==1:self.emit(self.text('stale'));self.show(self.backend.cached(args[0]));return True
        if cmd in ('who','online'):self.show(self.backend.who());return True
        if cmd=='map':self.map();return True
        if cmd in ('market','routes','news','rankings','hall') and len(args)<=1:
            page=int(args[0]) if args else 1
            if page<1:raise ValueError('page')
            data=self.backend.call(cmd);rows=data['entries'] if cmd=='market' else data
            fields={'market':('goods_id','price','stock'),'routes':('route_id','destination_id','distance','is_open'),
                    'news':('kind','planet_id','game_time'),'rankings':('category','rank','display_name','score'),
                    'hall':('round_id','category','rank','display_name','score')}[cmd]
            count=max(1,(self.rows-5)//(2 if cmd=='news' else 1));start=(page-1)*count
            self.emit(' | '.join(self.packs[self.language].get(k,k) for k in fields))
            for row in rows[start:start+count]:
                self.emit(' | '.join(str(row.get(k,'-')) for k in fields))
                if cmd=='news':self.emit('  '+', '.join(self.packs[self.language].get(k,k)+'='+str(v) for k,v in row.get('values',{}).items()))
            self.emit(f'{cmd} {page} / {max(1,(len(rows)+count-1)//count)}');return True
        specs={'buy':('buy',('goods_id','quantity')),'sell':('sell',('goods_id','quantity')),
               'invest':('invest',('industry','paid_credits')),'donate':('donate',('route_id','paid_credits')),
               'ship-buy':('buy_ship',('ship_id',))}
        if cmd in ('go','warp'):
            if len(args)!=(1 if cmd=='go' else 2):raise ValueError('navigation')
            result=self.backend.call('navigate',{'destination_id':args[0],'mode':'normal' if cmd=='go' else 'warp','level':None if cmd=='go' else args[1]})
            self.show(result);self.map();return True
        if cmd in specs:
            op,fields=specs[cmd]
            if len(args)!=len(fields):raise ValueError('arguments')
            values={k:int(v) if k in ('quantity','paid_credits') else v for k,v in zip(fields,args)}
            self.show(self.backend.call(op,values));return True
        if cmd in ('status','market','routes','development','production','shipyard','insure','bankrupt','dock','flight','news','score','rankings','hall','rounds','exploration') and not args:
            self.show(self.backend.call(cmd));return True
        raise ValueError('command')

    def run(self,input_stream):
        import threading
        stop=threading.Event()
        def heartbeat():
            interval=max(5,getattr(self.backend,'config',{}).get('heartbeat_seconds',30))
            while not stop.wait(interval):
                try:self.backend.heartbeat()
                except ClientError:self.emit(self.text('offline'));return
        worker=threading.Thread(target=heartbeat,daemon=True);worker.start()
        self.emit(self.text('welcome'));self.emit(self.text('help'))
        try:
            while True:
                self.resize(input_stream)
                self.emit('SRT>')
                line=input_stream.readline(4097)
                if not line:break
                self.resize(input_stream)
                if len(line)>4096:self.emit(self.text('invalid'));continue
                try:
                    if not self.execute(line):break
                except ClientError as e:self.emit(self.text('offline') if e.code=='MASTER_UNAVAILABLE' else self.text('error')+': '+e.code)
                except (ValueError,KeyError,TypeError):self.emit(self.text('invalid'))
        finally:
            stop.set();worker.join(timeout=1)
            try:self.backend.logout()
            except ClientError:pass
            self.emit(self.text('goodbye'))
