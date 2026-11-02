"""Retained v1 offline algorithm for existing reproducible fixtures."""
import copy,hashlib,uuid
from starroute.generation_contract import parameters,_template
from starroute.universe import VERSION,GENERATION_RULES_VERSION,normal_planets,_hash

class Draw:
    """Specified SHA-256 counter stream; independent of Python random versions."""
    def __init__(self,seed,attempt):self.seed=seed;self.attempt=attempt;self.counter=0

    def below(self,n):
        from starroute.rules import canonical_bytes
        # Rejection sampling avoids modulo bias. Bound is always a positive integer.
        limit=(1<<256)-((1<<256)%n)
        while True:
            raw=canonical_bytes([VERSION,self.seed,self.attempt,self.counter]);self.counter+=1
            value=int.from_bytes(hashlib.sha256(raw).digest(),'big')
            if value<limit:return value%n

    def shuffle(self,items):
        items=list(items)
        for i in range(len(items)-1,0,-1):
            j=self.below(i+1);items[i],items[j]=items[j],items[i]
        return items


def _compile(template,params,seed,universe_id):
    from starroute.catalog import identifier
    identifier(seed);params=parameters(params);c=_template(template)
    if not isinstance(universe_id,str) or str(uuid.UUID(universe_id))!=universe_id:raise ValueError('universe id')
    if c.phase3 is not None and (params['width'],params['height'])!=(240,120):raise ValueError('phase3 chart requires 240 by 120')
    names=normal_planets();ids=[r['id'] for r in names];templates=sorted(c.planets)
    max_edge=min(s['max_distance'] for s in c.ships.values())
    for attempt in range(params['max_attempts']):
        rng=Draw(seed,attempt)
        cells=rng.shuffle([(x,y) for x in range(params['width']) for y in range(params['height'])])[:48]
        coords=dict(zip(ids,cells))
        def distance(a,b):return abs(coords[a][0]-coords[b][0])+abs(coords[a][1]-coords[b][1])
        edges=sorted((distance(a,b),a,b) for i,a in enumerate(ids) for b in ids[i+1:] if distance(a,b)<=max_edge)
        parent={p:p for p in ids}
        def find(p):
            while p!=parent[p]:p=parent[p]
            return p
        selected=set()
        for dist,a,b in edges:
            x,y=find(a),find(b)
            if x!=y:parent[x]=y;selected.add((a,b))
        if len(selected)!=47:continue
        for pid in ids:
            nearby=[(d,a,b) for d,a,b in edges if pid in (a,b)]
            selected.update((a,b) for _,a,b in nearby[:params['extra_neighbors']])
        # Balanced shuffled template assignment guarantees each template is represented.
        assignments=dict(zip(ids,rng.shuffle([templates[i%len(templates)] for i in range(48)])))
        start=ids[rng.below(len(ids))];visited={start};opened=set()
        while len(opened)<params['initial_open_routes']:
            frontier=sorted((distance(a,b),a,b) for a,b in selected if (a in visited)!=(b in visited))
            if not frontier:break
            _,a,b=frontier[0];opened.add((a,b));visited.update((a,b))
        if len(opened)!=params['initial_open_routes']:continue
        d=copy.deepcopy(template)
        d['planets']=[{'id':r['id'],'name':r['en']} for r in names]
        d['starting']['planet_id']=start
        d['routes']=[dict(id=f'r{a}-{b}',**{'from':a,'to':b},distance=distance(a,b),seconds=distance(a,b),fee=0,is_open=(a,b) in opened) for a,b in sorted(selected)]
        d['navigation']['plans']=[]
        for ship in sorted(c.ships):
            base=next(row for (sid,_),row in c.navigation_plans.items() if sid==ship)
            for route in d['routes']:
                factor=route['distance']
                time_factor=max(factor,(c.phase3 or {}).get('navigation_min_distance_units',1))
                d['navigation']['plans'].append(dict(ship_id=ship,route_id=route['id'],normal_seconds=base['normal_seconds']*time_factor,
                    warp_options=[{**o,'seconds':o['seconds']*time_factor,'fuel_cost':o['fuel_cost']*factor} for o in base['warp_options']]))
        d['markets']=[];d['economy']['markets']=[];d['production']['sources']=[];d['production']['imports']=[]
        d['development']['planets']=[];d['industry_effects']['planets']=[]
        if c.market_events['mode']!='disabled':d['market_events']['targets']=[]
        initial={(r['planet_id'],r['goods_id']):r for r in template['markets']}
        for pid in ids:
            origin=assignments[pid]
            if c.market_events['mode']!='disabled':
                d['market_events']['targets'].extend({**row,'planet_id':pid} for row in c.market_events['targets'] if row['planet_id']==origin)
            for group in ('development','industry_effects'):
                base=next(row for row in template[group]['planets'] if row['planet_id']==origin)
                d[group]['planets'].append({**copy.deepcopy(base),'planet_id':pid})
            for good in sorted(c.goods):
                key=(origin,good)
                d['markets'].append({**initial[key],'planet_id':pid})
                d['economy']['markets'].append({**c.economy_markets[key],'planet_id':pid})
                if key in c.production_sources:
                    percent=params['production_percent_min']+rng.below(params['production_percent_max']-params['production_percent_min']+1)
                    base=c.production_sources[key]
                    d['production']['sources'].append({**base,'planet_id':pid,'units_per_tick':max(1,base['units_per_tick']*percent//100)})
                if key in c.production_imports:d['production']['imports'].append(dict(planet_id=pid,goods_id=good,units_per_tick=c.production_imports[key]))
        # Every good must retain at least two different domestic production capacities.
        if any(len({r['units_per_tick'] for r in d['production']['sources'] if r['goods_id']==g})<2 for g in c.goods):continue
        d['universe']=dict(format_version=1,generator_version=VERSION,game_rules_version=GENERATION_RULES_VERSION,
            universe_id=universe_id,seed=seed,parameters=copy.deepcopy(params),template=copy.deepcopy(template),
            coordinates=[dict(planet_id=p,x=coords[p][0],y=coords[p][1]) for p in ids])
        d['universe']['definition_hash']=_hash(d)
        # Reject a starting economy unable to buy and transport even one available item.
        from starroute.regional import policy,anchors
        from starroute.economy import price_at
        production=dict(c.production,sources=d['production']['sources'])
        region=anchors(d,production,policy(d,production,identifier))
        ship=c.ships[d['starting']['ship_id']];cash=d['starting']['cash']
        rows={r['goods_id']:r for r in d['economy']['markets'] if r['planet_id']==start}
        if not any(m['planet_id']==start and m['stock']>0 and c.goods[m['goods_id']]['volume']<=ship['capacity']
                   and price_at(region[start,m['goods_id']]['base_price'],m['stock']-1,rows[m['goods_id']])<=cash for m in d['markets']):continue
        return d
    raise ValueError('generation constraints unsatisfied; no world created')


def generate(template,params,seed,universe_id=None):
    from starroute.catalog import Catalog
    data=_compile(template,params,seed,universe_id or str(uuid.uuid4()))
    from starroute.universe import seal_manifest
    seal_manifest(data)
    Catalog(data)  # Validate all existing rules before any output is written.
    return data


