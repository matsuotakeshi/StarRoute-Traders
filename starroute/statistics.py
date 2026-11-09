"""Deterministic scores from committed journals. No client-supplied scores."""
import json
from .phase4_db import policy
from .model import GameError

CATEGORIES=('trade','planet','route','exploration')


def calculate(c,round_id,settings=None):
    settings=policy(settings)
    players={r['id']:dict(player_id=r['id'],display_name=r['handle'],bbs_id=r['bbs_id'],user_id=r['local_user_id'])
             for r in c.execute('SELECT p.*,a.bbs_id,a.local_user_id FROM players p JOIN bbs_accounts a ON a.player_id=p.id JOIN player_state s ON s.player_id=p.id WHERE s.season_id=?',(round_id,))}
    stats={pid:{**row,**dict.fromkeys(('trade_profit','purchases','sales','navigation_cost','planet_paid','planet_effect','planet_bonus',
          'route_paid','route_effect','route_bonus','jackpot','insurance_premium','insurance_claim','restart_grant','bankruptcy_cash_removed',
          'ship_cost','device_cost','guild_cost','pirate_loss','repair_cost','exploration','unpriced_units'),0)} for pid,row in players.items()}
    lots={pid:{} for pid in players}
    epochs={pid:0 for pid in players}
    def consume(pid,good,count):
        queue=lots[pid].setdefault(good,[]);cost=0
        while count and queue:
            qty,paid=queue[0];used=min(qty,count);amount=paid if used==qty else paid*used//qty
            cost+=amount;count-=used
            if used==qty:queue.pop(0)
            else:queue[0]=[qty-used,paid-amount]
        return cost
    def reconcile(pid,cargo):
        for good in set(lots[pid])|set(cargo):
            known=sum(q for q,_ in lots[pid].get(good,[]));actual=cargo.get(good,0)
            if actual>known:
                lots[pid].setdefault(good,[]).append([actual-known,0]);stats[pid]['unpriced_units']+=actual-known
            elif known>actual:consume(pid,good,known-actual)
    # Operation sequence is the authoritative serialization order, not client time.
    for row in c.execute('SELECT * FROM operation_history WHERE season_id=? ORDER BY sequence',(round_id,)):
        result=json.loads(row['result']);before=json.loads(row['before_state']);after=json.loads(row['after_state'])
        if not after:continue
        pid=after['id']
        if pid not in stats:continue
        s=stats[pid];payload=json.loads(row['payload']);method=payload[0]
        epoch=(before or {}).get('_cargo_epoch',epochs[pid])
        if epoch!=epochs[pid]:lots[pid]={};epochs[pid]=epoch
        reconcile(pid,before.get('cargo',{}) if before else {})
        if method=='buy_goods':
            lots[pid].setdefault(result['goods_id'],[]).append([result['quantity'],result['total']]);s['purchases']+=result['total']
        elif method=='sell_goods':
            cost=consume(pid,result['goods_id'],result['quantity']);s['sales']+=result['total'];s['trade_profit']+=result['total']-cost
        elif method in ('depart','navigate','coordinate_depart'):s['navigation_cost']+=result.get('fuel_cost',result.get('fee',0)) or 0
        elif method=='invest':
            s['planet_paid']+=result['paid_credits'];s['planet_effect']+=result['effect_units']
            # The catalog is the frozen effective policy for this current round.
            catalog=json.loads(c.execute("SELECT value FROM metadata WHERE key='catalog'").fetchone()[0])
            base=result['paid_credits']//catalog['development']['credits_per_unit'][result['industry']]
            s['planet_bonus']+=result['effect_units']-base
        elif method=='donate':
            s['route_paid']+=result['paid_credits'];s['route_effect']+=result['effect_units'];s['route_bonus']+=result['effect_units']-result['paid_credits'];s['jackpot']+=result['jackpot']
        elif method=='insure':s['insurance_premium']+=result['paid_credits']
        elif method=='buy_device':s['device_cost']+=result['paid_credits']
        elif method=='guild':s['guild_cost']+=result['paid_credits']
        elif method=='buy_ship':s['ship_cost']+=result['paid_credits']
        elif method=='bankrupt':
            s['restart_grant']+=result['cash'];s['bankruptcy_cash_removed']+=(before or {}).get('cash',0)
        reconcile(pid,after.get('cargo',{}))
    record=c.execute('SELECT state_json FROM phase3_state WHERE season_id=?',(round_id,)).fetchone()
    if record:
        events=json.loads(record[0]).get('events',{})
        catalog=json.loads(c.execute("SELECT value FROM metadata WHERE key='catalog'").fetchone()[0]);cfg=catalog.get('phase3',{})
        from .catalog import Catalog
        profiles=Catalog(catalog).ship_profiles
        for e in events.values():
            s=stats.get(e['target'])
            if s is None:continue
            if e['kind']=='pirate':s['pirate_loss']+=e['loss']
            elif e['kind']=='failure':s['repair_cost']+=e['loss']
            elif e['kind']=='wreck':
                if e['insured_rescue']:s['insurance_claim']+=profiles[e['ship_id']].purchase_price*cfg['insurance_cash_bps']//10000
                else:s['restart_grant']+=e['cash']
    for row in c.execute('SELECT player_id,count(*) AS n FROM p4_visits WHERE round_id=? GROUP BY player_id',(round_id,)):
        if row['player_id'] in stats:stats[row['player_id']]['exploration']=row['n']
    return stats


def rankings(stats,settings=None):
    settings=policy(settings)
    fields={'trade':'trade_profit','planet':'planet_effect' if settings['planet']=='effect_units' else 'planet_paid',
            'route':'route_effect' if settings['route']=='effect_units' else 'route_paid','exploration':'exploration'}
    result=[]
    for category,field in fields.items():
        for rank,row in enumerate(sorted(stats.values(),key=lambda s:(-s[field],s['player_id'])),1):
            result.append({k:row[k] for k in ('player_id','bbs_id','user_id','display_name')}|
                          dict(category=category,rank=rank,score=row[field],evaluation='provisional_unique_visits_not_victory' if category=='exploration' else 'provisional'))
    return result


def read_scores(c,round_id):
    row=c.execute('SELECT * FROM p4_rounds WHERE round_id=?',(round_id,)).fetchone()
    if row and row['finalized']:
        return [dict(r) for r in c.execute('SELECT * FROM p4_rankings WHERE round_id=? ORDER BY category,rank',(round_id,))]
    if not c.execute('SELECT 1 FROM seasons WHERE id=?',(round_id,)).fetchone():raise GameError('ROUND_NOT_FOUND')
    settings=json.loads(row['policy_json']) if row else None
    return rankings(calculate(c,round_id,settings),settings)
