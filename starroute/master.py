"""Server-local Phase 3 boundary, NOT an API transport or authentication system.

Only trusted master code constructs ServerContext after resolving identity and
disclosure permissions. Never deserialize a BBS body directly into that context.
The CLI/Application remain trusted local tools and must not be shipped as a
BBS-side shared-world engine. Phase 5 owns TLS, authentication and admission.
"""
from dataclasses import dataclass,field
import hashlib
import json
from .catalog import identifier
from .model import GameError,integer
from .rules import canonical_bytes,fingerprint

PROJECTION_VERSION=1


@dataclass(frozen=True)
class WorldTarget:
    universe_id: str
    round_id: int

    def __post_init__(self):
        identifier(self.universe_id);integer(self.round_id,1)


@dataclass(frozen=True)
class Visibility:
    planet_ids: frozenset[str]=field(default_factory=frozenset)
    coordinate_ids: frozenset[str]=field(default_factory=frozenset)
    route_ids: frozenset[str]=field(default_factory=frozenset)

    def __post_init__(self):
        for name in ('planet_ids','coordinate_ids','route_ids'):
            object.__setattr__(self,name,frozenset(getattr(self,name)))
            for value in getattr(self,name):identifier(value)
        if not self.coordinate_ids<=self.planet_ids:raise ValueError('coordinates require visible planets')


@dataclass(frozen=True)
class ServerContext:
    target: WorldTarget
    bbs_id: str
    user_id: str
    visibility: Visibility=field(default_factory=Visibility)

    def __post_init__(self):
        identifier(self.bbs_id);identifier(self.user_id)
        if self.bbs_id=='local':raise GameError('RESERVED_NAMESPACE')
        if not isinstance(self.target,WorldTarget) or not isinstance(self.visibility,Visibility):
            raise ValueError('server context')


def target_for(repository,world):
    raw=repository.catalog.data.get('universe')
    return WorldTarget(raw['universe_id'] if raw else repository.world_id,world.season_id)


def check_target(repository,world,target):
    if target_for(repository,world)!=target:raise GameError('WORLD_TARGET_MISMATCH')


def public_definition(catalog,target,visibility):
    """Only explicitly disclosed fixed facts, never the private catalog/manifest."""
    coordinates={r['planet_id']:{k:r[k] for k in ('x','y')} for r in catalog.data.get('universe',{}).get('coordinates',[])}
    planets=[]
    for pid in sorted(visibility.planet_ids & catalog.planets.keys()):
        row={'planet_id':pid,'name':catalog.planets[pid]['name']}
        if pid in visibility.coordinate_ids and pid in coordinates:row['coordinates']=coordinates[pid]
        planets.append(row)
    routes=[]
    for row in sorted(catalog.data['routes'],key=lambda r:r['id']):
        if row['id'] in visibility.route_ids and {row['from'],row['to']}<=visibility.planet_ids:
            routes.append({k:row[k] for k in ('id','from','to','distance')})
    result={'projection_version':PROJECTION_VERSION,'universe_id':target.universe_id,
            'round_id':target.round_id,'planets':planets,'routes':routes}
    return {'definition':result,'public_definition_hash':hashlib.sha256(canonical_bytes(result)).hexdigest()}


PLAYER_FIELDS=('player_id','handle','season_id','cash','ship_id','ship_name','capacity','used_capacity',
               'planet_id','planet_name','destination_id','arrival_at','remaining_seconds')
TRADE_FIELDS=('side','goods_id','quantity','unit_price','first_unit_price','last_unit_price','total','pricing_mode','stock_before','stock_after')
NAV_FIELDS=('season_id','player_id','ship_id','origin_id','destination_id','mode','level','seconds','fuel_cost','warp_speed','policy_status','arrival_at','fee')
OPERATIONS={
    'register':('create_account',('handle',)),
    'status':('get_player',()),
    'market':('get_market',()),
    'production':('get_production',()),
    'development':('get_development',()),
    'routes':('get_routes',()),
    'quote_trade':('quote_trade',('goods_id','quantity','side')),
    'buy':('buy_goods',('goods_id','quantity')),
    'sell':('sell_goods',('goods_id','quantity')),
    'invest':('invest',('industry','paid_credits')),
    'quote_navigation':('quote_navigation',('destination_id','mode','level')),
    'navigate':('navigate',('destination_id','mode','level')),
    'dock':('dock',()),
    'shipyard':('shipyard',()),
    'buy_ship':('buy_ship',('ship_id',)),
    'donate':('donate',('route_id','paid_credits')),
    'insure':('insure',()),
    'bankrupt':('bankrupt',()),
    'flight':('flight',()),
    'news':('news',()),
}
MUTATIONS=frozenset(('register','buy','sell','invest','navigate','dock','buy_ship','donate','insure','bankrupt'))


def pick(value,fields):return {k:value[k] for k in fields if k in value}


def response(operation,value,visibility):
    # Explicit projections prevent a future internal field from silently becoming public.
    if operation=='shipyard':return [pick(r,('ship_id','price','capacity','available')) for r in value]
    if operation=='buy_ship':return pick(value,('ship_id','old_ship_id','paid_credits'))
    if operation=='donate':return pick(value,('route_id','paid_credits','effect_units','opened','jackpot'))
    if operation=='insure':return pick(value,('ship_id','paid_credits','insured'))
    if operation=='bankrupt':return pick(value,('ship_id','cash','planet_id','insured_rescue'))
    if operation=='flight':return pick(value,('origin_id','destination_id','departure_at','arrival_at','remaining_seconds','position'))
    if operation=='news':
        rows=[]
        for row in value:
            if row['planet_id'] is not None and row['planet_id'] not in visibility.planet_ids:continue
            values=row['values']
            if 'route_id' in values and values['route_id'] not in visibility.route_ids:continue
            if 'planet_id' in values and values['planet_id'] not in visibility.planet_ids:continue
            item=pick(row,('event_id','kind','game_time','planet_id'))
            item['values']=pick(values,('goods_id','delta','before','after','capacity','quantity','loss','arrival_at','route_id','reward','ship_id','cash','planet_id','insured_rescue'))
            if 'changes' in values:item['values']['changes']=[pick(c,('industry','before','after')) for c in values['changes']]
            rows.append(item)
        return rows
    if operation in ('register','status'):
        result=pick(value,PLAYER_FIELDS)
        result['cargo']=[pick(r,('goods_id','name','quantity')) for r in value['cargo']]
        return result
    if operation in ('buy','sell','quote_trade'):return pick(value,TRADE_FIELDS)
    if operation in ('navigate','quote_navigation'):return pick(value,NAV_FIELDS)
    if operation=='dock':return pick(value,('planet_id','fee'))
    if operation=='invest':
        result=pick(value,('planet_id','industry','paid_credits','effect_units','progress','level'))
        if 'level' in result:result.pop('progress',None)
        return result
    if operation=='routes':
        return [pick(r,('route_id','destination_id','name','distance','fee','seconds','is_open')) for r in value
                if r['route_id'] in visibility.route_ids and r['destination_id'] in visibility.planet_ids]
    if operation=='development':
        return {**pick(value,('planet_id','enabled')),
                'industries':[pick(r,('industry','level') if 'level' in r else ('industry','progress')) for r in value['industries']]}
    if operation in ('market','production'):
        fields=('goods_id','name','volume','price','stock') if operation=='market' else ('goods_id','produces','industry','production_per_tick','imports_per_tick','available','market_capacity')
        return {**pick(value,('planet_id','pricing_mode','enabled','tick_seconds')),
                'entries':[pick(r,fields) for r in value['entries']]}
    raise GameError('MASTER_REQUEST_INVALID')


class MasterService:
    """In-process adapter contract. No network, cache, credentials or admission decisions."""
    def __init__(self,application):self.app=application

    def _context(self,context):
        if not isinstance(context,ServerContext):raise GameError('MASTER_REQUEST_INVALID')

    def _target_guard(self,context):
        return lambda world:check_target(self.app.repository,world,context.target)

    def manifest(self,context):
        self._context(context)
        with self.app.repository.transaction() as world:
            self._target_guard(context)(world)
            # Identity binding is server-side; a client cannot supply another player's ID.
            pid=self.app.resolve_account(context.bbs_id,context.user_id)
            self.app.engine.player(world,pid)
            result=public_definition(self.app.engine.catalog,context.target,context.visibility)
            result['rules']=fingerprint(self.app.engine.catalog)
            raw=self.app.engine.catalog.data.get('universe')
            result['generator_version']=raw['generator_version'] if raw else None
            return result

    def execute(self,context,operation,arguments,*,request_id=None):
        self._context(context)
        if type(operation) is not str or operation not in OPERATIONS or not isinstance(arguments,dict):
            raise GameError('MASTER_REQUEST_INVALID')
        method,fields=OPERATIONS[operation]
        expected_total=None
        if operation in ('buy','sell') and 'expected_total' in arguments:
            arguments=dict(arguments);expected_total=arguments.pop('expected_total');integer(expected_total,0)
        if set(arguments)!=set(fields):raise GameError('MASTER_REQUEST_INVALID')
        for key in ('goods_id','destination_id','ship_id','route_id'):
            if key in arguments:identifier(arguments[key])
        if operation in MUTATIONS:
            if request_id is None:raise GameError('MASTER_REQUEST_INVALID')
            identifier(request_id)
        elif request_id is not None:raise GameError('MASTER_REQUEST_INVALID')
        args=[arguments[k] for k in fields]
        if operation=='register':
            value=self.app.create_account(context.bbs_id,context.user_id,*args,request_id=request_id,target_guard=self._target_guard(context))
        else:
            pid=self.app.resolve_account(context.bbs_id,context.user_id)
            def access(world):
                if operation in ('status','news'):return
                if operation=='flight':
                    player=self.app.engine.player(world,pid)
                    if player.planet_id not in context.visibility.coordinate_ids or (player.destination_id and player.destination_id not in context.visibility.coordinate_ids):raise GameError('DISCLOSURE_DENIED')
                    return
                if operation=='donate' and arguments['route_id'] not in context.visibility.route_ids:raise GameError('DISCLOSURE_DENIED')
                player=self.app.engine.docked(world,pid)
                if player.planet_id not in context.visibility.planet_ids:raise GameError('DISCLOSURE_DENIED')
                if operation in ('navigate','quote_navigation'):
                    dest=arguments['destination_id']
                    if dest not in context.visibility.planet_ids:raise GameError('DISCLOSURE_DENIED')
                    if not any(r['route_id'] in context.visibility.route_ids and r['destination_id']==dest
                               for r in self.app.engine.get_routes(world,pid)):
                        raise GameError('DISCLOSURE_DENIED')
            value=self.app._call(method,pid,*args,request_id=request_id,
                                 target_guard=self._target_guard(context),access_guard=access,server_quote=operation=='navigate',expected_total=expected_total)
        return response(operation,value,context.visibility)

    def result(self,context,operation,request_id):
        """Resolve uncertain completion, without executing or advancing game time."""
        self._context(context);identifier(request_id)
        if type(operation) is not str or operation not in MUTATIONS:raise GameError('MASTER_REQUEST_INVALID')
        with self.app.repository.transaction() as world:
            self._target_guard(context)(world)
            if operation=='register':actor='account:'+json.dumps([context.bbs_id,context.user_id])
            else:actor=self.app.resolve_account(context.bbs_id,context.user_id)
            row=self.app.repository.find_operation(world.season_id,actor,request_id)
            if row is None:return {'status':'unknown'}
            if json.loads(row['payload'])[0]!=OPERATIONS[operation][0]:raise GameError('REQUEST_CONFLICT')
            return {'status':'committed','result':response(operation,json.loads(row['result']),context.visibility)}
