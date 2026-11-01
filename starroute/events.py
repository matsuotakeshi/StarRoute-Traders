"""Replayable independent slot draws; no global/random-module RNG state."""
import hashlib,json
from .model import integer,GameError
MAX_CATCHUP=1000

def policy(data,identifier):
    raw=data.get('market_events')
    if raw is None or raw=={'mode':'disabled'}:return {'mode':'disabled'}
    if not isinstance(raw,dict) or set(raw)!={'mode','status','seed','interval_seconds','duration_seconds','targets'} or raw['mode']!='slot_shocks_v1' or raw['status']!='provisional':raise ValueError('events')
    if not isinstance(data.get('economy'),dict) or data['economy']['mode']=='fixed':raise ValueError('event economy')
    identifier(raw['seed']);integer(raw['interval_seconds'],1);integer(raw['duration_seconds'],1,raw['interval_seconds'])
    if not isinstance(raw['targets'],list):raise ValueError('targets')
    markets={(r['planet_id'],r['goods_id']) for r in data['markets']};seen=set();rows=[]
    for row in raw['targets']:
        if set(row)!={'planet_id','goods_id','surge_bps','crash_bps','surge_credits','crash_credits'}:raise ValueError('event fields')
        key=(identifier(row['planet_id']),identifier(row['goods_id']))
        if key not in markets or key in seen:raise ValueError('event reference')
        seen.add(key)
        integer(row['surge_bps'],0,10000);integer(row['crash_bps'],0,10000)
        if row['surge_bps']+row['crash_bps']>10000:raise ValueError('probability')
        integer(row['surge_credits'],1);integer(row['crash_credits'],1);rows.append(dict(row))
    return {**raw,'targets':sorted(rows,key=lambda r:(r['planet_id'],r['goods_id']))}

def draw(seed,season,slot,planet,good):
    raw=json.dumps(['slot_shocks_v1',seed,season,slot,planet,good],separators=(',',':')).encode()
    return int.from_bytes(hashlib.sha256(raw).digest(),'big')%10000

def time_limit(catalog,world,target,partial=False):
    p=catalog.market_events
    if p['mode']=='disabled':return target
    due=max(0,(target-world.event_anchor)//p['interval_seconds'])
    if due-world.event_slot>MAX_CATCHUP:
        if not partial:raise GameError('EVENT_SYNC_REQUIRED')
        return world.event_anchor+(world.event_slot+MAX_CATCHUP)*p['interval_seconds']
    return target

def update(catalog,world):
    p=catalog.market_events
    if p['mode']=='disabled':return
    now=world.game_time;last=max(0,(now-world.event_anchor)//p['interval_seconds'])
    for slot in range(world.event_slot+1,last+1):
        start=world.event_anchor+slot*p['interval_seconds']
        for row in p['targets']:
            n=draw(p['seed'],world.season_id,slot,row['planet_id'],row['goods_id'])
            if n<row['surge_bps']:kind='surge';delta=row['surge_credits']
            elif n<row['surge_bps']+row['crash_bps']:kind='crash';delta=-row['crash_credits']
            else:continue
            record=dict(slot=slot,planet_id=row['planet_id'],goods_id=row['goods_id'],kind=kind,delta=delta,starts_at=start,ends_at=integer(start+p['duration_seconds']))
            world.pending_events.append(record);world.active_events.append(record)
    world.event_slot=last
    world.active_events=[r for r in world.active_events if r['starts_at']<=now<r['ends_at']]
    for m in world.markets.values():m.shock=0
    for r in world.active_events:world.markets[r['planet_id'],r['goods_id']].shock=r['delta']
