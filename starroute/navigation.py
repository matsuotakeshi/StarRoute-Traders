"""Explicit navigation tables: no unapproved fuel-price formula is selected."""
from .model import integer


def navigation_plans(data, profiles):
    policy=data.get('navigation')
    if policy is None:
        return {}, 'legacy'
    if data['format_version']!=2 or set(policy)!={'status','plans'} or policy['status'] not in ('provisional','confirmed'):
        raise ValueError('navigation policy')
    if not isinstance(policy['plans'],list):
        raise ValueError('navigation plans')
    routes={r['id'] for r in data['routes']}
    plans={}
    for row in policy['plans']:
        if set(row)!={'ship_id','route_id','normal_seconds','warp_options'}:
            raise ValueError('plan fields')
        key=(row['ship_id'],row['route_id'])
        if key in plans or row['ship_id'] not in profiles or row['route_id'] not in routes:
            raise ValueError('plan reference')
        integer(row['normal_seconds'],1)
        if not isinstance(row['warp_options'],list):
            raise ValueError('warp options')
        profile=profiles[row['ship_id']]
        levels=set();speeds=set();ordered=[]
        for option in row['warp_options']:
            if set(option)!={'level','speed','seconds','fuel_cost'}:
                raise ValueError('warp option fields')
            from .catalog import identifier
            identifier(option['level'])
            if option['level'] in levels or option['speed'] in speeds:
                raise ValueError('duplicate warp level or speed')
            for k in ('speed','seconds','fuel_cost'):integer(option[k],1)
            if profile.max_warp_speed is None or profile.normal_speed is None or not profile.normal_speed<option['speed']<=profile.max_warp_speed:
                raise ValueError('warp speed outside ship capability')
            if option['seconds']>=row['normal_seconds']:
                raise ValueError('warp must save time')
            levels.add(option['level']);speeds.add(option['speed']);ordered.append(option)
        ordered.sort(key=lambda o:o['speed'])
        for slow,fast in zip(ordered,ordered[1:]):
            if fast['seconds']>=slow['seconds'] or fast['fuel_cost']<=slow['fuel_cost']:
                raise ValueError('faster warp requires more fuel and less time')
        plans[key]=row
    if set(plans)!={(s,r) for s in profiles for r in routes}:
        raise ValueError('navigation table must cover every ship and route')
    for rid in routes:
        normals=[(p,plans[(p.ship_id,rid)]) for p in profiles.values() if p.ship_type=='normal']
        for standard,normal in normals:
            for p in profiles.values():
                candidate=plans[(p.ship_id,rid)]
                if p.ship_type in ('normal','armed_cruiser') and candidate['normal_seconds']!=normal['normal_seconds']:
                    raise ValueError('normal and armed cruise time independent of grade')
                if p.ship_type=='engineering' and candidate['normal_seconds']<=normal['normal_seconds']:
                    raise ValueError('engineering cruise must be slower')
    return plans,policy['status']
