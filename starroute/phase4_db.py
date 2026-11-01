"""Additive operational schema and exploration persistence. No network or engine."""
import json
from pathlib import Path
from .model import GameError,integer
from .rules import canonical_bytes
import hashlib


def policy(value=None):
    if value is None:value=json.loads((Path(__file__).parent/'config/phase4.json').read_text(encoding='utf8'))
    if set(value)!={'version','status','round_seconds','trade','planet','route','exploration','ties','cutoff','unpriced_cargo'}:raise GameError('INVALID_ROUND_POLICY')
    if value['version']!=1 or value['status']!='provisional':raise GameError('INVALID_ROUND_POLICY')
    integer(value['round_seconds'],1)
    for k,allowed in {'trade':('fifo_realized_v1',),'planet':('effect_units','paid_credits'),
                       'route':('effect_units','paid_credits'),'exploration':('unique_visits_provisional',),
                       'ties':('score_desc_player_id_asc',),'cutoff':('committed_at_deadline_no_carry',),
                       'unpriced_cargo':('zero_cost_marked',)}.items():
        if value[k] not in allowed:raise GameError('INVALID_ROUND_POLICY')
    return json.loads(canonical_bytes(value))


def policy_hash(value):return hashlib.sha256(canonical_bytes(policy(value))).hexdigest()


def create(c):
    had_visits=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='p4_visits'").fetchone()
    statements=[
        '''CREATE TABLE IF NOT EXISTS p4_universes(
          universe_id TEXT PRIMARY KEY, state TEXT NOT NULL CHECK(state IN ('STAGED','VALIDATED','REGISTERED','ACTIVE','ARCHIVED')),
          package_json TEXT NOT NULL, package_hash TEXT NOT NULL, definition_hash TEXT NOT NULL,
          generator_version TEXT NOT NULL, schema_version INTEGER NOT NULL, rules_version TEXT NOT NULL,
          configuration_hash TEXT NOT NULL, source_type TEXT NOT NULL, repository_id TEXT,
          commit_id TEXT, verification_json TEXT NOT NULL, registered_at INTEGER,
          activated_at INTEGER, archived_at INTEGER)''',
        '''CREATE TABLE IF NOT EXISTS p4_rounds(
          round_id INTEGER PRIMARY KEY, universe_id TEXT NOT NULL UNIQUE REFERENCES p4_universes(universe_id),
          state TEXT NOT NULL CHECK(state IN ('PREPARED','ACTIVE','CLOSING','CLOSED','ARCHIVED')),
          starts_at INTEGER NOT NULL, ends_at INTEGER NOT NULL, closed_at INTEGER,
          finalized INTEGER NOT NULL DEFAULT 0, hall_saved INTEGER NOT NULL DEFAULT 0,
          policy_json TEXT NOT NULL, configuration_hash TEXT NOT NULL, CHECK(ends_at>starts_at))''',
        "CREATE UNIQUE INDEX IF NOT EXISTS p4_one_active ON p4_rounds(state) WHERE state='ACTIVE'",
        '''CREATE TABLE IF NOT EXISTS p4_audit(
          sequence INTEGER PRIMARY KEY, at INTEGER NOT NULL, action TEXT NOT NULL,
          universe_id TEXT, round_id INTEGER, details TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS p4_visits(
          round_id INTEGER NOT NULL, player_id TEXT NOT NULL REFERENCES players(id), planet_id TEXT NOT NULL,
          first_at INTEGER NOT NULL, source TEXT NOT NULL, PRIMARY KEY(round_id,player_id,planet_id))''',
        '''CREATE TABLE IF NOT EXISTS p4_discoveries(
          round_id INTEGER NOT NULL, event_id TEXT NOT NULL, player_id TEXT NOT NULL REFERENCES players(id),
          at INTEGER NOT NULL, kind TEXT NOT NULL, details TEXT NOT NULL, PRIMARY KEY(round_id,event_id))''',
        '''CREATE TABLE IF NOT EXISTS p4_statistics(
          round_id INTEGER NOT NULL REFERENCES p4_rounds(round_id), player_id TEXT NOT NULL,
          stats_json TEXT NOT NULL, PRIMARY KEY(round_id,player_id))''',
        '''CREATE TABLE IF NOT EXISTS p4_rankings(
          round_id INTEGER NOT NULL REFERENCES p4_rounds(round_id), category TEXT NOT NULL,
          rank INTEGER NOT NULL, player_id TEXT NOT NULL, bbs_id TEXT NOT NULL, user_id TEXT NOT NULL,
          display_name TEXT NOT NULL, score INTEGER NOT NULL, evaluation TEXT NOT NULL,
          PRIMARY KEY(round_id,category,rank), UNIQUE(round_id,category,player_id))''',
        '''CREATE TABLE IF NOT EXISTS p4_hall(
          round_id INTEGER NOT NULL REFERENCES p4_rounds(round_id), universe_id TEXT NOT NULL,
          category TEXT NOT NULL, rank INTEGER NOT NULL CHECK(rank BETWEEN 1 AND 3), player_id TEXT NOT NULL,
          bbs_id TEXT NOT NULL, user_id TEXT NOT NULL, display_name TEXT NOT NULL,
          score INTEGER NOT NULL, closed_at INTEGER NOT NULL, evaluation TEXT NOT NULL,
          PRIMARY KEY(round_id,category,rank), UNIQUE(round_id,category,player_id))''',
        '''CREATE TABLE IF NOT EXISTS p4_archives(
          round_id INTEGER PRIMARY KEY REFERENCES p4_rounds(round_id), universe_id TEXT NOT NULL,
          snapshot BLOB NOT NULL, sha256 TEXT NOT NULL, created_at INTEGER NOT NULL)''',
    ]
    for sql in statements:c.execute(sql)
    for table in ('p4_hall','p4_rankings','p4_statistics','p4_archives'):
        for operation in ('UPDATE','DELETE'):
            c.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE_ROUND_RECORD'); END")
    if had_visits:return
    # Existing visits can be reconstructed only where a committed arrival is known.
    c.execute('''INSERT OR IGNORE INTO p4_visits
      SELECT s.season_id,s.player_id,s.planet_id,t.game_time,'legacy_current_location'
      FROM player_state s JOIN seasons t ON t.id=s.season_id''')
    ambiguous=set()
    for saved in c.execute('SELECT season_id,state_json FROM phase3_state'):
        for e in json.loads(saved['state_json']).get('events',{}).values():
            if e['kind'] in ('storm','wreck'):ambiguous.add((saved['season_id'],e['target']))
    for r in c.execute('''SELECT v.season_id,v.player_id,v.destination_id,MIN(v.arrival_at) AS at
      FROM voyages v JOIN seasons s ON s.id=v.season_id WHERE v.arrival_at<=s.game_time
      GROUP BY v.season_id,v.player_id,v.destination_id''').fetchall():
        if (r['season_id'],r['player_id']) in ambiguous:continue
        c.execute('''INSERT INTO p4_visits VALUES (?,?,?,?,'legacy_completed_voyage')
          ON CONFLICT(round_id,player_id,planet_id) DO UPDATE SET first_at=MIN(first_at,excluded.first_at)''',tuple(r))


def save_exploration(c,world):
    for pid,planet,at,source in world.exploration_events:
        c.execute('''INSERT INTO p4_visits VALUES (?,?,?,?,?)
          ON CONFLICT(round_id,player_id,planet_id) DO UPDATE SET first_at=MIN(first_at,excluded.first_at)''',
          (world.season_id,pid,planet,at,source))
    for p in world.players.values():
        if p.destination_id is None:
            c.execute('INSERT OR IGNORE INTO p4_visits VALUES (?,?,?,?,?)',(world.season_id,p.id,p.planet_id,world.game_time,'confirmed_location'))
    for eid,event in world.phase3_state.get('events',{}).items():
        if event['kind']=='mineral':
            n=world.phase3_state['news'][eid]
            c.execute('INSERT OR IGNORE INTO p4_discoveries VALUES (?,?,?,?,?,?)',
                      (world.season_id,eid,event['target'],n['game_time'],'mineral',json.dumps(event,sort_keys=True)))


def guard(c,world,now):
    managed=c.execute("SELECT value FROM metadata WHERE key='phase4_managed'").fetchone()
    if not managed:return
    row=c.execute('SELECT * FROM p4_rounds WHERE round_id=?',(world.season_id,)).fetchone()
    if not row or row['state']!='ACTIVE':raise GameError('ROUND_NOT_ACTIVE')
    if now<row['starts_at']:raise GameError('ROUND_NOT_STARTED')
    if now>=row['ends_at']:raise GameError('ROUND_ENDED')
