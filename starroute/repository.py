"""SQLite persistence adapter. One local database represents one shared world."""
from contextlib import contextmanager
import json
import sqlite3
import uuid
import os
from pathlib import Path
from .catalog import Catalog
from .model import GameError, Market, Player, World, MAX_VALUE

SCHEMA_VERSION = 11
SCHEMA = f"""
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE seasons(
 id INTEGER PRIMARY KEY, status TEXT NOT NULL CHECK(status IN ('active','closing','closed')),
 started_at INTEGER NOT NULL, game_time INTEGER NOT NULL CHECK(game_time>=0));
CREATE UNIQUE INDEX one_active_season ON seasons(status) WHERE status='active';
CREATE TABLE players(id TEXT PRIMARY KEY, handle TEXT NOT NULL);
CREATE TABLE ships(id TEXT PRIMARY KEY, name TEXT NOT NULL, capacity INTEGER NOT NULL CHECK(capacity>0),
 max_distance INTEGER NOT NULL CHECK(max_distance>0), speed INTEGER NOT NULL CHECK(speed>0));
CREATE TABLE planets(id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE goods(id TEXT PRIMARY KEY, name TEXT NOT NULL, base_price INTEGER NOT NULL CHECK(base_price>0),
 volume INTEGER NOT NULL CHECK(volume>0), production INTEGER NOT NULL CHECK(production>=0),
 volatility_bps INTEGER NOT NULL CHECK(volatility_bps BETWEEN 0 AND 10000));
CREATE TABLE player_state(
 season_id INTEGER NOT NULL REFERENCES seasons(id), player_id TEXT NOT NULL REFERENCES players(id),
 cash INTEGER NOT NULL CHECK(cash BETWEEN 0 AND {MAX_VALUE}), ship_id TEXT NOT NULL REFERENCES ships(id),
 planet_id TEXT NOT NULL REFERENCES planets(id), destination_id TEXT REFERENCES planets(id), arrival_at INTEGER,
 PRIMARY KEY(season_id,player_id),
 CHECK((destination_id IS NULL AND arrival_at IS NULL) OR
       (destination_id IS NOT NULL AND arrival_at IS NOT NULL AND arrival_at>=0)));
CREATE TABLE cargo(
 season_id INTEGER NOT NULL, player_id TEXT NOT NULL, goods_id TEXT NOT NULL REFERENCES goods(id),
 quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND {MAX_VALUE}),
 PRIMARY KEY(season_id,player_id,goods_id),
 FOREIGN KEY(season_id,player_id) REFERENCES player_state(season_id,player_id));
CREATE TABLE markets(
 season_id INTEGER NOT NULL REFERENCES seasons(id), planet_id TEXT NOT NULL REFERENCES planets(id),
 goods_id TEXT NOT NULL REFERENCES goods(id), price INTEGER NOT NULL CHECK(price BETWEEN 1 AND {MAX_VALUE}),
 stock INTEGER NOT NULL CHECK(stock BETWEEN 0 AND {MAX_VALUE}), PRIMARY KEY(season_id,planet_id,goods_id));
CREATE TABLE routes(
 season_id INTEGER NOT NULL REFERENCES seasons(id), id TEXT NOT NULL,
 from_id TEXT NOT NULL REFERENCES planets(id), to_id TEXT NOT NULL REFERENCES planets(id),
 distance INTEGER NOT NULL CHECK(distance>0), seconds INTEGER NOT NULL CHECK(seconds>0),
 fee INTEGER NOT NULL CHECK(fee BETWEEN 0 AND {MAX_VALUE}), is_open INTEGER NOT NULL CHECK(is_open IN (0,1)),
 PRIMARY KEY(season_id,id), CHECK(from_id<>to_id));
"""


class SQLiteRepository:
    def __init__(self, path, catalog=None, now=0, *, default_catalog_path=None):
        self.path = str(path)
        self.backup_path = None
        self.connection = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("BEGIN IMMEDIATE")
            exists = self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone()
            if exists:
                version = self.connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
                if not version or version[0] not in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10", str(SCHEMA_VERSION)):
                    raise GameError("UNSUPPORTED_SCHEMA")
                row = self.connection.execute("SELECT value FROM metadata WHERE key='catalog'").fetchone()
                self.catalog = Catalog(json.loads(row[0]))
                if catalog is not None and catalog.canonical() != self.catalog.canonical():
                    raise GameError("CONFIG_MISMATCH")
                if version[0] in ("1", "2", "3", "4", "5", "6", "7", "8"):
                    self._backup(version[0])
                    if version[0] == "1":
                        self._foundation()
                    if version[0] in ("1", "2"):
                        self._ship_models()
                    if version[0] in ("1", "2", "3"):
                        self._navigation()
                    if version[0] in ("1", "2", "3", "4"):
                        self._world_identity()
                    if version[0] in ("1", "2", "3", "4", "5"):
                        self._economy_tables()
                    if version[0] in ("1", "2", "3", "4", "5", "6"):
                        self._development_tables()
                    if version[0] != "8":
                        self._event_tables()
                    self._industry_tables()
                    self.connection.execute("UPDATE metadata SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            else:
                # Execute statements individually: executescript would implicitly COMMIT.
                if self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise GameError("UNSUPPORTED_SCHEMA")
                self.catalog = catalog or Catalog.load(default_catalog_path)
                for statement in SCHEMA.split(";"):
                    if statement.strip():
                        self.connection.execute(statement)
                self._seed(now)
                self._foundation()
                self._ship_models()
                self._navigation()
                self._world_identity()
                self._economy_tables()
                self._development_tables()
                self._event_tables()
                self._industry_tables()
            if exists and version[0] in ('9','10'):self._backup(version[0])
            self.connection.execute('CREATE TABLE IF NOT EXISTS phase3_state(season_id INTEGER PRIMARY KEY REFERENCES seasons(id), state_json TEXT NOT NULL)')
            self.connection.execute("UPDATE metadata SET value=? WHERE key='schema_version'",(str(SCHEMA_VERSION),))
            from .phase4_db import create as phase4_tables
            phase4_tables(self.connection)
            identity = self.connection.execute("SELECT world_id FROM world_identity WHERE singleton=1").fetchone()
            if not identity:
                raise GameError("CONFIG_VERIFICATION_FAILED")
            try:
                self.world_id = str(uuid.UUID(identity[0]))
                if self.world_id != identity[0]: raise ValueError("world_id")
            except (ValueError, TypeError):
                raise GameError("CONFIG_VERIFICATION_FAILED") from None
            self._check_navigation()
            self._check_ship_models()
            self._check_development()
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            self.connection.close()
            raise


    def check_round(self,world,now):
        from .phase4_db import guard
        guard(self.connection,world,now)

    def records(self,kind,player_id,round_id=None,category=None):
        from .records import read
        return read(self.connection,kind,player_id,round_id,category)

    def _industry_tables(self):
        self.connection.execute("""CREATE TABLE industry_periods(
            season_id INTEGER NOT NULL, planet_id TEXT NOT NULL, goods_id TEXT NOT NULL,
            production_rate INTEGER NOT NULL CHECK(production_rate>=0),
            capacity INTEGER NOT NULL CHECK(capacity>0),
            PRIMARY KEY(season_id,planet_id,goods_id),
            FOREIGN KEY(season_id,planet_id,goods_id) REFERENCES markets(season_id,planet_id,goods_id))""")
        if self.catalog.industry_effects['mode'] == 'disabled': return
        from .industry_effects import values
        for season in self.connection.execute('SELECT id FROM seasons').fetchall():
            sid=season[0]
            progress={(r['planet_id'],r['industry']):r['progress'] for r in self.connection.execute('SELECT * FROM planet_development WHERE season_id=?',(sid,))}
            for key in self.catalog.economy_markets:
                output,capacity=values(self.catalog,progress,key)
                self.connection.execute('INSERT INTO industry_periods VALUES (?,?,?,?,?)',(sid,*key,output,capacity))

    def _event_tables(self):
        self.connection.execute('CREATE TABLE event_clock(season_id INTEGER PRIMARY KEY REFERENCES seasons(id),anchor INTEGER NOT NULL,last_slot INTEGER NOT NULL CHECK(last_slot>=0))')
        self.connection.execute('INSERT INTO event_clock SELECT id,game_time,0 FROM seasons')
        self.connection.execute("""CREATE TABLE market_event_history(sequence INTEGER PRIMARY KEY,season_id INTEGER NOT NULL REFERENCES seasons(id),slot INTEGER NOT NULL,
            planet_id TEXT NOT NULL REFERENCES planets(id),goods_id TEXT NOT NULL REFERENCES goods(id),kind TEXT NOT NULL CHECK(kind IN ('surge','crash')),
            delta INTEGER NOT NULL,starts_at INTEGER NOT NULL,ends_at INTEGER NOT NULL,
            UNIQUE(season_id,slot,planet_id,goods_id))""")

    def event_history(self,after=0,limit=50):
        from .model import integer
        integer(after);integer(limit,1,100)
        return [dict(r) for r in self.connection.execute('SELECT * FROM market_event_history WHERE sequence>? ORDER BY sequence LIMIT ?',(after,limit))]

    def _development_tables(self):
        self.connection.execute("""CREATE TABLE planet_development(
            season_id INTEGER NOT NULL REFERENCES seasons(id),planet_id TEXT NOT NULL REFERENCES planets(id),
            industry TEXT NOT NULL CHECK(industry IN ('primary','secondary','tertiary','quaternary')),
            progress INTEGER NOT NULL CHECK(progress>=0), PRIMARY KEY(season_id,planet_id,industry))""")
        for season in self.connection.execute('SELECT id FROM seasons').fetchall():
            for pid,row in self.catalog.development_planets.items():
                self.connection.executemany('INSERT INTO planet_development VALUES (?,?,?,?)',
                    [(season[0],pid,k,v) for k,v in row['initial_progress'].items()])
        self.connection.execute("""CREATE TABLE investment_records(
            sequence INTEGER PRIMARY KEY,season_id INTEGER NOT NULL REFERENCES seasons(id),
            player_id TEXT NOT NULL REFERENCES players(id),planet_id TEXT NOT NULL REFERENCES planets(id),
            industry TEXT NOT NULL,paid_credits INTEGER NOT NULL CHECK(paid_credits>0),
            effect_units INTEGER NOT NULL CHECK(effect_units>0),progress_before INTEGER NOT NULL,
            progress_after INTEGER NOT NULL,game_time INTEGER NOT NULL,request_id TEXT NOT NULL,
            policy_version TEXT NOT NULL,rules_hash TEXT,UNIQUE(season_id,player_id,request_id))""")
        self.connection.execute('CREATE INDEX investments_player ON investment_records(player_id,sequence)')

    def _check_development(self):
        expected={(s[0],pid,k) for s in self.connection.execute('SELECT id FROM seasons')
                  for pid,row in self.catalog.development_planets.items() for k in row['initial_progress']}
        rows=self.connection.execute('SELECT * FROM planet_development').fetchall()
        if {(r['season_id'],r['planet_id'],r['industry']) for r in rows}!=expected:
            raise GameError('CONFIG_VERIFICATION_FAILED')
        for row in rows:
            if row['progress']>self.catalog.development_planets[row['planet_id']]['private_caps'][row['industry']]:
                raise GameError('CONFIG_VERIFICATION_FAILED')

    def record_investment(self, world, player_id, receipt, request_id):
        from .rules import fingerprint, RULES_VERSION
        try: rules_hash=fingerprint(self.catalog)['sha256']
        except GameError: rules_hash=None
        self.connection.execute('INSERT INTO investment_records VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?)',
            (world.season_id,player_id,receipt['planet_id'],receipt['industry'],receipt['paid_credits'],
             receipt['effect_units'],receipt['progress']-receipt['effect_units'],receipt['progress'],
             world.game_time,request_id,RULES_VERSION,rules_hash))

    def investment_ledger(self, player_id, after=0, limit=50):
        from .model import integer
        from .catalog import identifier
        identifier(player_id);integer(after);integer(limit,1,100)
        # Explicit public projection, never serialize policy/catalog objects here.
        return [dict(row) for row in self.connection.execute(
            'SELECT sequence,season_id,player_id,planet_id,industry,paid_credits,effect_units,progress_before,progress_after,game_time,request_id FROM investment_records WHERE player_id=? AND sequence>? ORDER BY sequence LIMIT ?',
            (player_id,after,limit))]

    def _economy_tables(self):
        self.connection.execute("CREATE TABLE economy_clock(season_id INTEGER PRIMARY KEY REFERENCES seasons(id), updated_at INTEGER NOT NULL CHECK(updated_at>=0))")
        self.connection.execute("INSERT INTO economy_clock SELECT id,game_time FROM seasons")
        self.connection.execute("""CREATE TABLE trade_ledger(
            sequence INTEGER PRIMARY KEY, season_id INTEGER NOT NULL REFERENCES seasons(id),
            player_id TEXT NOT NULL REFERENCES players(id), planet_id TEXT NOT NULL REFERENCES planets(id),
            goods_id TEXT NOT NULL REFERENCES goods(id), side TEXT NOT NULL CHECK(side IN ('buy','sell')),
            quantity INTEGER NOT NULL CHECK(quantity>0), total INTEGER NOT NULL CHECK(total>=0),
            first_unit_price INTEGER NOT NULL, last_unit_price INTEGER NOT NULL,
            stock_before INTEGER NOT NULL, stock_after INTEGER NOT NULL,
            cash_before INTEGER NOT NULL, cash_after INTEGER NOT NULL,
            game_time INTEGER NOT NULL, request_id TEXT NOT NULL, rules_hash TEXT,
            pricing_mode TEXT NOT NULL, UNIQUE(season_id,player_id,request_id))""")
        self.connection.execute("CREATE INDEX ledger_player ON trade_ledger(player_id,sequence)")

    def record_trade(self, world, player_id, planet_id, receipt, before, request_id):
        from .rules import fingerprint
        try: rules_hash=fingerprint(self.catalog)['sha256']
        except GameError:
            # Old catalogs with unclassified fields remain playable, never certified.
            rules_hash=None
        after=world.players[player_id];stock=world.markets[planet_id,receipt['goods_id']].stock
        old_stock=stock+receipt['quantity'] if receipt['side']=='buy' else stock-receipt['quantity']
        self.connection.execute("INSERT INTO trade_ledger VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (world.season_id,player_id,planet_id,receipt['goods_id'],receipt['side'],receipt['quantity'],receipt['total'],
             receipt.get('first_unit_price',receipt['unit_price']),receipt.get('last_unit_price',receipt['unit_price']),
             old_stock,stock,before['cash'],after.cash,world.game_time,request_id,rules_hash,self.catalog.economy['mode']))

    def trade_ledger(self, player_id, after=0, limit=50):
        from .model import integer
        from .catalog import identifier
        identifier(player_id);integer(after);integer(limit,1,100)
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM trade_ledger WHERE player_id=? AND sequence>? ORDER BY sequence LIMIT ?",(player_id,after,limit))]

    def _world_identity(self):
        self.connection.execute("CREATE TABLE world_identity(singleton INTEGER PRIMARY KEY CHECK(singleton=1), world_id TEXT NOT NULL UNIQUE)")
        self.connection.execute("INSERT INTO world_identity VALUES (1,?)", (str(uuid.uuid4()),))

    def account_identity(self, bbs_id, local_user_id):
        return {'world_id': self.world_id, 'bbs_id': bbs_id, 'local_user_id': local_user_id,
                'player_id': self.resolve_account(bbs_id, local_user_id)}

    def _backup(self, version):
        # BEGIN IMMEDIATE already excludes writers. A separate reader can back up
        # the committed old database without deadlocking the writer connection.
        if self.path == ':memory:':
            return
        self.backup_path = self.path + '.v' + version + '-backup-' + uuid.uuid4().hex + '.db'
        fd = os.open(self.backup_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        source = sqlite3.connect(self.path)
        target = sqlite3.connect(self.backup_path)
        try:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise sqlite3.DatabaseError('backup integrity')
        finally:
            source.close()
            target.close()

    def _foundation(self):
        statements = [
            "CREATE TABLE bbs_accounts(bbs_id TEXT NOT NULL, local_user_id TEXT NOT NULL, player_id TEXT NOT NULL UNIQUE REFERENCES players(id) DEFERRABLE INITIALLY DEFERRED, PRIMARY KEY(bbs_id,local_user_id))",
            "CREATE TABLE preferences(player_id TEXT PRIMARY KEY REFERENCES players(id), language TEXT NOT NULL CHECK(language IN ('ja','en')))",
            "CREATE TABLE operation_history(sequence INTEGER PRIMARY KEY, season_id INTEGER NOT NULL REFERENCES seasons(id), actor TEXT NOT NULL, request_id TEXT NOT NULL, payload TEXT NOT NULL, result TEXT NOT NULL, before_state TEXT NOT NULL, after_state TEXT NOT NULL, game_time INTEGER NOT NULL, UNIQUE(season_id,actor,request_id))",
        ]
        for statement in statements:
            self.connection.execute(statement)
        self.connection.execute("INSERT INTO bbs_accounts SELECT 'local',id,id FROM players")

    def _ship_models(self):
        c = self.connection
        c.execute("CREATE TABLE ship_grades(id TEXT PRIMARY KEY, rank INTEGER NOT NULL UNIQUE CHECK(rank>0))")
        c.execute("""CREATE TABLE ship_profiles(
            ship_id TEXT PRIMARY KEY REFERENCES ships(id),
            ship_type TEXT CHECK(ship_type IN ('normal','armed_cruiser','engineering')),
            grade_id TEXT REFERENCES ship_grades(id),
            normal_speed INTEGER CHECK(normal_speed>0),
            max_warp_speed INTEGER CHECK(max_warp_speed>0),
            purchase_price INTEGER CHECK(purchase_price>=0),
            insurance_premium INTEGER CHECK(insurance_premium>=0),
            specification_status TEXT NOT NULL CHECK(specification_status IN ('legacy','provisional','confirmed')))
        """)
        c.executemany('INSERT INTO ship_grades VALUES (?,?)', [(g.id,g.rank) for g in self.catalog.ship_grades.values()])
        c.executemany('INSERT INTO ship_profiles VALUES (:ship_id,:ship_type,:grade_id,:normal_speed,:max_warp_speed,:purchase_price,:insurance_premium,:specification_status)', [p.dto() for p in self.catalog.ship_profiles.values()])

    def _check_ship_models(self):
        grades = {r['id']:r['rank'] for r in self.connection.execute('SELECT * FROM ship_grades')}
        profiles = {r['ship_id']:dict(r) for r in self.connection.execute('SELECT * FROM ship_profiles')}
        if grades != {g.id:g.rank for g in self.catalog.ship_grades.values()} or profiles != {k:p.dto() for k,p in self.catalog.ship_profiles.items()}:
            raise GameError('SHIP_MODEL_MISMATCH')

    def _navigation(self):
        c=self.connection
        c.execute("CREATE TABLE navigation_policy(id INTEGER PRIMARY KEY CHECK(id=1), policy TEXT NOT NULL)")
        c.execute('INSERT INTO navigation_policy VALUES (1,?)',(json.dumps(self.catalog.data.get('navigation'),sort_keys=True),))
        c.execute("""CREATE TABLE voyages(
            sequence INTEGER PRIMARY KEY,
            season_id INTEGER NOT NULL REFERENCES seasons(id), player_id TEXT NOT NULL REFERENCES players(id),
            origin_id TEXT NOT NULL REFERENCES planets(id), destination_id TEXT NOT NULL REFERENCES planets(id),
            mode TEXT NOT NULL CHECK(mode IN ('legacy','normal','warp')), level TEXT,
            departure_at INTEGER, arrival_at INTEGER NOT NULL CHECK(arrival_at>=0),
            fuel_cost INTEGER CHECK(fuel_cost>=0), quote_id TEXT, request_id TEXT NOT NULL,
            UNIQUE(season_id,player_id,request_id))""")
        c.execute("""INSERT INTO voyages(season_id,player_id,origin_id,destination_id,mode,arrival_at,request_id)
            SELECT season_id,player_id,planet_id,destination_id,'legacy',arrival_at,'migration-pending'
            FROM player_state WHERE destination_id IS NOT NULL""")

    def _check_navigation(self):
        row=self.connection.execute('SELECT policy FROM navigation_policy WHERE id=1').fetchone()
        if not row or row[0]!=json.dumps(self.catalog.data.get('navigation'),sort_keys=True):
            raise GameError('NAVIGATION_POLICY_MISMATCH')

    def record_voyage(self, season_id, player_id, origin, departure, receipt, request_id):
        self.connection.execute('INSERT INTO voyages(season_id,player_id,origin_id,destination_id,mode,level,departure_at,arrival_at,fuel_cost,quote_id,request_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (season_id,player_id,origin,receipt['destination_id'],receipt.get('mode','normal'),receipt.get('level'),departure,receipt['arrival_at'],receipt['fee'],receipt.get('quote_id'),request_id))

    def latest_voyage(self, season_id, player_id):
        row=self.connection.execute('SELECT * FROM voyages WHERE season_id=? AND player_id=? ORDER BY sequence DESC LIMIT 1',(season_id,player_id)).fetchone()
        return dict(row) if row else None

    def find_operation(self, season_id, actor, request_id):
        row = self.connection.execute('SELECT payload,result FROM operation_history WHERE season_id=? AND actor=? AND request_id=?', (season_id,actor,request_id)).fetchone()
        return dict(row) if row else None

    def record_operation(self, season_id, actor, request_id, payload, result, before, after, game_time):
        self.connection.execute('INSERT INTO operation_history(season_id,actor,request_id,payload,result,before_state,after_state,game_time) VALUES (?,?,?,?,?,?,?,?)',
            (season_id,actor,request_id,payload,json.dumps(result,ensure_ascii=False),json.dumps(before,ensure_ascii=False),json.dumps(after,ensure_ascii=False),game_time))

    def account_exists(self, bbs_id, local_user_id):
        return self.connection.execute('SELECT 1 FROM bbs_accounts WHERE bbs_id=? AND local_user_id=?', (bbs_id,local_user_id)).fetchone() is not None

    def bind_account(self, bbs_id, local_user_id, player_id):
        self.connection.execute('INSERT INTO bbs_accounts VALUES (?,?,?)', (bbs_id,local_user_id,player_id))

    def resolve_account(self, bbs_id, local_user_id):
        from .catalog import identifier
        identifier(bbs_id); identifier(local_user_id)
        row = self.connection.execute('SELECT player_id FROM bbs_accounts WHERE bbs_id=? AND local_user_id=?', (bbs_id,local_user_id)).fetchone()
        if row is None:
            raise GameError('PLAYER_NOT_FOUND')
        return row[0]

    def get_language(self, player_id, default="ja"):
        row = self.connection.execute('SELECT language FROM preferences WHERE player_id=?', (player_id,)).fetchone()
        return row[0] if row else default

    def set_language(self, player_id, language):
        if language not in ('ja','en'):
            raise GameError('INVALID_LANGUAGE')
        with self.transaction() as world:
            if player_id not in world.players:
                raise GameError('PLAYER_NOT_FOUND')
            self.connection.execute('INSERT INTO preferences VALUES (?,?) ON CONFLICT(player_id) DO UPDATE SET language=excluded.language', (player_id,language))

    def _seed(self, now):
        c = self.connection
        d = self.catalog.data
        c.executemany("INSERT INTO metadata VALUES (?,?)", [
            ("schema_version", str(SCHEMA_VERSION)), ("catalog", self.catalog.canonical())])
        c.execute("INSERT INTO seasons VALUES (1,'active',?,?)", (now, now))
        c.executemany("INSERT INTO planets VALUES (:id,:name)", d["planets"])
        c.executemany("INSERT INTO goods VALUES (:id,:name,:base_price,:volume,:production,:volatility_bps)", d["goods"])
        c.executemany("INSERT INTO ships VALUES (:id,:name,:capacity,:max_distance,:speed)", d["ships"])
        c.executemany("INSERT INTO markets VALUES (1,:planet_id,:goods_id,:price,:stock)", d["markets"])
        c.executemany('INSERT INTO routes VALUES (1,:id,:from,:to,:distance,:seconds,:fee,:is_open)', d["routes"])

    @contextmanager
    def transaction(self):
        c = self.connection
        c.execute("BEGIN IMMEDIATE")
        try:
            if c.execute("SELECT 1 FROM metadata WHERE key='node_paused' AND value='1'").fetchone():raise GameError('NODE_TRANSITION')
            stored=c.execute("SELECT value FROM metadata WHERE key='catalog'").fetchone()
            if not stored or stored[0]!=self.catalog.canonical():raise GameError('WORLD_CHANGED')
            if c.execute("SELECT value FROM metadata WHERE key='phase4_managed'").fetchone():
                if not c.execute("SELECT 1 FROM p4_rounds WHERE state='ACTIVE'").fetchone():raise GameError('ROUND_NOT_ACTIVE')
            world = self._load()
            yield world
            self._save(world)
            c.commit()
        except BaseException:
            c.rollback()
            raise

    def _load(self):
        c = self.connection
        season = c.execute("SELECT * FROM seasons WHERE status='active'").fetchone()
        if not season:
            raise GameError("NO_ACTIVE_SEASON")
        sid = season["id"]
        players = {}
        for r in c.execute("SELECT s.*,p.handle FROM player_state s JOIN players p ON p.id=s.player_id WHERE s.season_id=?", (sid,)):
            players[r["player_id"]] = Player(
                r["player_id"], r["handle"], r["cash"], r["ship_id"], r["planet_id"],
                destination_id=r["destination_id"], arrival_at=r["arrival_at"])
        for r in c.execute("SELECT * FROM cargo WHERE season_id=?", (sid,)):
            players[r["player_id"]].cargo[r["goods_id"]] = r["quantity"]
        markets = {(r["planet_id"], r["goods_id"]): Market(r["price"], r["stock"])
                   for r in c.execute("SELECT * FROM markets WHERE season_id=?", (sid,))}
        routes = {r["id"]: {"from": r["from_id"], "to": r["to_id"], "distance": r["distance"],
                              "seconds": r["seconds"], "fee": r["fee"], "is_open": bool(r["is_open"])}
                  for r in c.execute("SELECT * FROM routes WHERE season_id=?", (sid,))}
        clock=c.execute("SELECT updated_at FROM economy_clock WHERE season_id=?",(sid,)).fetchone()
        if clock is None:raise GameError("CONFIG_VERIFICATION_FAILED")
        developments={(r["planet_id"],r["industry"]):r["progress"] for r in c.execute("SELECT * FROM planet_development WHERE season_id=?",(sid,))}
        event_clock=c.execute("SELECT anchor,last_slot FROM event_clock WHERE season_id=?",(sid,)).fetchone()
        if event_clock is None:raise GameError("CONFIG_VERIFICATION_FAILED")
        active=[{k:r[k] for k in ("slot","planet_id","goods_id","kind","delta","starts_at","ends_at")} for r in c.execute("SELECT * FROM market_event_history WHERE season_id=? AND ends_at>?",(sid,season["game_time"]))]
        periods=c.execute('SELECT * FROM industry_periods WHERE season_id=?',(sid,)).fetchall()
        expected=set(markets) if self.catalog.industry_effects['mode']!='disabled' else set()
        if {(r['planet_id'],r['goods_id']) for r in periods} != expected:
            raise GameError('CONFIG_VERIFICATION_FAILED')
        for row in periods:
            key=(row['planet_id'],row['goods_id'])
            from .industry_effects import values
            bounds=developments
            if self.catalog.phase3 is not None:
                bounds={(pid,i):v for pid,row in self.catalog.development_planets.items() for i,v in row['private_caps'].items()}
            max_output,max_capacity=values(self.catalog,bounds,key)
            base_output=self.catalog.production_sources.get(key,{}).get('units_per_tick',0)
            base_capacity=self.catalog.economy_markets[key]['stock_limit']
            if not (base_output<=row['production_rate']<=max_output and base_capacity<=row['capacity']<=max_capacity):
                raise GameError('CONFIG_VERIFICATION_FAILED')
            market=markets[key]
            if market.stock>row['capacity']:raise GameError('CONFIG_VERIFICATION_FAILED')
            market.production_rate=row['production_rate'];market.capacity=row['capacity']
        extra=c.execute('SELECT state_json FROM phase3_state WHERE season_id=?',(sid,)).fetchone()
        state=json.loads(extra[0]) if extra else {}
        return World(sid, season["game_time"], players, markets, routes, clock[0], developments,event_clock[0],event_clock[1],active,phase3_state=state)

    def _save(self, world):
        c = self.connection
        sid = world.season_id
        if self.catalog.phase3 is not None:
            c.execute('INSERT INTO phase3_state VALUES (?,?) ON CONFLICT(season_id) DO UPDATE SET state_json=excluded.state_json',(sid,json.dumps(world.phase3_state,ensure_ascii=False)))
        c.execute("UPDATE event_clock SET last_slot=? WHERE season_id=?",(world.event_slot,sid))
        for e in world.pending_events:
            c.execute("INSERT INTO market_event_history VALUES (NULL,?,?,?,?,?,?,?,?)",(sid,e["slot"],e["planet_id"],e["goods_id"],e["kind"],e["delta"],e["starts_at"],e["ends_at"]))
        c.execute("UPDATE seasons SET game_time=? WHERE id=?", (world.game_time, sid))
        c.execute("UPDATE economy_clock SET updated_at=? WHERE season_id=?",(world.economy_time,sid))
        c.executemany("UPDATE planet_development SET progress=? WHERE season_id=? AND planet_id=? AND industry=?",
                      [(v,sid,p,k) for (p,k),v in world.developments.items()])
        c.executemany('UPDATE industry_periods SET production_rate=?,capacity=? WHERE season_id=? AND planet_id=? AND goods_id=?',
                      [(m.production_rate,m.capacity,sid,*key) for key,m in world.markets.items() if m.capacity is not None])
        for p in world.players.values():
            c.execute("INSERT INTO players VALUES (?,?) ON CONFLICT(id) DO UPDATE SET handle=excluded.handle", (p.id, p.handle))
            c.execute("""INSERT INTO player_state VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(season_id,player_id) DO UPDATE SET cash=excluded.cash,ship_id=excluded.ship_id,
                planet_id=excluded.planet_id,destination_id=excluded.destination_id,arrival_at=excluded.arrival_at""",
                      (sid, p.id, p.cash, p.ship_id, p.planet_id, p.destination_id, p.arrival_at))
            if not c.execute("SELECT 1 FROM bbs_accounts WHERE player_id=?", (p.id,)).fetchone():
                c.execute("INSERT INTO bbs_accounts VALUES ('local',?,?)", (p.id,p.id))
            c.execute("DELETE FROM cargo WHERE season_id=? AND player_id=?", (sid, p.id))
            c.executemany("INSERT INTO cargo VALUES (?,?,?,?)", [(sid, p.id, g, q) for g, q in p.cargo.items()])
        from .phase4_db import save_exploration
        save_exploration(c,world)
        c.executemany("UPDATE markets SET price=?,stock=? WHERE season_id=? AND planet_id=? AND goods_id=?",
                      [(m.price, m.stock, sid, planet, good) for (planet, good), m in world.markets.items()])
        c.executemany("UPDATE routes SET is_open=? WHERE season_id=? AND id=?",
                      [(r["is_open"], sid, key) for key, r in world.routes.items()])

    def close(self):
        self.connection.close()
