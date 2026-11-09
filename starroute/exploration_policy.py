"""Pure exploration configuration and private runtime catalog validation."""
import copy
from .model import integer
HIDDEN="hidden-001"
def distance(a,b):return max(abs(a[0]-b[0]),abs(a[1]-b[1]))

def policy(data):
    p=data.get('exploration')
    if p is None:return None
    fields={'mode','status','device_price','offroute_speed_bps','guild_price','truth_bps','trade_rumor_bps','departure_rumor_bps','hint_thresholds','rumor_radius'}
    if not isinstance(p,dict) or set(p)!=fields or p['mode']!='coordinate_discovery_v1' or p['status']!='provisional':raise ValueError('exploration policy')
    if (p['device_price'],p['guild_price'],p['truth_bps'])!=(1000000,100,2000):raise ValueError('confirmed exploration values')
    for k in ('device_price','guild_price','truth_bps'):integer(p[k],1)
    integer(p['offroute_speed_bps'],1,10000)
    for k in ('trade_rumor_bps','departure_rumor_bps'):integer(p[k],0,10000)
    integer(p['rumor_radius'],1,240)
    if not isinstance(p['hint_thresholds'],list) or len(p['hint_thresholds'])!=3:raise ValueError('hint thresholds')
    last=0
    for value in p['hint_thresholds']:integer(value,last+1,240);last=value
    return copy.deepcopy(p)


def materialize(catalog):
    if catalog.exploration is None or 'universe' not in catalog.data:return
    if catalog.data['universe']['format_version']!=3:raise ValueError('connected universe required')
    from .hidden_world import economic_catalog
    expanded=economic_catalog(catalog.data)
    catalog.runtime_data=expanded.data
    for name in ('planets','economy','economy_markets','development','development_planets','production','production_sources','production_imports','regional_prices','regional_anchors','market_events','industry_effects','industry_effect_planets'):
        setattr(catalog,name,getattr(expanded,name))
    coords={r['planet_id']:[r['x'],r['y']] for r in catalog.data['universe']['coordinates']}
    raw=catalog.data['universe']['private_world'];hidden=[raw['position']['x'],raw['position']['y']]
    radius=catalog.exploration['rumor_radius']
    near=[p for p,xy in coords.items() if p!=HIDDEN and distance(xy,hidden)<=radius]
    far=[p for p,xy in coords.items() if p!=HIDDEN and distance(xy,hidden)>radius]
    if not near or not far:raise ValueError('rumor regions require true and false candidates')


