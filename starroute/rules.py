"""Internal effective-rule projection. No trust decisions or network operations."""
import hashlib
import json
from .model import GameError, MAX_VALUE

RULES_VERSION = "phase3-complete-1"
CONFIG_SCHEMA_VERSION = 10
CANONICALIZATION = "srt-integer-json-v1"
SITE_SETTINGS = ("default_language", "language_files", "inter_bbs", "display_names",
                 "terminal_encoding", "display_mode", "bbs_name", "addresses", "log_path")


def canonical_bytes(value):
    # JSON integers only. Floats, including integral floats, are not accepted.
    def check(v):
        if v is None or type(v) in (str, int, bool):
            return
        if type(v) is list:
            for x in v: check(x)
            return
        if type(v) is dict and all(type(k) is str for k in v):
            for x in v.values(): check(x)
            return
        raise GameError("CONFIG_VERIFICATION_FAILED")
    check(value)
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeError):
        raise GameError("CONFIG_VERIFICATION_FAILED") from None


def effective_rules(catalog):
    """Server-only detached projection; never publish this whole object to clients.

    Unknown fields are not silently certified. Legacy games can still open/play,
    but obtaining their fingerprint fails until those fields are classified.
    """
    d=catalog.data
    if 'universe' in d:
        from .universe import rules
        return rules(catalog)
    def fields(row, required, optional=()):
        if not isinstance(row,dict) or set(row)-set(required)-set(optional) or set(required)-set(row):
            raise GameError("CONFIG_VERIFICATION_FAILED")
    fields(d, ('format_version','starting','planets','goods','ships','routes','markets'),
           ('ship_grades','navigation','economy','development','production','regional_prices','market_events','industry_effects','phase3'))
    fields(d['starting'], ('cash','planet_id','ship_id'))
    groups={
        'planets': ('id','name'),
        'goods': ('id','name','base_price','volume','production','volatility_bps'),
        'ships': ('id','name','capacity','max_distance','speed'),
        'routes': ('id','from','to','distance','seconds','fee','is_open'),
        'markets': ('planet_id','goods_id','price','stock'),
    }
    result={'starting':dict(d['starting'])}
    for group, required in groups.items():
        rows=[]
        for row in d[group]:
            fields(row, required, ('profile',) if group=='ships' else ())
            item={k:v for k,v in row.items() if k not in ('name','profile','fee')}
            # Normal travel ignores legacy fees; fixed free rules are explicit below.
            if group=='ships':
                profile=catalog.ship_profiles[row['id']].dto()
                profile.pop('specification_status')
                item['profile']=profile
            rows.append(item)
        result[group]=sorted(rows,key=lambda r:(r['planet_id'],r['goods_id']) if group=='markets' else r['id'])
    for row in d.get('ship_grades',[]): fields(row, ('id','rank'))
    result['ship_grades']=[{'id':g.id,'rank':g.rank} for g in sorted(catalog.ship_grades.values(),key=lambda g:g.id)]
    plans=[]
    for key,row in sorted(catalog.navigation_plans.items()):
        plans.append({**row,'warp_options':sorted(row['warp_options'],key=lambda o:o['level'])})
    result['navigation']=plans
    result['economy']={k:v for k,v in catalog.economy.items() if k!='status'}
    result['development']={k:v for k,v in catalog.development.items() if k!='status'}
    result['industry_effects']={k:v for k,v in catalog.industry_effects.items() if k!='status'}
    result['production']={k:v for k,v in catalog.production.items() if k!='status'}
    result['market_events']={k:v for k,v in catalog.market_events.items() if k!='status'}
    result['regional_prices']={k:v for k,v in catalog.regional_prices.items() if k!='status'}
    if catalog.regional_prices['mode']!='disabled':
        for market in result['markets']:market.pop('price')
    # Only the actual travel times are effective when explicit plans replace legacy speed.
    if plans:
        for row in result['ships']: row.pop('speed')
        for row in result['routes']: row.pop('seconds')
    if catalog.phase3 is not None:result['phase3']={k:v for k,v in catalog.phase3.items() if k!='status'}
    result['fixed_rules']={'normal_fee':0,'docking_fee':0,'integer_limit':MAX_VALUE}
    # Future mechanics must register their parameters here and bump the schema/rule version.
    return json.loads(canonical_bytes(result))


def fingerprint(catalog):
    payload={'rules_version':RULES_VERSION,'config_schema_version':CONFIG_SCHEMA_VERSION,
             'canonicalization':CANONICALIZATION,'game_rules':effective_rules(catalog)}
    return {k:v for k,v in payload.items() if k!='game_rules'} | {
        'algorithm':'sha256','sha256':hashlib.sha256(canonical_bytes(payload)).hexdigest()}


def master_candidate(world_id, catalog):
    # A local candidate is NOT an authenticated reference manifest.
    from .universe import public_info
    universe=public_info(catalog)
    return {'world_id':world_id, **fingerprint(catalog), **({'universe':universe} if universe else {}),
            'verification':{'status':'unverified','authority':None,'key_id':None,
                            'signature_algorithm':None,'signature':None,'distribution':None}}
