"""Generation input constraints shared by offline tools and package validation; no RNG."""
from .model import integer
from .development import INDUSTRIES

CONNECTED_VERSION='srt-universe-connected-v3'
CONNECTED_RULES_VERSION='universe-connected-1'
CONNECTED_MODE='grid_mst_connected_v2'
LEVEL_VERSION='srt-universe-levels-v2'
LEVEL_RULES_VERSION='phase3-industry-levels-1'


def level_parameters(raw):
    if not isinstance(raw,dict) or set(raw)!={'mode','status','maximum_ranges','initial_policy'} or raw['mode']!='independent_levels_v1' or raw['status']!='provisional':
        raise ValueError('industry level generation policy')
    if raw['initial_policy'] not in ('uniform_zero_to_max_v1','zero_v1','maximum_v1'):raise ValueError('initial policy')
    if not isinstance(raw['maximum_ranges'],dict) or set(raw['maximum_ranges'])!=set(INDUSTRIES):raise ValueError('industry ranges')
    for bounds in raw['maximum_ranges'].values():
        if not isinstance(bounds,dict) or set(bounds)!={'min','max'}:raise ValueError('level bounds')
        integer(bounds['min'],1);integer(bounds['max'],bounds['min'])
    return raw

def parameters(raw):
    fields={'mode','status','width','height','extra_neighbors','initial_open_routes',
            'production_percent_min','production_percent_max','max_attempts'}
    connected=isinstance(raw,dict) and raw.get('mode')==CONNECTED_MODE
    if connected:fields|={'hidden_min_distance','hidden_reference_max_distance'}
    if not isinstance(raw,dict) or set(raw)!=fields or raw['mode'] not in ('grid_mst_templates_v1',CONNECTED_MODE) or raw['status']!='provisional':
        raise ValueError('generator policy')
    integer(raw['width'],2,240);integer(raw['height'],2,128)
    if raw['width']*raw['height']<48:raise ValueError('insufficient coordinate cells')
    integer(raw['extra_neighbors'],1 if connected else 0,8)
    integer(raw['initial_open_routes'],47 if connected else 1,47 if connected else 46)
    if connected:
        if (raw['width'],raw['height'])!=(240,120):raise ValueError('connected chart dimensions')
        integer(raw['hidden_min_distance'],1,240);integer(raw['hidden_reference_max_distance'],1,240)
    integer(raw['production_percent_min'],1,10000)
    integer(raw['production_percent_max'],raw['production_percent_min'],10000)
    integer(raw['max_attempts'],1,128)
    return dict(raw)


def _template(data):
    from .catalog import Catalog
    if 'universe' in data:raise ValueError('nested generated template')
    c=Catalog(data)
    if (c.production['mode']=='disabled' or c.development['mode']=='disabled'
            or c.industry_effects['mode']=='disabled' or c.regional_prices['mode']=='disabled'
            or not c.navigation_plans):
        raise ValueError('trial requires production, development, effects, regional prices and navigation')
    if len(c.planets)>48:raise ValueError('too many templates')
    # The baseline is a set of economic templates, not fixed identities for the 48 names.
    if {k[1] for k in c.production_sources}!=set(c.goods):raise ValueError('each candidate good needs a production template')
    compositions={tuple(sorted(g for p,g in c.production_sources if p==pid)) for pid in c.planets}
    if len(compositions)<2:raise ValueError('at least two different production templates required')
    for ship in c.ships:
        plans=[{k:v for k,v in row.items() if k!='route_id'} for key,row in c.navigation_plans.items() if key[0]==ship]
        if any(row!=plans[0] for row in plans):raise ValueError('navigation templates must be route-independent')
    return c


