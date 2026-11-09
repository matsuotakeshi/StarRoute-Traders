"""Opt-in shared market purchasing budgets, independent of resale inventory."""
from .model import integer, GameError


def policy(data):
    raw = data.get('market_buyback')
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != {'mode','status','capacity','initial','recovery_units','interval_seconds'}:
        raise ValueError('buyback fields')
    if raw['mode'] != 'recovering_v1' or raw['status'] != 'provisional':
        raise ValueError('buyback mode')
    integer(raw['capacity'], 1)
    integer(raw['initial'], 0, raw['capacity'])
    integer(raw['recovery_units'], 1)
    integer(raw['interval_seconds'], 1)
    return dict(raw)


def update(catalog, world):
    cfg = catalog.market_buyback
    if cfg is None:
        return
    anchor = world.economy_time if world.economy_time is not None else world.game_time
    state = world.phase3_state.setdefault('market_buyback', {'time':anchor, 'remaining':{}})
    integer(state['time'])
    ticks = max(0, (world.game_time-state['time']) // cfg['interval_seconds'])
    for planet, good in world.markets:
        key = planet+'/'+good
        old = state['remaining'].setdefault(key, cfg['initial'])
        integer(old, 0, cfg['capacity'])
        state['remaining'][key] = min(cfg['capacity'], old+ticks*cfg['recovery_units'])
    state['time'] += ticks*cfg['interval_seconds']


def available(catalog, world, planet, good):
    if catalog.market_buyback is None:
        return None
    update(catalog, world)
    return world.phase3_state['market_buyback']['remaining'][planet+'/'+good]


def consume(catalog, world, planet, good, quantity):
    if catalog.market_buyback is None:
        return
    if quantity > available(catalog, world, planet, good):
        raise GameError('INSUFFICIENT_BUYBACK')
    world.phase3_state['market_buyback']['remaining'][planet+'/'+good] -= quantity
