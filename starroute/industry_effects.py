"""Provisional industry effects; fixed definitions and persisted period snapshots."""
from .model import integer
from .development import INDUSTRIES


def policy(catalog):
    raw = catalog.data.get('industry_effects')
    if raw is None or raw == {'mode': 'disabled'}:
        return {'mode': 'disabled'}
    if (not isinstance(raw, dict) or set(raw) != {'mode', 'status', 'planets'}
            or raw['mode'] != 'next_period_v1' or raw['status'] != 'provisional'
            or catalog.production['mode'] == 'disabled'
            or catalog.development['mode'] == 'disabled'):
        raise ValueError('industry effects policy')
    if not isinstance(raw['planets'], list):
        raise ValueError('industry effects planets')
    rows = []; seen = set()
    for row in raw['planets']:
        if not isinstance(row, dict) or set(row) != {'planet_id', 'production_bps_per_unit', 'market_bps_per_unit'}:
            raise ValueError('industry effects fields')
        pid = row['planet_id']
        if pid not in catalog.planets or pid in seen:
            raise ValueError('industry effects reference')
        seen.add(pid)
        rates = row['production_bps_per_unit']
        if not isinstance(rates, dict) or set(rates) != set(INDUSTRIES):
            raise ValueError('industry effects industries')
        for value in (*rates.values(), row['market_bps_per_unit']):
            integer(value, 0, 10000)
        # Validate the largest reachable result without publishing hidden limits.
        caps = catalog.development_planets[pid]['private_caps']
        for key, market in catalog.economy_markets.items():
            if key[0] != pid: continue
            integer(scaled(market['stock_limit'], caps['tertiary'], row['market_bps_per_unit']), 1)
            source = catalog.production_sources.get(key)
            if source:
                ind = source['industry']
                amount = scaled(source['units_per_tick'], caps[ind], rates[ind])
                integer(amount + catalog.production_imports.get(key, 0))
        rows.append({'planet_id': pid, 'production_bps_per_unit': dict(rates),
                     'market_bps_per_unit': row['market_bps_per_unit']})
    if seen != set(catalog.planets):
        raise ValueError('industry effects coverage')
    return {'mode': raw['mode'], 'status': raw['status'], 'planets': sorted(rows, key=lambda r: r['planet_id'])}


def scaled(base, progress, bps):
    return base + base * progress * bps // 10000


def values(catalog, progress, key):
    """Domestic output and capacity; imports and demand are deliberately unchanged."""
    row = catalog.industry_effect_planets[key[0]]
    source = catalog.production_sources.get(key)
    output = 0
    if source:
        ind = source['industry']
        output = scaled(source['units_per_tick'], progress[key[0], ind], row['production_bps_per_unit'][ind])
    capacity = scaled(catalog.economy_markets[key]['stock_limit'], progress[key[0], 'tertiary'], row['market_bps_per_unit'])
    return output, capacity
