"""Validated provisional mechanics. Shared by runtime and offline packaging."""
import copy
from .model import integer
from .development import INDUSTRIES


def policy(data, profiles, grades):
    raw=data.get('phase3')
    if raw is None:return None
    required={'status','sales','route_cost_per_distance','jackpot_bps','route_bonus_bps',
              'restart_ship','restart_cash','insurance_cash_bps','event_interval','event_seed',
              'event_probabilities','disaster_damage','disaster_industries','loot_goods','loot_quantity',
              'pirate_loss_bps','storm_delay','repair_cost','mineral_goods','rare_goods',
              'mineral_base_bps','mineral_level_bps','mineral_abundance_divisor','rare_bps',
              'max_catchup_slots','investment_bonus_mode','ship_exchange_mode','cap_mode',
              'bankruptcy_mode','disaster_cap_mode','excess_stock_mode','disaster_effect_timing','insurance_mode','jackpot_mode'}
    if not isinstance(raw,dict) or set(raw)!=required or raw['status']!='provisional':raise ValueError('phase3 fields')
    for k in ('route_cost_per_distance','event_interval','disaster_damage','loot_quantity','storm_delay','mineral_abundance_divisor','max_catchup_slots'):
        integer(raw[k],1)
    for k in ('jackpot_bps','route_bonus_bps','insurance_cash_bps','pirate_loss_bps','mineral_base_bps','mineral_level_bps','rare_bps'):
        integer(raw[k],0,10000)
    integer(raw['restart_cash'],1,data['starting']['cash']-1);integer(raw['repair_cost'])
    if not isinstance(raw['event_seed'],str) or not raw['event_seed'] or len(raw['event_seed'])>64:raise ValueError('event seed')
    expected={'pirate','patrol','storm','failure','wreck','planet_raid','cyclone','factory_accident'}
    if set(raw['event_probabilities'])!=expected:raise ValueError('event probabilities')
    for v in raw['event_probabilities'].values():integer(v,0,10000)
    if set(raw['disaster_industries'])!={'planet_raid','cyclone','factory_accident'}:raise ValueError('disasters')
    for values in raw['disaster_industries'].values():
        if not isinstance(values,list) or not values or len(set(values))!=len(values) or set(values)-set(INDUSTRIES):raise ValueError('industry targets')
    for key,value in {'investment_bonus_mode':'accumulate_fraction_v1','ship_exchange_mode':'replace_no_refund_v1',
                      'cap_mode':'reject_no_charge_v1','bankruptcy_mode':'clear_cargo_reset_start_v1',
                      'disaster_cap_mode':'preserve_maximum_v1','excess_stock_mode':'discard_at_boundary_v1',
                      'disaster_effect_timing':'next_period_v1','insurance_mode':'one_wreck_ship_cash_no_cargo_v1',
                      'jackpot_mode':'last_donor_total_paid_v1'}.items():
        if raw[key]!=value:raise ValueError('unsupported policy')
    goods={g['id'] for g in data['goods']}
    for key in ('loot_goods','mineral_goods','rare_goods'):
        if raw[key] not in goods:raise ValueError('event goods')
    start=profiles[data['starting']['ship_id']];restart=profiles.get(raw['restart_ship'])
    if not restart or restart.ship_type!='normal' or grades[restart.grade_id].rank!=grades[start.grade_id].rank-1:raise ValueError('restart grade')
    if data.get('development',{}).get('mode') not in ('linear_units_v1','linear_levels_v1'):raise ValueError('development required')
    if not isinstance(raw['sales'],dict) or set(raw['sales'])!=set(profiles):raise ValueError('sales coverage')
    for sid,requirements in raw['sales'].items():
        if not isinstance(requirements,dict) or set(requirements)-set(INDUSTRIES):raise ValueError('sales requirements')
        for v in requirements.values():integer(v)
        p=profiles[sid]
        if any(getattr(p,k) is None for k in ('purchase_price','insurance_premium','grade_id')):raise ValueError('complete profiles required')
    return copy.deepcopy(raw)
