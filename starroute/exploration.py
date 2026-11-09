"""Server-only coordinate voyages and player-scoped discovery state.
All mutations are executed by Application within the existing game transaction.
"""
import copy,hashlib,unicodedata
from .model import GameError,integer
from .rules import canonical_bytes
HIDDEN='hidden-001'


def enabled(engine):
    if engine.catalog.exploration is None or 'universe' not in engine.catalog.data:raise GameError('FEATURE_UNAVAILABLE')
    return engine.catalog.exploration


def state(world):return world.phase3_state.setdefault('exploration',{'players':{},'arrivals':[]})
def player_state(world,pid):
    return state(world)['players'].setdefault(pid,{'device':False,'space':False,'position':None,'trip':None,'found_at':None,'name':None,'hint':None,'notebook':[]})
def discovered(world,pid):return world.phase3_state.get('exploration',{}).get('players',{}).get(pid,{}).get('found_at') is not None

def coordinates(catalog):
    result={r['planet_id']:[r['x'],r['y']] for r in catalog.data.get('universe',{}).get('coordinates',[])}
    raw=catalog.data.get('universe',{}).get('private_world')
    if raw:result[HIDDEN]=[raw['position']['x'],raw['position']['y']]
    return result

def distance(a,b):return max(abs(a[0]-b[0]),abs(a[1]-b[1]))
def stationary(engine,world,pid):
    p=engine.player(world,pid)
    if p.destination_id is not None:raise GameError('IN_TRANSIT')
    return p

def position(engine,world,pid):
    p=engine.player(world,pid);s=player_state(world,pid)
    return s['position'] if s['space'] else coordinates(engine.catalog)[p.planet_id]


def buy_device(engine,world,pid):
    cfg=enabled(engine);p=engine.docked(world,pid);s=player_state(world,pid)
    if s['device']:raise GameError('DEVICE_OWNED')
    if p.cash<cfg['device_price']:raise GameError('INSUFFICIENT_FUNDS')
    p.cash-=cfg['device_price'];s['device']=True
    return {'device':True,'paid_credits':cfg['device_price']}


def quote(engine,world,pid,x,y,mode='normal',level=None):
    cfg=enabled(engine);p=stationary(engine,world,pid);s=player_state(world,pid)
    if not s['device']:raise GameError('DEVICE_REQUIRED')
    integer(x,0,239);integer(y,0,119)
    start=position(engine,world,pid);units=abs(x-start[0])+abs(y-start[1])
    if not units:raise GameError('SAME_COORDINATES')
    template=engine.catalog.data['universe']['template'];plan=next(r for r in template['navigation']['plans'] if r['ship_id']==p.ship_id)
    seconds=plan['normal_seconds'];cost=0
    if mode=='warp':
        option=next((r for r in plan['warp_options'] if r['level']==level),None)
        if option is None:raise GameError('WARP_LEVEL_UNAVAILABLE')
        seconds=option['seconds'];cost=integer(option['fuel_cost']*units)
    elif mode!='normal' or level is not None:raise GameError('INVALID_NAVIGATION')
    factor=max(units,(engine.catalog.phase3 or {}).get('navigation_min_distance_units',1))
    seconds=integer((seconds*factor*10000+cfg['offroute_speed_bps']-1)//cfg['offroute_speed_bps'],1)
    result={'origin':start,'x':x,'y':y,'mode':mode,'level':level,'seconds':seconds,'fuel_cost':cost,'ship_id':p.ship_id}
    from .rules import fingerprint
    result['quote_id']=hashlib.sha256(canonical_bytes([fingerprint(engine.catalog),pid,result])).hexdigest()
    result['estimated_arrival_at']=integer(world.game_time+seconds)
    result['distance']=units
    return result


def depart(engine,world,pid,x,y,mode,level,quote_id):
    q=quote(engine,world,pid,x,y,mode,level)
    if not quote_id or q['quote_id']!=quote_id:raise GameError('QUOTE_CHANGED')
    p=engine.player(world,pid);s=player_state(world,pid)
    if p.cash<q['fuel_cost']:raise GameError('INSUFFICIENT_FUNDS')
    arrival=integer(world.game_time+q['seconds']);p.cash-=q['fuel_cost']
    s['trip']={**q,'departure_at':world.game_time,'arrival_at':arrival};s['hint']=None
    # Existing FK-valid transit marker; public projections never present it as the destination.
    p.destination_id=p.planet_id;p.arrival_at=arrival
    return {**q,'arrival_at':arrival,'fee':q['fuel_cost']}


def settle(engine,world):
    if engine.catalog.exploration is None:return
    coords=coordinates(engine.catalog);hidden=coords[HIDDEN];cfg=engine.catalog.exploration
    trips=[]
    for pid,s in state(world)['players'].items():
        trip=s.get('trip');p=world.players.get(pid)
        if not trip or p is None:continue
        if p.destination_id is None:
            s.update(trip=None,space=False,position=None);continue
        # Existing storm/failure events may postpone the authoritative arrival.
        trip['arrival_at']=p.arrival_at
        if p.arrival_at<=world.game_time:trips.append((p.arrival_at,pid,s,trip))
    for when,pid,s,trip in sorted(trips,key=lambda row:(row[0],row[1])):
        p=world.players[pid];point=[trip['x'],trip['y']];d=distance(point,hidden)
        s.update(trip=None,position=point,space=True,hint=None)
        p.destination_id=None;p.arrival_at=None
        planet=next((key for key,value in coords.items() if value==point),None)
        if planet:
            p.planet_id=planet;s['space']=False;world.exploration_events.append((pid,planet,when,'arrival'))
        if d==0:
            s['hint']='discovered'
            if s['found_at'] is None:
                s['found_at']=when
                state(world)['arrivals'].append({'player_id':pid,'display_name':p.handle,'at':when,'name':None,'rank':len(state(world)['arrivals'])+1,'round_id':world.season_id,'universe_id':engine.catalog.data['universe']['universe_id']})
        else:
            for limit,kind in zip(cfg['hint_thresholds'],('bright','strong','faint')):
                if d<=limit:s['hint']=kind;break
        from .mechanics import player_state as ship_state
        ship_state(world,pid)['mining_since']=when


def flight(engine,world,pid):
    enabled(engine);p=engine.player(world,pid);s=player_state(world,pid);trip=s['trip']
    if not trip and not s['space'] and p.planet_id!=HIDDEN:return None
    point=position(engine,world,pid)
    if trip:
        start=trip.get('segment_start',trip['departure_at']);origin=trip.get('segment_position',trip['origin'])
        end=p.arrival_at;elapsed=max(0,min(end-start,world.game_time-start));duration=max(1,end-start)
        point=[origin[i]+([trip['x'],trip['y']][i]-origin[i])*elapsed//duration for i in (0,1)]
    return {'origin_id':None if s['space'] else p.planet_id,'destination_id':'coordinates' if trip else None,
            'departure_at':trip['departure_at'] if trip else None,'arrival_at':p.arrival_at,
            'remaining_seconds':max(0,(p.arrival_at or world.game_time)-world.game_time),'position':point,
            'target':[trip['x'],trip['y']] if trip else None,'origin_position':trip['origin'] if trip else point}


def info(engine,world,pid):
    cfg=enabled(engine);p=engine.player(world,pid);s=player_state(world,pid)
    template=engine.catalog.data['universe']['template'];plan=next(r for r in template['navigation']['plans'] if r['ship_id']==p.ship_id)
    return {'device':s['device'],'device_price':cfg['device_price'],'guild_price':cfg['guild_price'],
            'found':s['found_at'] is not None,'naming_pending':s['found_at'] is not None and s['name'] is None,
            'personal_name':s['name'],'hint':s['hint'],'in_space':s['space'],'coordinate_warps':[r['level'] for r in plan['warp_options']]}


def nearby(engine,world,pid):
    enabled(engine);stationary(engine,world,pid);origin=position(engine,world,pid)
    return sorted([{'planet_id':k,'name':engine.catalog.planets[k]['name'],'x':xy[0],'y':xy[1],'distance':distance(origin,xy),'navigation_distance':sum(abs(a-b) for a,b in zip(origin,xy))}
                   for k,xy in coordinates(engine.catalog).items() if k!=HIDDEN],key=lambda row:(row['distance'],row['planet_id']))


def public_rumor(row):return {k:row[k] for k in ('id','at','template','planet_id','planet_name')}
def rumor(engine,world,pid):
    cfg=enabled(engine);s=player_state(world,pid);coords=coordinates(engine.catalog)
    truthful=engine.random_below(10000)<cfg['truth_bps']
    choices=[k for k,xy in coords.items() if k!=HIDDEN and (distance(xy,coords[HIDDEN])<=cfg['rumor_radius'])==truthful]
    if not choices:raise GameError('CONFIG_VERIFICATION_FAILED')
    row={'id':len(s['notebook'])+1,'at':world.game_time,'template':engine.random_below(4),'planet_id':choices[engine.random_below(len(choices))],'truth':truthful}
    row['planet_name']=engine.catalog.planets[row['planet_id']]['name']
    s['notebook'].append(row);return public_rumor(row)

def guild(engine,world,pid):
    cfg=enabled(engine);p=engine.docked(world,pid)
    if p.cash<cfg['guild_price']:raise GameError('INSUFFICIENT_FUNDS')
    p.cash-=cfg['guild_price'];return {'paid_credits':cfg['guild_price'],'rumor':rumor(engine,world,pid)}

def after_operation(engine,world,pid,method,result):
    cfg=engine.catalog.exploration
    if cfg is None:return
    if method=='bankrupt':player_state(world,pid).update(device=False,space=False,position=None,trip=None,hint=None)
    key='trade_rumor_bps' if method in ('buy_goods','sell_goods') else 'departure_rumor_bps' if method in ('navigate','depart','coordinate_depart') else None
    if key and engine.random_below(10000)<cfg[key]:result['rumor']=rumor(engine,world,pid)

def notebook(engine,world,pid):
    enabled(engine);stationary(engine,world,pid)
    return [public_rumor(row) for row in reversed(player_state(world,pid)['notebook'])]

def name(engine,world,pid,value):
    enabled(engine);stationary(engine,world,pid);s=player_state(world,pid)
    if s['found_at'] is None:raise GameError('DISCOVERY_REQUIRED')
    if s['name'] is not None:raise GameError('NAME_FINAL')
    if not isinstance(value,str) or not value.strip() or len(value)>20 or any(unicodedata.category(c).startswith('C') or not c.isprintable() for c in value):raise GameError('INVALID_STAR_NAME')
    s['name']=value
    for row in state(world)['arrivals']:
        if row['player_id']==pid:row['name']=value
    return {'personal_name':value}

def arrivals(engine,world,pid):
    enabled(engine);stationary(engine,world,pid)
    return copy.deepcopy(state(world)['arrivals'])


def archived_arrivals(repository):
    """Read only the safe arrival projection; private archives never leave the server."""
    import json,zlib
    result=[]
    for archive in repository.connection.execute('SELECT round_id,snapshot,sha256 FROM p4_archives ORDER BY round_id'):
        raw=zlib.decompress(archive['snapshot'])
        if hashlib.sha256(raw).hexdigest()!=archive['sha256']:raise GameError('CONFIG_VERIFICATION_FAILED')
        tables=json.loads(raw)['tables']
        for row in tables.get('phase3_state',[]):
            for arrival in json.loads(row['state_json']).get('exploration',{}).get('arrivals',[]):
                result.append({k:arrival[k] for k in ('player_id','display_name','at','name','rank','round_id','universe_id')})
    return result
