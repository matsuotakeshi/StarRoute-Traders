"""Owner-visible UI facts only; no prices or mechanics calculated by the client."""
def describe(engine,world,pid,visibility,bbs_id,connection):
    p=engine.player(world,pid);catalog=engine.catalog
    ps=world.phase3_state.get('players',{}).get(pid,{})
    ships=[]
    for sid,row in catalog.ships.items():
        profile=catalog.ship_profiles[sid]
        ships.append(dict(ship_id=sid,name=row['name'],ship_type=profile.ship_type,grade=profile.grade_id,
            capacity=row['capacity'],normal_speed=profile.normal_speed,max_warp_speed=profile.max_warp_speed,
            insurance_premium=profile.insurance_premium))
    options={}
    if not p.destination_id and not world.phase3_state.get('exploration',{}).get('players',{}).get(pid,{}).get('space'):
        for route in engine.get_routes(world,pid):
            if route['is_open'] and route['route_id'] in visibility.route_ids:
                plan=catalog.navigation_plans.get((p.ship_id,route['route_id']),{})
                options[route['destination_id']]=[{k:v[k] for k in ('level','speed')} for v in plan.get('warp_options',[])]
    voyage=connection.execute('SELECT * FROM voyages WHERE player_id=? AND season_id=? ORDER BY sequence DESC LIMIT 1',(pid,world.season_id)).fetchone()
    trip=dict(voyage) if voyage and p.destination_id else {}
    cfg=catalog.phase3 or {}
    extra={}
    if catalog.exploration is not None:
        from .exploration import info
        extra['exploration']=info(engine,world,pid)
        coordinate_trip=world.phase3_state.get('exploration',{}).get('players',{}).get(pid,{}).get('trip')
        if coordinate_trip:trip=coordinate_trip
    return {**extra,'bbs':connection.execute('SELECT name FROM p5_sites WHERE bbs_id=?',(bbs_id,)).fetchone()[0],
            'insured':bool(ps.get('insured',False)),'ships':ships,'warp_options':options,
            'flight':{k:trip[k] for k in ('mode','level','warp_speed') if k in trip},
            'restart':{k:cfg[k] for k in ('restart_ship','restart_cash') if k in cfg}}
