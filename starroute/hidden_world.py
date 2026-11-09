"""Private initial data adapter. Never used by a public API or by discovery gameplay.

The private catalog is validated with the ordinary economy validators. The live
undiscovered world retains exactly 48 public planets. A future authorized discovery
transition must explicitly integrate this data; no BBS can request this adapter.
"""
import copy
from .model import integer


def economic_catalog(data):
    from .catalog import Catalog
    hidden=data['universe']['private_world'];pid=hidden['planet_id']
    result=copy.deepcopy({k:v for k,v in data.items() if k!='universe'})
    result['planets'].append({'id':pid,'name':'Undiscovered'})
    result['markets'].extend(copy.deepcopy(hidden['markets']))
    for group,key,part in [('development','planets','development'),('industry_effects','planets','effects')]:
        result[group][key].append(copy.deepcopy(hidden[part]))
    for group,key,part in [('economy','markets','pricing'),('production','sources','sources'),('production','imports','imports')]:
        result[group][key].extend(copy.deepcopy(hidden[part]))
    if result['market_events']['mode']!='disabled':result['market_events']['targets'].extend(copy.deepcopy(hidden['events']))
    return Catalog(result)


def validate_hidden(catalog):
    data=catalog.data;raw=data['universe'];h=raw.get('private_world');params=raw['parameters']
    fields={'planet_id','position','reference_planet_id','development','effects','markets','pricing','sources','imports','events','buyback'}
    if not isinstance(h,dict) or set(h)!=fields or h['planet_id']!='hidden-001' or h['planet_id'] in catalog.planets:raise ValueError('hidden planet identity')
    if not isinstance(h['position'],dict) or set(h['position'])!={'x','y'}:raise ValueError('hidden position')
    x=integer(h['position']['x'],0,params['width']-1);y=integer(h['position']['y'],0,params['height']-1)
    coords={r['planet_id']:(r['x'],r['y']) for r in raw['coordinates']}
    distances={pid:max(abs(x-c[0]),abs(y-c[1])) for pid,c in coords.items()}
    if len(distances)!=48 or min(distances.values())<params['hidden_min_distance']:raise ValueError('hidden separation')
    if h['reference_planet_id'] not in distances or distances[h['reference_planet_id']]>params['hidden_reference_max_distance']:raise ValueError('hidden reference distance')
    if set(h['buyback'])!=set(catalog.goods) or any(type(v) is not int or v!=catalog.market_buyback['initial'] for v in h['buyback'].values()):raise ValueError('hidden buyback')
    for part in ('markets','pricing','sources','imports','events'):
        if not isinstance(h[part],list) or any(r.get('planet_id')!=h['planet_id'] for r in h[part]):raise ValueError('hidden economic reference')
    for part in ('development','effects'):
        if h[part].get('planet_id')!=h['planet_id']:raise ValueError('hidden development reference')
    for ind,bounds in raw['industry_levels']['maximum_ranges'].items():
        maximum=integer(h['development']['private_caps'][ind],bounds['min'],bounds['max'])
        initial=integer(h['development']['initial_progress'][ind],0,maximum)
        policy=raw['industry_levels']['initial_policy']
        if policy=='zero_v1' and initial!=0 or policy=='maximum_v1' and initial!=maximum:raise ValueError('hidden initial policy')
    def normalized(rows):
        from .rules import canonical_bytes
        return sorted((canonical_bytes({k:v for k,v in row.items() if k!='planet_id'}) for row in rows))
    def matches(pid):
        for part,rows in [('markets',data['markets']),('pricing',data['economy']['markets']),('sources',data['production']['sources']),('imports',data['production']['imports']),('events',data['market_events'].get('targets',[]))]:
            if normalized(h[part])!=normalized([r for r in rows if r['planet_id']==pid]):return False
        if h['development']['resources']!=catalog.development_planets[pid]['resources']:return False
        return normalized([h['effects']])==normalized([catalog.industry_effect_planets[pid]])
    if not any(matches(pid) for pid in catalog.planets):raise ValueError('hidden economy binding')
    economic_catalog(data)
