"""Read-only public round records. No universe package or secret fields."""
import json
from .statistics import calculate,read_scores
from .model import GameError


def read(c,kind,player_id,round_id=None,category=None):
    # A snapshot prevents an activation between current-round lookup and score query.
    c.execute('BEGIN')
    try:
        if not c.execute('SELECT 1 FROM players WHERE id=?',(player_id,)).fetchone():raise GameError('PLAYER_NOT_FOUND')
        if kind=='hall':return [dict(r) for r in c.execute('SELECT * FROM p4_hall ORDER BY round_id,category,rank')]
        if kind=='rounds':return [dict(r) for r in c.execute('SELECT round_id,universe_id,state,starts_at,ends_at,closed_at,finalized FROM p4_rounds ORDER BY round_id')]
        if round_id is None:
            r=c.execute('SELECT id FROM seasons ORDER BY id DESC LIMIT 1').fetchone();round_id=r[0]
        if kind=='rankings':return [r for r in read_scores(c,round_id) if category is None or r['category']==category]
        if kind=='exploration':return [dict(r) for r in c.execute('SELECT planet_id,first_at,source FROM p4_visits WHERE round_id=? AND player_id=? ORDER BY first_at,planet_id',(round_id,player_id))]
        if kind=='score':
            r=c.execute('SELECT stats_json FROM p4_statistics WHERE round_id=? AND player_id=?',(round_id,player_id)).fetchone()
            if r:return json.loads(r[0])
            return calculate(c,round_id).get(player_id,{})
        raise ValueError('unknown records query')
    finally:c.rollback()
