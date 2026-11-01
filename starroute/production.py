"""Fixed per-planet production definitions; not mutable market state."""
from .model import integer
from .development import INDUSTRIES


def policy(data, identifier):
    raw=data.get('production')
    enabled=data.get('economy',{}).get('mode')=='planet_supply_v1' if isinstance(data.get('economy'),dict) else False
    if raw is None or raw=={'mode':'disabled'}:
        if enabled:raise ValueError('production required')
        return {'mode':'disabled'}
    if not enabled or not isinstance(raw,dict) or set(raw)-{'mode','status','sources','imports'} or not {'mode','status','sources'}<=set(raw) or raw['mode']!='per_planet_v1' or raw['status']!='provisional':raise ValueError('production policy')
    markets={(r['planet_id'],r['goods_id']) for r in data['markets']}
    result={'mode':raw['mode'],'status':raw['status']}
    for group in ('sources','imports'):
        rows=raw.get(group,[]);seen=set();normalized=[]
        if not isinstance(rows,list):raise ValueError('production rows')
        fields={'planet_id','goods_id','units_per_tick'} | ({'industry'} if group=='sources' else set())
        for row in rows:
            if not isinstance(row,dict) or set(row)!=fields:raise ValueError('production fields')
            key=(identifier(row['planet_id']),identifier(row['goods_id']))
            if key not in markets or key in seen:raise ValueError('production reference')
            seen.add(key);integer(row['units_per_tick'],1)
            if group=='sources' and row['industry'] not in INDUSTRIES:raise ValueError('production industry')
            normalized.append(dict(row))
        result[group]=sorted(normalized,key=lambda r:(r['planet_id'],r['goods_id']))
    return result


def supply(catalog,key):
    return catalog.production_sources.get(key,{}).get('units_per_tick',0)+catalog.production_imports.get(key,0)


def public_view(catalog,world,planet):
    if catalog.production['mode']=='disabled':
        return {'planet_id':planet,'enabled':False,'tick_seconds':None,'entries':[]}
    entries=[]
    for good in catalog.goods:
        key=(planet,good);source=catalog.production_sources.get(key)
        entries.append({'goods_id':good,'produces':source is not None,
                        'industry':source['industry'] if source else None,
                        'production_per_tick':world.markets[key].production_rate if world.markets[key].production_rate is not None else (source['units_per_tick'] if source else 0),
                        'imports_per_tick':catalog.production_imports.get(key,0),
                        'available':world.markets[key].stock})
        if world.markets[key].capacity is not None:
            entries[-1]['market_capacity'] = world.markets[key].capacity
    return {'planet_id':planet,'enabled':True,'tick_seconds':catalog.economy['tick_seconds'],'entries':entries}
