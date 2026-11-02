"""Phase 3 domain operations. No IO, SQL, generator or presentation imports."""
import hashlib
from .model import GameError, integer
from .development import INDUSTRIES
from .rules import canonical_bytes


def enabled(engine):
    if engine.catalog.phase3 is None:raise GameError('FEATURE_UNAVAILABLE')
    return engine.catalog.phase3


def state(world):
    s=world.phase3_state
    for key in ('players','routes','news','events'):s.setdefault(key,{})
    s.setdefault('anchor',world.game_time);s.setdefault('slot',0)
    return s


def player_state(world,pid):
    return state(world)['players'].setdefault(pid,{'insured':False,'bonus_remainder':{},'mining_since':world.game_time})


def news(world,event_id,kind,planet_id=None,player_id=None,occurred_at=None,**values):
    rows=state(world)['news']
    rows.setdefault(event_id,dict(event_id=event_id,kind=kind,game_time=world.game_time if occurred_at is None else occurred_at,
                                 planet_id=planet_id,player_id=player_id,values=values))


def shipyard(engine,world,pid):
    cfg=enabled(engine);p=engine.docked(world,pid);c=engine.catalog
    return [dict(ship_id=sid,price=c.ship_profiles[sid].purchase_price,capacity=c.ships[sid]['capacity'],
                 available=all(world.developments[p.planet_id,i]>=v for i,v in req.items()))
            for sid,req in sorted(cfg['sales'].items())]


def buy_ship(engine,world,pid,sid):
    from .catalog import identifier
    identifier(sid)
    p=engine.docked(world,pid);offer=next((s for s in shipyard(engine,world,pid) if s['ship_id']==sid),None)
    if offer is None or not offer['available']:raise GameError('SHIP_UNAVAILABLE')
    if sid==p.ship_id:raise GameError('SHIP_ALREADY_OWNED')
    if engine.used_capacity(p)>offer['capacity']:raise GameError('INSUFFICIENT_CAPACITY')
    if p.cash<offer['price']:raise GameError('INSUFFICIENT_FUNDS')
    old=p.ship_id;p.cash-=offer['price'];p.ship_id=sid
    ps=player_state(world,pid);ps['insured']=False;ps['mining_since']=world.game_time
    return dict(ship_id=sid,old_ship_id=old,paid_credits=offer['price'])


def donate(engine,world,pid,rid,paid):
    from .catalog import identifier
    identifier(rid)
    cfg=enabled(engine);p=engine.docked(world,pid);integer(paid,1)
    r=world.routes.get(rid)
    if not r or p.planet_id not in (r['from'],r['to']):raise GameError('NO_ROUTE')
    if r['is_open']:raise GameError('ROUTE_ALREADY_OPEN')
    if p.cash<paid:raise GameError('INSUFFICIENT_FUNDS')
    rec=state(world)['routes'].setdefault(rid,dict(paid=0,effect=0,jackpot_paid=False,remainder=0))
    bonus=cfg['route_bonus_bps'] if engine.catalog.ship_profiles[p.ship_id].ship_type=='engineering' else 0
    extra,remainder=divmod(paid*bonus+rec['remainder'],10000)
    effect=integer(paid+extra);threshold=integer(r['distance']*cfg['route_cost_per_distance'])
    new_paid=integer(rec['paid']+paid);new_effect=integer(rec['effect']+effect)
    opened=new_effect>=threshold;reward=new_paid*cfg['jackpot_bps']//10000 if opened else 0
    integer(p.cash-paid+reward)
    p.cash=p.cash-paid+reward;rec.update(paid=new_paid,effect=new_effect,remainder=remainder)
    if opened:
        r['is_open']=True;rec['jackpot_paid']=True;rec['winner']=pid;rec['reward']=reward
        news(world,'route:'+rid,'route_open',route_id=rid,reward=reward)
    return dict(route_id=rid,paid_credits=paid,effect_units=effect,opened=opened,jackpot=reward)


def insure(engine,world,pid):
    enabled(engine);p=engine.docked(world,pid);ps=player_state(world,pid)
    if ps['insured']:raise GameError('ALREADY_INSURED')
    price=engine.catalog.ship_profiles[p.ship_id].insurance_premium
    if p.cash<price:raise GameError('INSUFFICIENT_FUNDS')
    p.cash-=price;ps['insured']=True
    return dict(ship_id=p.ship_id,paid_credits=price,insured=True)


def restart(engine,world,pid,accident=False):
    cfg=enabled(engine);p=engine.player(world,pid) if accident else engine.docked(world,pid)
    ps=player_state(world,pid);old=p.ship_id
    insured=accident and ps['insured']
    p.cargo.clear();p.destination_id=None;p.arrival_at=None
    p.planet_id=engine.catalog.data['starting']['planet_id']
    if insured:
        p.cash=integer(p.cash+engine.catalog.ship_profiles[old].purchase_price*cfg['insurance_cash_bps']//10000)
    else:
        p.cash=cfg['restart_cash'];p.ship_id=cfg['restart_ship']
    ps.update(insured=False,mining_since=world.game_time,bonus_remainder={})
    ps.pop('voyage',None)
    return dict(ship_id=p.ship_id,cash=p.cash,planet_id=p.planet_id,insured_rescue=insured)


def reward(engine,p,goods,quantity):
    free=engine.catalog.ships[p.ship_id]['capacity']-engine.used_capacity(p)
    quantity=min(quantity,max(0,free//engine.catalog.goods[goods]['volume']))
    if quantity:p.cargo[goods]=integer(p.cargo.get(goods,0)+quantity)
    return quantity


def apply_event(engine,world,event_id,kind,target):
    """Internal deterministic event sink; never expose injection through player APIs."""
    cfg=enabled(engine);s=state(world)
    if event_id in s['events']:
        saved=s['events'][event_id]
        if (saved['kind'],saved['target'])!=(kind,target):raise GameError('REQUEST_CONFLICT')
        return saved
    c=engine.catalog;result=dict(kind=kind,target=target)
    if kind in cfg['disaster_industries']:
        if target not in c.development_planets:raise GameError('PLANET_NOT_FOUND')
        changes=[]
        for industry in cfg['disaster_industries'][kind]:
            key=(target,industry);old=world.developments[key];new=max(0,old-cfg['disaster_damage'])
            world.developments[key]=new;changes.append(dict(industry=industry,before=old,after=new))
        result['changes']=changes
        # Effects take over at the next production boundary. Never rewrite elapsed supply.
        news(world,event_id,kind,planet_id=target,changes=changes)
    else:
        p=engine.player(world,target);profile=c.ship_profiles[p.ship_id]
        if kind in ('pirate','patrol','storm','failure','wreck') and p.destination_id is None:
            raise GameError('EVENT_NOT_ELIGIBLE')
        if kind=='pirate':
            if profile.ship_type=='armed_cruiser':raise GameError('EVENT_NOT_ELIGIBLE')
            loss=p.cash*cfg['pirate_loss_bps']//10000;p.cash-=loss;result['loss']=loss
        elif kind=='patrol':
            if profile.ship_type!='armed_cruiser':raise GameError('EVENT_NOT_ELIGIBLE')
            result.update(goods_id=cfg['loot_goods'],quantity=reward(engine,p,cfg['loot_goods'],cfg['loot_quantity']))
        elif kind=='mineral':
            if p.destination_id is not None or profile.ship_type!='engineering':raise GameError('EVENT_NOT_ELIGIBLE')
            rare=draw(cfg,event_id,'rare')<cfg['rare_bps']
            good=cfg['rare_goods'] if rare else cfg['mineral_goods']
            result.update(goods_id=good,quantity=reward(engine,p,good,cfg['loot_quantity']))
        elif kind=='storm':
            position=flight(engine,world,target)['position']
            p.arrival_at=integer(p.arrival_at+cfg['storm_delay'])
            # Rebase interpolation so a delay cannot make the displayed ship jump backwards.
            trip=player_state(world,target).get('voyage')
            if trip:trip.update(segment_start=world.game_time,segment_position=position)
            result['arrival_at']=p.arrival_at
        elif kind=='failure':
            loss=min(p.cash,cfg['repair_cost']);p.cash-=loss;result['loss']=loss
        elif kind=='wreck':result.update(restart(engine,world,target,True))
        else:raise GameError('INVALID_EVENT')
        news(world,event_id,kind,player_id=target,**{k:v for k,v in result.items() if k not in ('kind','target')})
    s['events'][event_id]=result
    return result


def draw(cfg,*keys):
    return int.from_bytes(hashlib.sha256(canonical_bytes([cfg['event_seed'],*keys])).digest(),'big')%10000


def event_tick(engine,world,slot):
    cfg=enabled(engine);interval=cfg['event_interval'];s=state(world)
    for pid in ([] if 'world_events' in cfg else sorted(engine.catalog.planets)):
        for kind in cfg['disaster_industries']:
            eid=f'planet:{slot}:{pid}:{kind}'
            if draw(cfg,eid)<cfg['event_probabilities'][kind]:apply_event(engine,world,eid,kind,pid)
    for pid,p in sorted(world.players.items()):
        ps=player_state(world,pid);profile=engine.catalog.ship_profiles[p.ship_id]
        if p.destination_id is not None and p.arrival_at>world.game_time:
            for kind in ('pirate','patrol','storm','failure','wreck'):
                if kind=='pirate' and profile.ship_type=='armed_cruiser':continue
                if kind=='patrol' and profile.ship_type!='armed_cruiser':continue
                eid=f'ship:{slot}:{pid}:{kind}'
                if draw(cfg,eid)<cfg['event_probabilities'][kind]:apply_event(engine,world,eid,kind,pid)
        elif p.destination_id is None and profile.ship_type=='engineering' and world.game_time-ps['mining_since']>=interval:
            row=engine.catalog.development_planets[p.planet_id]
            abundance=sum(r['abundance'] for r in row['resources'])
            chance=min(10000,cfg['mineral_base_bps']+world.developments[p.planet_id,'primary']*cfg['mineral_level_bps']+abundance//cfg['mineral_abundance_divisor'])
            eid=f'mineral:{slot}:{pid}'
            if draw(cfg,eid)<chance:apply_event(engine,world,eid,'mineral',pid)
    s['slot']=slot


def world_tick(engine,world,slot):
    """One draw per UTC interval for the entire universe; misses persist too."""
    cfg=enabled(engine);policy=cfg['world_events'];s=state(world)
    checks=s.setdefault('world_checks',{})
    key=str(slot)
    if key in checks:return checks[key]
    eid=f'world:{slot}'
    result={'slot':slot,'scheduled_at':slot*policy['interval_seconds'],'occurred':False}
    if draw(cfg,eid,'occurrence')<policy['probability_bps']:
        weights=sorted(policy['kind_weights'].items())
        n=int.from_bytes(hashlib.sha256(canonical_bytes([cfg['event_seed'],eid,'kind'])).digest(),'big')%sum(v for _,v in weights)
        for kind,weight in weights:
            if n<weight:break
            n-=weight
        planets=sorted(engine.catalog.planets)
        n=int.from_bytes(hashlib.sha256(canonical_bytes([cfg['event_seed'],eid,'planet'])).digest(),'big')%len(planets)
        target=planets[n];apply_event(engine,world,eid,kind,target)
        result.update(occurred=True,kind=kind,planet_id=target)
    checks[key]=result;s['world_slot']=slot
    return result


def coordinates(catalog):
    return {r['planet_id']:[r['x'],r['y']] for r in catalog.data.get('universe',{}).get('coordinates',[])}


def flight(engine,world,pid):
    p=engine.player(world,pid);coords=coordinates(engine.catalog);position=coords.get(p.planet_id,[0,0])
    trip=player_state(world,pid).get('voyage',{})
    if p.destination_id and p.destination_id in coords:
        start=trip.get('segment_start',trip.get('departure_at',world.game_time));origin=trip.get('segment_position',position)
        duration=max(1,p.arrival_at-start);elapsed=max(0,min(duration,world.game_time-start));destination=coords[p.destination_id]
        position=[origin[i]+(destination[i]-origin[i])*elapsed//duration for i in (0,1)]
    return dict(origin_id=p.planet_id,destination_id=p.destination_id,departure_at=trip.get('departure_at'),
                arrival_at=p.arrival_at,remaining_seconds=max(0,(p.arrival_at or world.game_time)-world.game_time),position=position)


def news_view(engine,world,pid):
    engine.player(world,pid)
    return [r for _,r in sorted(state(world)['news'].items(),key=lambda item:(item[1]['game_time'],item[0]))
            if r['player_id'] in (None,pid)][-100:]
