"""Server-side development policy. Public projections never include limits."""
from .model import integer, GameError

INDUSTRIES=('primary','secondary','tertiary','quaternary')


def policy(data, identifier):
    raw=data.get('development')
    if raw is None or raw=={'mode':'disabled'}:return {'mode':'disabled'}
    if not isinstance(raw,dict) or set(raw)!={'mode','status','credits_per_unit','engineering_bonus_bps','planets'} or raw['mode'] not in ('linear_units_v1','linear_levels_v1') or raw['status']!='provisional':
        raise ValueError('development policy')
    rates=raw['credits_per_unit']
    if not isinstance(rates,dict) or set(rates)!=set(INDUSTRIES):raise ValueError('industries')
    for v in rates.values():integer(v,1)
    integer(raw['engineering_bonus_bps'],1,10000)
    expected={r['id'] for r in data['planets']};seen=set();planets=[]
    if not isinstance(raw['planets'],list):raise ValueError('planets')
    for row in raw['planets']:
        if not isinstance(row,dict) or set(row)!={'planet_id','initial_progress','private_caps','resources'}:raise ValueError('planet fields')
        key=identifier(row['planet_id'])
        if key not in expected or key in seen:raise ValueError('planet reference')
        seen.add(key)
        for field in ('initial_progress','private_caps'):
            if not isinstance(row[field],dict) or set(row[field])!=set(INDUSTRIES):raise ValueError('industries')
            for v in row[field].values():integer(v,1 if field=='private_caps' and raw['mode']=='linear_levels_v1' else 0)
        if any(row['initial_progress'][k]>row['private_caps'][k] for k in INDUSTRIES):raise ValueError('progress')
        resources=row['resources'];ids=set()
        if not isinstance(resources,list):raise ValueError('resources')
        for resource in resources:
            if not isinstance(resource,dict) or set(resource)!={'resource_id','abundance','rare'}:raise ValueError('resource fields')
            rid=identifier(resource['resource_id'])
            if rid in ids:raise ValueError('duplicate resource')
            ids.add(rid);integer(resource['abundance'],0,10000)
            if type(resource['rare']) is not bool:raise ValueError('resource flag')
        planets.append({'planet_id':key,'initial_progress':dict(row['initial_progress']),
                        'private_caps':dict(row['private_caps']),
                        'resources':sorted([dict(r) for r in resources],key=lambda r:r['resource_id'])})
    if seen!=expected:raise ValueError('planet coverage')
    return {'mode':raw['mode'],'status':raw['status'],'credits_per_unit':dict(rates),
            'engineering_bonus_bps':raw['engineering_bonus_bps'],'planets':sorted(planets,key=lambda r:r['planet_id'])}


def public_view(catalog,world,planet_id):
    row=catalog.development_planets.get(planet_id)
    if row is None:return {'planet_id':planet_id,'enabled':False,'industries':[],'resources':[]}
    return {'planet_id':planet_id,'enabled':True,
            'industries':[{'industry':k,'progress':world.developments[planet_id,k],**({'level':world.developments[planet_id,k]} if catalog.development['mode']=='linear_levels_v1' else {})} for k in INDUSTRIES],
            'resources':[{'resource_id':r['resource_id']} for r in row['resources']]}


def invest(catalog,world,player,industry,paid):
    integer(paid,1)
    if industry not in INDUSTRIES:raise GameError('INVALID_INDUSTRY')
    row=catalog.development_planets.get(player.planet_id)
    if row is None:raise GameError('DEVELOPMENT_UNAVAILABLE')
    rate=catalog.development['credits_per_unit'][industry]
    if paid%rate:raise GameError('INVALID_INVESTMENT')
    base=paid//rate
    bonus=catalog.development['engineering_bonus_bps'] if catalog.ship_profiles[player.ship_id].ship_type=='engineering' else 0
    remainder=0
    if catalog.phase3 is not None:
        from .mechanics import player_state
        account=player_state(world,player.id)['bonus_remainder'];key=player.planet_id+':'+industry
        remainder=account.get(key,0)
    extra,new_remainder=divmod(base*bonus+remainder,10000)
    effect=integer(base+extra,1)
    if player.cash<paid:raise GameError('INSUFFICIENT_FUNDS')
    current=world.developments[player.planet_id,industry]
    # No partial acceptance, remaining amount, limit, or saturation flag escapes.
    if current+effect>row['private_caps'][industry]:raise GameError('INVESTMENT_UNAVAILABLE')
    if catalog.phase3 is not None:account[key]=new_remainder
    player.cash-=paid
    world.developments[player.planet_id,industry]=current+effect
    return {'planet_id':player.planet_id,'industry':industry,'paid_credits':paid,
            'effect_units':effect,'progress':current+effect,**({'level':current+effect} if catalog.development['mode']=='linear_levels_v1' else {})}
