"""Shared use cases for CLI, future Door and Web adapters."""
from contextlib import AbstractContextManager
from typing import Protocol
from .clock import Clock
from .catalog import Catalog
from .engine import Engine
from .model import World, GameError
from .catalog import identifier
from dataclasses import asdict
import json
import uuid


class Repository(Protocol):
    catalog: Catalog
    world_id: str
    def check_round(self,world,now): ...
    def records(self,kind,player_id,round_id=None,category=None): ...
    def event_history(self, after=0, limit=50): ...
    def record_investment(self, world, player_id, receipt, request_id): ...
    def investment_ledger(self, player_id, after=0, limit=50): ...
    def record_trade(self, world, player_id, planet_id, receipt, before, request_id): ...
    def trade_ledger(self, player_id, after=0, limit=50): ...
    def account_identity(self, bbs_id, local_user_id): ...
    def record_voyage(self, season_id, player_id, origin, departure, receipt, request_id): ...
    def latest_voyage(self, season_id, player_id): ...
    def find_operation(self, season_id, actor, request_id): ...
    def record_operation(self, season_id, actor, request_id, payload, result, before, after, game_time): ...
    def account_exists(self, bbs_id, local_user_id): ...
    def bind_account(self, bbs_id, local_user_id, player_id): ...

    def resolve_account(self, bbs_id, local_user_id): ...
    def get_language(self, player_id, default="ja"): ...
    def set_language(self, player_id, language): ...

    def transaction(self) -> AbstractContextManager[World]: ...


class Application:
    def records(self,kind,player_id,round_id=None,category=None):
        return self.repository.records(kind,player_id,round_id,category)

    def __init__(self, repository: Repository, clock: Clock, default_language="ja"):
        if default_language not in ("ja","en"):
            raise GameError("INVALID_LANGUAGE")
        self.default_language = default_language
        self.repository = repository
        self.clock = clock
        self.engine = Engine(repository.catalog)

    def configuration_info(self):
        """Trusted local/admin metadata. BBS adapters must use MasterService."""
        from .rules import fingerprint
        result={'world_id': self.repository.world_id, **fingerprint(self.engine.catalog)}
        from .universe import public_info
        universe=public_info(self.engine.catalog)
        if universe is not None:result['universe']=universe
        return result

    def reference_candidate(self):
        from .rules import master_candidate
        return master_candidate(self.repository.world_id, self.engine.catalog)

    def account_identity(self, bbs_id, local_user_id):
        return self.repository.account_identity(bbs_id, local_user_id)

    def _call(self, method, *args, request_id=None, target_guard=None, access_guard=None, server_quote=False, expected_total=None):
        mutation = method in ('create_player','buy_goods','sell_goods','depart','navigate','dock','invest','buy_ship','donate','insure','bankrupt')
        if request_id is not None:
            identifier(request_id)
        if self.engine.catalog.phase3 is not None and 'world_events' in self.engine.catalog.phase3:
            from .maintenance import advance
            def guarded(world):
                if target_guard:target_guard(world)
                if access_guard:access_guard(world)
            advance(self.repository,self.clock.now(),guarded)
        with self.repository.transaction() as world:
            self.repository.check_round(world,self.clock.now())
            if target_guard is not None:target_guard(world)
            actor = args[0] if args else ''
            payload = json.dumps([method, args], sort_keys=True, ensure_ascii=False)
            if expected_total is not None:payload=json.dumps([method,args,expected_total],sort_keys=True,ensure_ascii=False)
            if mutation and request_id is not None:
                row = self.repository.find_operation(world.season_id,actor,request_id)
                if row:
                    if row['payload'] != payload:
                        raise GameError('REQUEST_CONFLICT')
                    return json.loads(row['result'])
            before = asdict(world.players[actor]) if actor in world.players else None
            self.engine.update(world, self.clock.now(),partial=method=="events_sync")
            # Journal the actual operation boundary after time-driven events settle.
            before = asdict(world.players[actor]) if actor in world.players else None
            if before is not None:
                before['_cargo_epoch']=sum(e['kind']=='wreck' and e['target']==actor for e in world.phase3_state.get('events',{}).values())
            if self.engine.catalog.phase3 is not None and actor in world.players and world.players[actor].destination_id is not None:
                if method not in ('get_player','flight','news','events_sync'):raise GameError('IN_TRANSIT')
            if access_guard is not None:access_guard(world)
            if expected_total is not None:
                from .model import integer
                integer(expected_total,0)
                side='buy' if method=='buy_goods' else 'sell'
                if self.engine.quote_trade(world,*args,side)['total']!=expected_total:raise GameError('PRICE_CHANGED')
            origin = world.players[actor].planet_id if actor in world.players else None
            if server_quote:
                if method!='navigate':raise GameError('MASTER_REQUEST_INVALID')
                quote=self.engine.quote_navigation(world,*args)
                result=self.engine.navigate(world,*args,quote_id=quote['quote_id'])
            else:
                result = getattr(self.engine, method)(world, *args)
            if mutation:
                after = asdict(world.players[actor])
                operation_id=request_id or uuid.uuid4().hex
                self.repository.record_operation(world.season_id,actor,operation_id,payload,result,before,after,world.game_time)
                if method=="invest":
                    self.repository.record_investment(world,actor,result,operation_id)
                if method in ("buy_goods","sell_goods"):
                    self.repository.record_trade(world,actor,origin,result,before,operation_id)
                if method in ("depart","navigate"):
                    self.repository.record_voyage(world.season_id,actor,origin,world.game_time,result,operation_id)
            return result

    def create_account(self, bbs_id, local_user_id, handle, *, request_id=None, target_guard=None):
        """Trusted adapter API; bbs_id must come from authenticated server context.

        This API does not authenticate callers and is not exposed as a CLI switch.
        """
        identifier(bbs_id); identifier(local_user_id)
        if request_id is not None:
            identifier(request_id)
        if bbs_id == 'local':
            raise GameError('RESERVED_NAMESPACE')
        with self.repository.transaction() as world:
            self.repository.check_round(world,self.clock.now())
            if target_guard is not None:target_guard(world)
            actor = 'account:' + json.dumps([bbs_id,local_user_id])
            payload = json.dumps(['create_account',bbs_id,local_user_id,handle])
            if request_id is not None:
                prior = self.repository.find_operation(world.season_id,actor,request_id)
                if prior:
                    if prior['payload'] != payload:
                        raise GameError('REQUEST_CONFLICT')
                    return json.loads(prior['result'])
            if self.repository.account_exists(bbs_id,local_user_id):
                raise GameError('PLAYER_EXISTS')
            pid = uuid.uuid4().hex
            while pid in world.players:
                pid = uuid.uuid4().hex
            self.engine.update(world, self.clock.now())
            result = self.engine.create_player(world, pid, handle)
            self.repository.bind_account(bbs_id,local_user_id,pid)
            self.repository.record_operation(world.season_id,actor,request_id or uuid.uuid4().hex,payload,result,None,asdict(world.players[pid]),world.game_time)
            return result

    def resolve_account(self, bbs_id, local_user_id):
        return self.repository.resolve_account(bbs_id, local_user_id)

    def get_language(self, player_id):
        return self.repository.get_language(player_id, self.default_language)

    def set_language(self, player_id, language):
        self.repository.set_language(player_id, language)

    def create_player(self, player_id: str, handle: str, *, request_id=None) -> dict:
        return self._call("create_player", player_id, handle, request_id=request_id)

    def get_player(self, player_id: str) -> dict:
        return self._call("get_player", player_id)

    def get_ship(self, player_id: str) -> dict:
        return self._call("get_ship", player_id)

    def get_events(self, player_id):return self._call('get_events',player_id)

    def events_sync(self, player_id):
        result=self._call('events_sync',player_id)
        result['pending']=result['game_time']<self.clock.now()
        return result

    def event_history(self, player_id, after=0, limit=50):
        self._call('get_player',player_id)
        return self.repository.event_history(after,limit)

    def get_region(self, player_id):
        return self._call('get_region',player_id)

    def get_production(self, player_id):
        return self._call('get_production',player_id)

    def get_development(self, player_id):
        return self._call('get_development',player_id)

    def invest(self, player_id, industry, paid_credits, *, request_id=None):
        return self._call('invest',player_id,industry,paid_credits,request_id=request_id)

    def investment_ledger(self, player_id, after=0, limit=50):
        return self.repository.investment_ledger(player_id,after,limit)

    def get_market(self, player_id: str, planet_id: str | None = None) -> dict:
        return self._call("get_market", player_id, planet_id)

    def quote_trade(self, player_id, goods_id, quantity, side):
        return self._call('quote_trade',player_id,goods_id,quantity,side)

    def trade_ledger(self, player_id, after=0, limit=50):
        return self.repository.trade_ledger(player_id,after,limit)

    def buy_goods(self, player_id: str, goods_id: str, quantity: int, *, request_id=None) -> dict:
        return self._call("buy_goods", player_id, goods_id, quantity, request_id=request_id)

    def sell_goods(self, player_id: str, goods_id: str, quantity: int, *, request_id=None) -> dict:
        return self._call("sell_goods", player_id, goods_id, quantity, request_id=request_id)

    def get_routes(self, player_id: str) -> list:
        return self._call("get_routes", player_id)

    def depart(self, player_id: str, destination_id: str, *, request_id=None) -> dict:
        return self._call("depart", player_id, destination_id, request_id=request_id)

    def quote_navigation(self, player_id, destination_id, mode='normal', level=None):
        return self._call('quote_navigation',player_id,destination_id,mode,level)

    def navigate(self, player_id, destination_id, mode='normal', level=None, quote_id=None, *, request_id=None):
        return self._call('navigate',player_id,destination_id,mode,level,quote_id,request_id=request_id)

    def dock(self, player_id, *, request_id=None):
        return self._call('dock',player_id,request_id=request_id)

    def latest_voyage(self, player_id):
        with self.repository.transaction() as world:
            self.repository.check_round(world,self.clock.now())
            self.engine.update(world,self.clock.now())
            self.engine.player(world,player_id)
            receipt=self.repository.latest_voyage(world.season_id,player_id)
            if receipt:
                receipt['arrived']=receipt['arrival_at']<=world.game_time
            return receipt

    def update(self) -> dict:
        with self.repository.transaction() as world:
            self.repository.check_round(world,self.clock.now())
            return self.engine.update(world, self.clock.now())
