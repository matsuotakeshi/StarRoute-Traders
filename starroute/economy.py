"""Opt-in provisional stock curve and deterministic supply/demand ticks."""
from .model import integer, GameError
from .regional import base_price


def policy(data):
    raw=data.get('economy')
    if raw is None or raw=={'mode':'fixed'}: return {'mode':'fixed'}
    if not isinstance(raw,dict) or set(raw)!={'mode','status','tick_seconds','markets'} or raw['mode'] not in ('stock_curve_v1','planet_supply_v1') or raw['status']!='provisional':
        raise ValueError('economy policy')
    integer(raw['tick_seconds'],1)
    expected={(r['planet_id'],r['goods_id']):r for r in data['markets']}
    seen=set()
    if not isinstance(raw['markets'],list):raise ValueError('markets')
    for row in raw['markets']:
        fields={'planet_id','goods_id','target_stock','step_price','min_price','max_price','stock_limit','demand_per_tick'}
        if raw['mode']=='stock_curve_v1':fields.add('supply_per_tick')
        if set(row)!=fields:raise ValueError('market fields')
        key=(row['planet_id'],row['goods_id'])
        if key not in expected or key in seen:raise ValueError('market reference')
        seen.add(key)
        for k in ('target_stock','demand_per_tick'):integer(row[k])
        if raw['mode']=='stock_curve_v1':integer(row['supply_per_tick'])
        for k in ('step_price','min_price','max_price','stock_limit'):integer(row[k],1)
        if row['min_price']>row['max_price'] or max(row['target_stock'],expected[key]['stock'])>row['stock_limit']:raise ValueError('bounds')
    if seen!=set(expected):raise ValueError('coverage')
    return {'mode':raw['mode'],'status':raw['status'],'tick_seconds':raw['tick_seconds'],
            'markets':sorted([dict(r) for r in raw['markets']],key=lambda r:(r['planet_id'],r['goods_id']))}


def parameters(catalog, planet, good, market=None):
    row = catalog.economy_markets.get((planet,good))
    if row and market is not None and market.capacity is not None:
        return {**row, 'stock_limit': market.capacity}
    return row


def price_at(base,stock,row):
    return max(row['min_price'],min(row['max_price'],base+row['step_price']*(row['target_stock']-stock)))


def price_sum(base,lo,count,row):
    # Sum clamped arithmetic progression in O(1), even for hostile huge quantities.
    a=base+row['step_price']*row['target_stock'];step=row['step_price']
    def positive(offset):
        n=min(count,max(0,(offset-1)//step-lo+1))
        return n*(offset-step*lo)-step*n*(n-1)//2
    return integer(count*row['min_price']+positive(a-row['min_price'])-positive(a-row['max_price']))


def quote(catalog,market,planet,good,quantity,buying,buyback_remaining=None):
    integer(quantity,1)
    row=parameters(catalog,planet,good,market)
    if buying and quantity>market.stock:raise GameError('INSUFFICIENT_STOCK')
    if not buying:integer(market.stock+quantity)
    if not buying and buyback_remaining is not None and quantity>buyback_remaining:raise GameError('INSUFFICIENT_BUYBACK')
    if row and not buying and buyback_remaining is None and market.stock+quantity>row['stock_limit']:raise GameError('MARKET_FULL')
    if row:
        lo=market.stock-quantity if buying else market.stock
        base=base_price(catalog,market,planet,good)
        total=price_sum(base,lo,quantity,row)
        first=price_at(base,market.stock-1 if buying else market.stock,row)
        last=price_at(base,lo if buying else lo+quantity-1,row)
    else:total=integer(market.price*quantity);first=last=market.price
    after=market.stock-quantity if buying else market.stock+quantity
    if not buying and buyback_remaining is not None and row:
        # Resale shelves remain bounded; excess purchased goods satisfy local demand.
        after=min(after,row['stock_limit'])
    return {'side':'buy' if buying else 'sell','goods_id':good,'quantity':quantity,
            'unit_price':first,'first_unit_price':first,'last_unit_price':last,'total':total,
            'pricing_mode':catalog.economy['mode'],'stock_before':market.stock,
            'stock_after':after}


def update(catalog,world):
    if world.economy_time is None:world.economy_time=world.game_time
    if catalog.economy['mode']=='fixed':return
    tick=catalog.economy['tick_seconds']
    ticks=max(0,(world.game_time-world.economy_time)//tick)
    if not ticks:return
    for key,row in catalog.economy_markets.items():
        market=world.markets[key]
        from .production import supply
        inflow=supply(catalog,key) if catalog.economy['mode']=='planet_supply_v1' else row['supply_per_tick']
        if catalog.industry_effects['mode'] != 'disabled':
            from .industry_effects import values
            # Finish the already-started period with its saved capabilities.
            imports = catalog.production_imports.get(key,0)
            market.stock=max(0,min(market.capacity,market.stock+market.production_rate+imports-row['demand_per_tick']))
            output, capacity = values(catalog,world.developments,key)
            if catalog.phase3 is not None and (output,capacity)!=(market.production_rate,market.capacity):
                from .mechanics import news
                boundary=world.economy_time+tick
                news(world,f'production:{boundary}:{key[0]}:{key[1]}','production',planet_id=key[0],occurred_at=boundary,
                     goods_id=key[1],before=market.production_rate,after=output,capacity=capacity)
            if ticks > 1:
                market.stock=max(0,min(capacity,market.stock+(ticks-1)*(output+imports-row['demand_per_tick'])))
            market.stock=min(market.stock,capacity)
            market.production_rate, market.capacity = output, capacity
        else:
            market.stock=max(0,min(row['stock_limit'],market.stock+ticks*(inflow-row['demand_per_tick'])))
    world.economy_time+=ticks*tick
