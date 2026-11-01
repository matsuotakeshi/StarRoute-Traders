"""Opt-in provisional geographical price anchors, independent of live scarcity."""
import heapq
from .model import integer


def policy(data, production, identifier):
    raw=data.get('regional_prices')
    if raw is None or raw=={'mode':'disabled'}:return {'mode':'disabled'}
    if not isinstance(raw,dict) or set(raw)!={'mode','status','metric','goods'} or raw['mode']!='distance_bias_v1' or raw['status']!='provisional' or raw['metric']!='shortest_configured_routes_v1' or production['mode']=='disabled':raise ValueError('regional policy')
    if not isinstance(raw['goods'],list):raise ValueError('regional goods')
    seen=set();rows=[];expected={r['id'] for r in data['goods']}
    for row in raw['goods']:
        if not isinstance(row,dict) or set(row)!={'goods_id','origin_price','price_per_distance','unreachable_price'}:raise ValueError('regional fields')
        key=identifier(row['goods_id'])
        if key not in expected or key in seen:raise ValueError('regional reference')
        seen.add(key)
        integer(row['origin_price'],1);integer(row['price_per_distance']);integer(row['unreachable_price'],1)
        rows.append(dict(row))
    if seen!=expected:raise ValueError('regional coverage')
    return {'mode':raw['mode'],'status':raw['status'],'metric':raw['metric'],'goods':sorted(rows,key=lambda r:r['goods_id'])}


def anchors(data,production,config):
    if config['mode']=='disabled':return {}
    graph={p['id']:[] for p in data['planets']}
    # All configured undirected routes define geography; current openness is not distance.
    for route in data['routes']:
        graph[route['from']].append((route['to'],route['distance']))
        graph[route['to']].append((route['from'],route['distance']))
    result={}
    for rule in config['goods']:
        good=rule['goods_id'];sources={r['planet_id'] for r in production['sources'] if r['goods_id']==good}
        distance={s:0 for s in sources};queue=[(0,s) for s in sorted(sources)];heapq.heapify(queue)
        while queue:
            dist,node=heapq.heappop(queue)
            if dist!=distance[node]:continue
            for neighbor,cost in graph[node]:
                candidate=dist+cost
                if neighbor not in distance or candidate<distance[neighbor]:
                    distance[neighbor]=candidate;heapq.heappush(queue,(candidate,neighbor))
        for planet in graph:
            dist=distance.get(planet)
            price=rule['unreachable_price'] if dist is None else rule['origin_price']+dist*rule['price_per_distance']
            integer(price,1)
            result[planet,good]={'goods_id':good,'distance':dist,'base_price':price,
                                 'basis':'no_source' if not sources else 'unreachable' if dist is None else 'distance'}
    return result


def base_price(catalog,market,planet,good):
    row=catalog.regional_anchors.get((planet,good))
    return (row['base_price'] if row else market.price)+market.shock
