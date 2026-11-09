"""Authenticated owner-only presentation of the existing immutable trade ledger."""
from .model import GameError,integer

def history(repository,world,pid,args):
    if not isinstance(args,dict) or set(args)!={'before','limit'}:raise GameError('INVALID_REQUEST')
    before=args['before'];limit=integer(args['limit'],1,100)
    if before is not None:integer(before,1)
    rows=repository.connection.execute(
        'SELECT sequence,game_time,planet_id,goods_id,side,quantity,first_unit_price,last_unit_price,total FROM trade_ledger WHERE season_id=? AND player_id=? AND (? IS NULL OR sequence<?) ORDER BY sequence DESC LIMIT ?',
        (world.season_id,pid,before,before,limit+1)).fetchall()
    visible=[]
    for row in rows[:limit]:
        item=dict(row);planet=item['planet_id'];name=repository.catalog.planets[planet]['name']
        if planet=='hidden-001':name=world.phase3_state.get('exploration',{}).get('players',{}).get(pid,{}).get('name') or 'Unnamed'
        item.update(planet_name=name);visible.append(item)
    return {'entries':visible,'next_before':visible[-1]['sequence'] if len(rows)>limit else None}
