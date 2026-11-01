"""Versioned exchange format and pure validation/adapter. No generation or DB IO.

Package validation is not registration, activation, distribution or signature verification.
"""
import copy
import hashlib
from datetime import datetime,timezone
from .rules import canonical_bytes
from .development import INDUSTRIES
from .universe import normal_planets,seal_manifest
from .model import integer

FORMAT='starroute-universe-package'
SCHEMA_VERSION=1


def digest(package):
    return hashlib.sha256(canonical_bytes({k:v for k,v in package.items() if k!='integrity'})).hexdigest()


def export_package(data,created_at=None):
    from .catalog import Catalog
    c=Catalog(data)
    if data['universe']['format_version']!=2:raise ValueError('level universe required')
    names={r['id']:r for r in normal_planets()};u=data['universe']
    coords={r['planet_id']:{k:r[k] for k in ('x','y')} for r in u['coordinates']}
    initial={(r['planet_id'],r['goods_id']):r for r in data['markets']}
    def common(group,exclude):return {k:copy.deepcopy(v) for k,v in data[group].items() if k not in exclude}
    rules=dict(catalog_format=data['format_version'],initial_credits=data['starting']['cash'],initial_ship=data['starting']['ship_id'],
        commodities=copy.deepcopy(data['goods']),vessels=copy.deepcopy(data['ships']),grades=copy.deepcopy(data['ship_grades']),
        economy=common('economy',{'markets'}),investment=common('development',{'planets'}),
        production=common('production',{'sources','imports'}),industry_effects=common('industry_effects',{'planets'}),
        regional_prices=copy.deepcopy(data['regional_prices']),events=copy.deepcopy(c.market_events),navigation_status=data['navigation']['status'])
    if c.phase3 is not None:rules['phase3']=copy.deepcopy(c.phase3)
    targets=rules['events'].pop('targets',[])
    planets=[]
    for pid in sorted(c.planets):
        dev=c.development_planets[pid]
        planets.append(dict(planet_id=pid,names={k:names[pid][k] for k in ('ja','en')},position=coords[pid],
            industries={i:dict(initial_level=dev['initial_progress'][i],maximum_level=dev['private_caps'][i]) for i in INDUSTRIES},
            resources=copy.deepcopy(dev['resources']),
            output=[{k:v for k,v in row.items() if k!='planet_id'} for key,row in sorted(c.production_sources.items()) if key[0]==pid],
            imports=[dict(goods_id=g,units_per_tick=v) for (p,g),v in sorted(c.production_imports.items()) if p==pid],
            markets=[dict(goods_id=g,initial_price=initial[pid,g]['price'],initial_stock=initial[pid,g]['stock'],
                pricing={k:v for k,v in c.economy_markets[pid,g].items() if k not in ('planet_id','goods_id')}) for g in sorted(c.goods)],
            effects={k:copy.deepcopy(v) for k,v in c.industry_effect_planets[pid].items() if k!='planet_id'}))
    package=dict(format=FORMAT,schema_version=SCHEMA_VERSION,
        metadata=dict(universe_id=u['universe_id'],generator_version=u['generator_version'],game_rules_version=u['game_rules_version'],
                      created_at=created_at or datetime.now(timezone.utc).isoformat(),universe_data_version=u['definition_hash']),
        reproduction=dict(recipe_schema_version=1,seed=u['seed'],parameters=copy.deepcopy(u['parameters']),industry_levels=copy.deepcopy(u['industry_levels']),
                          template_format='srt-catalog-v2',template=copy.deepcopy(u['template'])),
        rules=rules,world=dict(start_planet=data['starting']['planet_id'],planets=planets,
                              routes=copy.deepcopy(data['routes']),travel_plans=copy.deepcopy(data['navigation']['plans']),event_targets=copy.deepcopy(targets)))
    package['integrity']={'algorithm':'sha256','sha256':digest(package)}
    to_catalog(package)
    return package


def fields(row,expected):
    if not isinstance(row,dict) or set(row)!=set(expected.split()):raise ValueError('package fields')


def to_catalog(package):
    """Validate all 192 level pairs and adapt a private package to runtime data."""
    fields(package,'format schema_version metadata reproduction rules world integrity')
    if package['format']!=FORMAT or type(package['schema_version']) is not int or package['schema_version']!=SCHEMA_VERSION:raise ValueError('unsupported package version')
    fields(package['integrity'],'algorithm sha256')
    if package['integrity']['algorithm']!='sha256' or package['integrity']['sha256']!=digest(package):raise ValueError('package checksum mismatch')
    m=package['metadata'];fields(m,'universe_id generator_version game_rules_version created_at universe_data_version')
    timestamp=datetime.fromisoformat(m['created_at'])
    if timestamp.tzinfo is None:raise ValueError('generation time requires timezone')
    recipe=package['reproduction'];fields(recipe,'recipe_schema_version seed parameters industry_levels template_format template')
    if type(recipe['recipe_schema_version']) is not int or recipe['recipe_schema_version']!=1 or recipe['template_format']!='srt-catalog-v2':raise ValueError('unsupported recipe')
    r=package['rules'];fields({k:v for k,v in r.items() if k!='phase3'},'catalog_format initial_credits initial_ship commodities vessels grades economy investment production industry_effects regional_prices events navigation_status')
    w=package['world'];fields(w,'start_planet planets routes travel_plans event_targets')
    names={p['id']:p for p in normal_planets()};seen=set();coordinates=[]
    data=dict(format_version=r['catalog_format'],starting=dict(cash=r['initial_credits'],ship_id=r['initial_ship'],planet_id=w['start_planet']),
        goods=copy.deepcopy(r['commodities']),ships=copy.deepcopy(r['vessels']),ship_grades=copy.deepcopy(r['grades']),planets=[],routes=copy.deepcopy(w['routes']),markets=[],
        economy=copy.deepcopy(r['economy']),development=copy.deepcopy(r['investment']),production=copy.deepcopy(r['production']),
        industry_effects=copy.deepcopy(r['industry_effects']),regional_prices=copy.deepcopy(r['regional_prices']),market_events=copy.deepcopy(r['events']),
        navigation=dict(status=r['navigation_status'],plans=copy.deepcopy(w['travel_plans'])))
    if 'phase3' in r:data['phase3']=copy.deepcopy(r['phase3'])
    for group,key in [('economy','markets'),('development','planets'),('production','sources'),('production','imports'),('industry_effects','planets')]:
        if key in data[group]:raise ValueError('world data mixed into shared rules')
        data[group][key]=[]
    if 'targets' in data['market_events']:raise ValueError('event targets in rules')
    if data['market_events']['mode']!='disabled':data['market_events']['targets']=copy.deepcopy(w['event_targets'])
    elif w['event_targets']:raise ValueError('disabled events with targets')
    if data['development']['mode']!='linear_levels_v1':raise ValueError('level policy required')
    if not isinstance(w['planets'],list) or len(w['planets'])!=48:raise ValueError('48 planets required')
    for p in w['planets']:
        fields(p,'planet_id names position industries resources output imports markets effects');pid=p['planet_id']
        if pid not in names or pid in seen:raise ValueError('planet identity')
        seen.add(pid);fields(p['names'],'ja en')
        if p['names']!={k:names[pid][k] for k in ('ja','en')}:raise ValueError('formal planet names')
        fields(p['position'],'x y');coordinates.append(dict(planet_id=pid,**p['position']))
        fields(p['industries'],' '.join(INDUSTRIES));initial={};caps={}
        for industry,row in p['industries'].items():
            fields(row,'initial_level maximum_level')
            maximum=integer(row['maximum_level'],1);level=integer(row['initial_level'],0,maximum)
            initial[industry]=level;caps[industry]=maximum
        data['planets'].append(dict(id=pid,name=p['names']['en']))
        data['development']['planets'].append(dict(planet_id=pid,initial_progress=initial,private_caps=caps,resources=copy.deepcopy(p['resources'])))
        fields(p['effects'],'production_bps_per_unit market_bps_per_unit')
        data['industry_effects']['planets'].append(dict(planet_id=pid,**copy.deepcopy(p['effects'])))
        for row in p['output']:
            fields(row,'goods_id industry units_per_tick');data['production']['sources'].append(dict(planet_id=pid,**row))
        for row in p['imports']:
            fields(row,'goods_id units_per_tick');data['production']['imports'].append(dict(planet_id=pid,**row))
        for row in p['markets']:
            fields(row,'goods_id initial_price initial_stock pricing')
            if 'planet_id' in row['pricing'] or 'goods_id' in row['pricing']:raise ValueError('market identity override')
            data['markets'].append(dict(planet_id=pid,goods_id=row['goods_id'],price=row['initial_price'],stock=row['initial_stock']))
            data['economy']['markets'].append(dict(planet_id=pid,goods_id=row['goods_id'],**row['pricing']))
    if seen!=set(names):raise ValueError('planet coverage')
    data['universe']=dict(format_version=2,universe_id=m['universe_id'],generator_version=m['generator_version'],game_rules_version=m['game_rules_version'],
        seed=recipe['seed'],parameters=copy.deepcopy(recipe['parameters']),industry_levels=copy.deepcopy(recipe['industry_levels']),template=copy.deepcopy(recipe['template']),coordinates=coordinates)
    seal_manifest(data)
    if data['universe']['definition_hash']!=m['universe_data_version']:raise ValueError('universe data version mismatch')
    from .catalog import Catalog
    return Catalog(data)
