"""Game rules only: no IO, SQL, HTML, CLI parsing or wall clock access."""
from . import economy, development, production, events, buyback
import hashlib
import json
from .catalog import Catalog, display_name, identifier
from .model import GameError, Player, World, integer


class Engine:
    def __init__(self, catalog: Catalog, random_below=None):
        import secrets
        self.catalog = catalog
        self.random_below=random_below or secrets.randbelow

    def update(self, world: World, now: int, partial=False):
        if self.catalog.phase3 is not None:
            from . import mechanics as m
            cfg=self.catalog.phase3;s=m.state(world);target=events.time_limit(self.catalog,world,max(world.game_time,integer(now)),partial)
            last=(target-s['anchor'])//cfg['event_interval']
            if last-s['slot']>cfg['max_catchup_slots']:
                if not partial:raise GameError('EVENT_CATCHUP_REQUIRED')
                last=s['slot']+cfg['max_catchup_slots'];target=s['anchor']+last*cfg['event_interval']
            ticks=[(s['anchor']+slot*cfg['event_interval'],0,slot) for slot in range(s['slot']+1,last+1)]
            if 'world_events' in cfg:
                interval=cfg['world_events']['interval_seconds']
                previous=s.setdefault('world_slot',world.game_time//interval)
                due=target//interval
                if due-previous>cfg['max_catchup_slots']:
                    if not partial:raise GameError('EVENT_CATCHUP_REQUIRED')
                    due=previous+cfg['max_catchup_slots'];target=due*interval
                ticks=[t for t in ticks if t[0]<=target]
                ticks.extend((slot*interval,1,slot) for slot in range(previous+1,due+1))
            for when,kind,slot in sorted(ticks):
                self._update_base(world,when,partial)
                if kind:m.world_tick(self,world,slot)
                else:m.event_tick(self,world,slot)
            return self._update_base(world,target,partial)
        return self._update_base(world,now,partial)

    def _update_base(self, world: World, now: int, partial=False):
        world.game_time = events.time_limit(self.catalog,world,max(world.game_time,integer(now)),partial)
        buyback.update(self.catalog, world)
        economy.update(self.catalog, world)
        events.update(self.catalog,world)
        if self.catalog.phase3 is not None:
            from .mechanics import news
            for e in world.pending_events:
                news(world,f"market:{e['slot']}:{e['planet_id']}:{e['goods_id']}",e['kind'],planet_id=e['planet_id'],goods_id=e['goods_id'],delta=e['delta'],occurred_at=e['starts_at'])
        from .exploration import settle
        settle(self,world)
        for player in world.players.values():
            if player.arrival_at is not None and player.arrival_at <= world.game_time:
                world.exploration_events.append((player.id,player.destination_id,player.arrival_at,'arrival'))
                player.planet_id = player.destination_id
                player.destination_id = None
                arrival_at=player.arrival_at
                player.arrival_at = None
                if self.catalog.phase3 is not None:
                    from .mechanics import player_state
                    player_state(world,player.id)['mining_since']=arrival_at
        return {"game_time": world.game_time}

    def player(self, world, player_id):
        identifier(player_id)
        if player_id not in world.players:
            raise GameError("PLAYER_NOT_FOUND")
        return world.players[player_id]

    def docked(self, world, player_id):
        player = self.player(world, player_id)
        if player.destination_id is not None:
            raise GameError("IN_TRANSIT")
        from .exploration import player_state,discovered,HIDDEN
        if self.catalog.exploration is not None:
            s=player_state(world,player_id)
            if s['space']:raise GameError('NOT_AT_PLANET')
            if player.planet_id==HIDDEN and not discovered(world,player_id):raise GameError('DISCLOSURE_DENIED')
        return player

    def create_player(self, world, player_id, handle):
        identifier(player_id)
        display_name(handle)
        if player_id in world.players:
            raise GameError("PLAYER_EXISTS")
        start = self.catalog.data["starting"]
        planet=start['planet_id']
        if self.catalog.data.get('universe',{}).get('format_version')==3:
            import secrets
            planet=secrets.choice(sorted(p for p in self.catalog.planets if p!='hidden-001'))
            world.phase3_state.setdefault('initial_planets',{})[player_id]=planet
        world.players[player_id] = Player(player_id, handle, start["cash"],
                                           start["ship_id"], planet)
        if self.catalog.phase3 is not None:
            from .mechanics import player_state
            player_state(world,player_id)
        return self.get_player(world, player_id)

    def used_capacity(self, player):
        return sum(self.catalog.goods[g]["volume"] * q for g, q in player.cargo.items())

    def get_player(self, world, player_id):
        p = self.player(world, player_id)
        ship = self.catalog.ships[p.ship_id]
        result={"player_id": p.id, "handle": p.handle, "season_id": world.season_id,
                "cash": p.cash, "ship_id": p.ship_id, "ship_name": ship["name"],
                "capacity": ship["capacity"], "used_capacity": self.used_capacity(p),
                "planet_id": p.planet_id, "planet_name": self.catalog.planets[p.planet_id]["name"],
                "destination_id": p.destination_id, "arrival_at": p.arrival_at,
                "remaining_seconds": max(0, p.arrival_at - world.game_time) if p.arrival_at else 0,
                "cargo": [{"goods_id": g, "name": self.catalog.goods[g]["name"], "quantity": q}
                          for g, q in sorted(p.cargo.items())]}
        if self.catalog.exploration is not None:
            from .exploration import player_state,HIDDEN
            s=player_state(world,player_id)
            if s['trip']:result['destination_id']='coordinates'
            if s['space']:result.update(planet_id=None,planet_name='Space')
            elif p.planet_id==HIDDEN:result['planet_name']=s['name'] or 'Undiscovered'
        return result

    def get_ship(self, world, player_id):
        p = self.docked(world, player_id) if self.catalog.phase3 is not None else self.player(world, player_id)
        ship = self.catalog.ships[p.ship_id]
        profile = self.catalog.ship_profiles[p.ship_id]
        result = profile.dto()
        grade = self.catalog.ship_grades.get(profile.grade_id)
        result.update(name=ship['name'], capacity=ship['capacity'], max_distance=ship['max_distance'],
                      legacy_speed=ship['speed'], grade_rank=grade.rank if grade else None)
        return result

    def events_sync(self, world, player_id):
        self.player(world,player_id)
        return {'game_time':world.game_time,'processed_slot':world.event_slot}

    def get_events(self, world, player_id):
        p=self.docked(world,player_id)
        return [dict(r) for r in world.active_events if r['planet_id']==p.planet_id]

    def get_region(self, world, player_id):
        player=self.docked(world,player_id)
        return {'planet_id':player.planet_id,'enabled':bool(self.catalog.regional_anchors),
                'entries':[dict(self.catalog.regional_anchors[player.planet_id,g]) for g in self.catalog.goods]
                if self.catalog.regional_anchors else []}

    def get_production(self, world, player_id):
        player=self.docked(world,player_id)
        return production.public_view(self.catalog,world,player.planet_id)

    def get_development(self, world, player_id):
        player=self.docked(world,player_id)
        return development.public_view(self.catalog,world,player.planet_id)

    def invest(self, world, player_id, industry, paid_credits):
        player=self.docked(world,player_id)
        return development.invest(self.catalog,world,player,industry,paid_credits)

    def get_market(self, world, player_id, planet_id=None):
        p = self.docked(world, player_id)
        if planet_id is not None and planet_id != p.planet_id:
            raise GameError("REMOTE_MARKET_UNAVAILABLE")
        entries=[]
        free=self.catalog.ships[p.ship_id]['capacity']-self.used_capacity(p)
        for g,good in self.catalog.goods.items():
            market=world.markets[p.planet_id,g]
            row=economy.parameters(self.catalog,p.planet_id,g,market)
            base=economy.base_price(self.catalog,market,p.planet_id,g)
            bid=economy.price_at(base,market.stock,row) if row else market.price
            ask=economy.price_at(base,max(0,market.stock-1),row) if row else market.price
            quota=buyback.available(self.catalog,world,p.planet_id,g)
            if quota is None:
                from .model import MAX_VALUE
                quota=max(0,(row['stock_limit'] if row else MAX_VALUE)-market.stock)
            low,high=0,min(market.stock,free//good['volume'])
            while low<high:
                mid=(low+high+1)//2
                try:affordable=economy.quote(self.catalog,market,p.planet_id,g,mid,True)['total']<=p.cash
                except GameError:affordable=False
                if affordable:low=mid
                else:high=mid-1
            owned=p.cargo.get(g,0)
            entries.append({'goods_id':g,'name':good['name'],'volume':good['volume'],
                'price':ask,'buy_price':ask,'sell_price':bid,'stock':market.stock,
                'buyback_available':quota,'owned':owned,'free_capacity':free,
                'max_buy':low,'max_sell':min(owned,quota)})
        return {'planet_id':p.planet_id,'pricing_mode':self.catalog.economy['mode'],'entries':entries}

    def _trade(self, world, player_id, goods_id, quantity, buying):
        integer(quantity, 1)
        identifier(goods_id)
        p = self.docked(world, player_id)
        if goods_id not in self.catalog.goods:
            raise GameError("GOODS_NOT_FOUND")
        m = world.markets[p.planet_id, goods_id]
        receipt = economy.quote(self.catalog,m,p.planet_id,goods_id,quantity,buying,
                                buyback.available(self.catalog,world,p.planet_id,goods_id))
        total = receipt["total"]
        owned = p.cargo.get(goods_id, 0)
        if buying:
            if p.cash < total:
                raise GameError("INSUFFICIENT_FUNDS")
            if self.used_capacity(p) + self.catalog.goods[goods_id]["volume"] * quantity > self.catalog.ships[p.ship_id]["capacity"]:
                raise GameError("INSUFFICIENT_CAPACITY")
            if m.stock < quantity:
                raise GameError("INSUFFICIENT_STOCK")
            integer(owned + quantity)
            p.cash -= total
            p.cargo[goods_id] = owned + quantity
            m.stock -= quantity
        else:
            if owned < quantity:
                raise GameError("INSUFFICIENT_CARGO")
            integer(p.cash + total)
            integer(m.stock + quantity)
            p.cash += total
            buyback.consume(self.catalog,world,p.planet_id,goods_id,quantity)
            m.stock = receipt["stock_after"]
            if owned == quantity:
                p.cargo.pop(goods_id)
            else:
                p.cargo[goods_id] = owned - quantity
        if self.catalog.economy['mode']=='fixed':
            return {k:receipt[k] for k in ('side','goods_id','quantity','unit_price','total')}
        return receipt

    def quote_trade(self, world, player_id, goods_id, quantity, side):
        if side not in ('buy','sell'):raise GameError('INVALID_TRADE_SIDE')
        identifier(goods_id)
        p=self.docked(world,player_id)
        if goods_id not in self.catalog.goods:raise GameError('GOODS_NOT_FOUND')
        return economy.quote(self.catalog,world.markets[p.planet_id,goods_id],p.planet_id,goods_id,quantity,side=='buy',
                             buyback.available(self.catalog,world,p.planet_id,goods_id))

    def buy_goods(self, world, player_id, goods_id, quantity):
        return self._trade(world, player_id, goods_id, quantity, True)

    def sell_goods(self, world, player_id, goods_id, quantity):
        return self._trade(world, player_id, goods_id, quantity, False)

    def get_routes(self, world, player_id):
        p = self.docked(world, player_id)
        speed = self.catalog.ships[p.ship_id]["speed"]
        result = []
        for route_id, r in world.routes.items():
            if p.planet_id in (r["from"], r["to"]):
                destination = r["to"] if p.planet_id == r["from"] else r["from"]
                result.append({"route_id": route_id, "destination_id": destination,
                               "name": self.catalog.planets[destination]["name"],
                               "distance": r["distance"], "fee": 0,
                               "seconds": self.catalog.navigation_plans.get((p.ship_id,route_id), {}).get("normal_seconds", max(1, (r["seconds"] + speed - 1) // speed)),
                               "is_open": r["is_open"]})
                if self.catalog.phase3 is not None:
                    from .mechanics import route_progress
                    result[-1].update(origin_id=p.planet_id,origin_name=self.catalog.planets[p.planet_id]['name'],**route_progress(self,world,player_id,route_id))
        return result

    def quote_navigation(self, world, player_id, destination_id, mode='normal', level=None):
        identifier(destination_id)
        if mode not in ('normal','warp') or (mode=='normal' and level is not None):
            raise GameError('INVALID_NAVIGATION')
        if mode=='warp':
            identifier(level)
        p=self.docked(world,player_id)
        if destination_id not in self.catalog.planets:
            raise GameError('PLANET_NOT_FOUND')
        route=next((r for r in self.get_routes(world,player_id) if r['destination_id']==destination_id),None)
        if route is None:raise GameError('NO_ROUTE')
        if not route['is_open']:raise GameError('ROUTE_CLOSED')
        if route['distance']>self.catalog.ships[p.ship_id]['max_distance']:
            raise GameError('OUT_OF_RANGE')
        seconds,cost,speed=route['seconds'],0,None
        if mode=='warp':
            plan=self.catalog.navigation_plans.get((p.ship_id,route['route_id']))
            if not plan:raise GameError('WARP_NOT_CONFIGURED')
            option=next((o for o in plan['warp_options'] if o['level']==level),None)
            if option is None:raise GameError('WARP_LEVEL_UNAVAILABLE')
            seconds,cost,speed=option['seconds'],option['fuel_cost'],option['speed']
        quote=dict(season_id=world.season_id,player_id=player_id,ship_id=p.ship_id,origin_id=p.planet_id,
                   destination_id=destination_id,route_id=route['route_id'],mode=mode,level=level,
                   seconds=seconds,fuel_cost=cost,warp_speed=speed,policy_status=self.catalog.navigation_status)
        from .rules import fingerprint
        binding=json.dumps(fingerprint(self.catalog),sort_keys=True) if self.catalog.exploration is not None else self.catalog.canonical()
        quote['quote_id']=hashlib.sha256((binding+json.dumps(quote,sort_keys=True)).encode()).hexdigest()
        quote.update(distance=route['distance'],estimated_arrival_at=integer(world.game_time+seconds))
        return quote

    def navigate(self, world, player_id, destination_id, mode='normal', level=None, quote_id=None):
        quote=self.quote_navigation(world,player_id,destination_id,mode,level)
        if mode=='warp' and quote_id is None:raise GameError('QUOTE_REQUIRED')
        if quote_id is not None and quote_id!=quote['quote_id']:raise GameError('QUOTE_CHANGED')
        p=self.player(world,player_id)
        if p.cash<quote['fuel_cost']:raise GameError('INSUFFICIENT_FUNDS')
        arrival=integer(world.game_time+quote['seconds'])
        if self.catalog.phase3 is not None:
            from .mechanics import player_state
            player_state(world,player_id)['voyage']={'departure_at':world.game_time,'origin_id':p.planet_id}
        p.cash-=quote['fuel_cost'];p.destination_id=destination_id;p.arrival_at=arrival
        return {**quote,'arrival_at':arrival,'fee':quote['fuel_cost']}

    def depart(self, world, player_id, destination_id):
        # Keep the established API and receipt shape; new normal trips are free.
        result=self.navigate(world,player_id,destination_id)
        return {k:result[k] for k in ('destination_id','arrival_at','fee')}

    def dock(self, world, player_id):
        p=self.docked(world,player_id)
        return {'planet_id':p.planet_id,'fee':0}

    def shipyard(self,world,pid):
        from .mechanics import shipyard
        return shipyard(self,world,pid)

    def buy_ship(self,world,pid,sid):
        from .mechanics import buy_ship
        return buy_ship(self,world,pid,sid)

    def donate(self,world,pid,rid,paid):
        from .mechanics import donate
        return donate(self,world,pid,rid,paid)

    def insure(self,world,pid):
        from .mechanics import insure
        return insure(self,world,pid)

    def bankrupt(self,world,pid):
        from .mechanics import restart
        return restart(self,world,pid)

    def flight(self,world,pid):
        from .mechanics import flight
        return flight(self,world,pid)

    def news(self,world,pid):
        from .mechanics import news_view
        return news_view(self,world,pid)

    def buy_device(self,world,pid):
        from .exploration import buy_device
        return buy_device(self,world,pid)

    def coordinate_quote(self,world,pid, x, y, mode, level):
        from .exploration import quote
        return quote(self,world,pid, x, y, mode, level)

    def coordinate_depart(self,world,pid, x, y, mode, level, quote_id):
        from .exploration import depart
        return depart(self,world,pid, x, y, mode, level, quote_id)

    def explorer_info(self,world,pid):
        from .exploration import info
        return info(self,world,pid)

    def nearby(self,world,pid):
        from .exploration import nearby
        return nearby(self,world,pid)

    def guild(self,world,pid):
        from .exploration import guild
        return guild(self,world,pid)

    def notebook(self,world,pid):
        from .exploration import notebook
        return notebook(self,world,pid)

    def name_star(self,world,pid, value):
        from .exploration import name
        return name(self,world,pid, value)

    def discoverers(self,world,pid):
        from .exploration import arrivals
        return arrivals(self,world,pid)
