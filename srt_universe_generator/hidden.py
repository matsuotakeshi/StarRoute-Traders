"""Bounded offline placement and ordinary economic initialization of one private planet."""
import copy
from .legacy import Draw
from starroute.development import INDUSTRIES


def generate_hidden(data,seed,draw):
    raw=data['universe'];params=raw['parameters'];rng=Draw(seed+'-hidden',0)
    coordinates={r['planet_id']:(r['x'],r['y']) for r in raw['coordinates']}
    def distance(a,b):return max(abs(a[0]-b[0]),abs(a[1]-b[1]))
    position=None
    # Finite candidate enumeration, not unbounded random rejection.
    for reference in rng.shuffle(sorted(coordinates))[:params['max_attempts']]:
        rx,ry=coordinates[reference];radius=params['hidden_reference_max_distance']
        candidates=[(x,y) for x in range(max(0,rx-radius),min(params['width']-1,rx+radius)+1)
                    for y in range(max(0,ry-radius),min(params['height']-1,ry+radius)+1)
                    if all(distance((x,y),p)>=params['hidden_min_distance'] for p in coordinates.values())]
        if candidates:
            position=candidates[rng.below(len(candidates))];break
    if position is None:raise ValueError('hidden placement constraints unsatisfied')
    origin=sorted(coordinates)[rng.below(48)];pid='hidden-001'
    def rows(group,key=None):
        source=data[group] if key is None else data[group][key]
        return [{**copy.deepcopy(r),'planet_id':pid} for r in source if r['planet_id']==origin]
    development=rows('development','planets')[0]
    for industry in INDUSTRIES:
        bounds=raw['industry_levels']['maximum_ranges'][industry]
        maximum=bounds['min']+draw(pid,industry,'maximum',bounds['max']-bounds['min']+1)
        initial=draw(pid,industry,'initial',maximum+1)
        if raw['industry_levels']['initial_policy']=='zero_v1':initial=0
        if raw['industry_levels']['initial_policy']=='maximum_v1':initial=maximum
        development['private_caps'][industry]=maximum;development['initial_progress'][industry]=initial
    return dict(planet_id=pid,position=dict(x=position[0],y=position[1]),reference_planet_id=reference,
                development=development,effects=rows('industry_effects','planets')[0],
                markets=rows('markets'),pricing=rows('economy','markets'),
                sources=rows('production','sources'),imports=rows('production','imports'),
                events=rows('market_events','targets') if data['market_events']['mode']!='disabled' else [],
                buyback={r['id']:data['market_buyback']['initial'] for r in data['goods']})
