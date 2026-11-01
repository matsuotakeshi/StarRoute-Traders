"""Administrator-only registry and atomic round lifecycle. No network server."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import uuid
import zlib
from .repository import SQLiteRepository
from .universe_package import to_catalog
from .rules import canonical_bytes,fingerprint
from .phase4_db import policy,policy_hash
from .engine import Engine
from .model import GameError,integer
from .statistics import calculate,rankings,read_scores

# Explicit allowlist: identities and historical management data never get reset.
GAME_TABLES=('seasons','ships','planets','goods','player_state','cargo','markets','routes',
 'operation_history','ship_grades','ship_profiles','navigation_policy','voyages','world_identity',
 'economy_clock','trade_ledger','planet_development','investment_records','event_clock',
 'market_event_history','industry_periods','phase3_state')


def initialize(path,now=0):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    r=SQLiteRepository(path,now=now)
    try:r.connection.execute("INSERT INTO metadata VALUES ('phase4_managed','1')")
    finally:r.close()


def restore_copy(source,destination):
    """Recover to a NEW isolated DB; never roll back an operating database."""
    source=Path(source).resolve(strict=True)
    c=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
    try:
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or c.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('invalid recovery source')
        fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        out=sqlite3.connect(destination)
        try:
            c.backup(out)
            if out.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or out.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('restored integrity failure')
        finally:out.close()
    finally:c.close()
    return {'state':'isolated_recovery_copy','destination':str(destination),'activation':'not_performed'}


class Manager:
    def __init__(self,path,now,failpoint=None):
        if not Path(path).is_file():raise ValueError('existing management DB required')
        self.path=str(path);self.now=integer(now);self.failpoint=failpoint or (lambda name:None)
        self.repo=SQLiteRepository(path);self.c=self.repo.connection
        if not self.c.execute("SELECT 1 FROM metadata WHERE key='phase4_managed'").fetchone():
            self.repo.close();raise ValueError('legacy DB is not an operational registry; initialize a separate DB')

    def close(self):self.repo.close()

    @contextmanager
    def atomic(self):
        self.c.execute('BEGIN IMMEDIATE')
        try:
            if self.c.execute("SELECT value FROM metadata WHERE key='catalog'").fetchone()[0]!=self.repo.catalog.canonical():raise ValueError('WORLD_CHANGED; reopen administrator connection')
            self.c.execute('PRAGMA defer_foreign_keys=ON')
            yield
            if self.c.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('foreign key integrity')
            self.c.commit()
        except BaseException:self.c.rollback();raise

    def audit(self,action,uid=None,rid=None,details=None):
        self.c.execute('INSERT INTO p4_audit VALUES(NULL,?,?,?,?,?)',(self.now,action,uid,rid,json.dumps(details or {},sort_keys=True)))

    def backup(self,label):
        directory=Path(self.path+'.backups');directory.mkdir(mode=0o700,exist_ok=True)
        target=directory/(str(self.now)+'-'+label+'-'+uuid.uuid4().hex+'.sqlite3')
        fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        dst=sqlite3.connect(target)
        try:
            self.c.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or dst.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('backup integrity')
        finally:dst.close()
        return str(target)

    def stage(self,raw,source=None):
        if len(raw)>32*1024*1024:raise ValueError('package size')
        p=json.loads(raw);uid=str(uuid.UUID(p['metadata']['universe_id']))
        h=hashlib.sha256(canonical_bytes(p)).hexdigest();m=p['metadata']
        source=source or {'source_type':'Local','verification':{'status':'trusted_local','method':'operator-local-import'}}
        if source['source_type']!='Local' and source['verification'].get('status')!='verified':raise ValueError('authenticated source required')
        with self.atomic():
            old=self.c.execute('SELECT package_hash,state FROM p4_universes WHERE universe_id=?',(uid,)).fetchone()
            if old:
                if old['package_hash']!=h:raise ValueError('UNIVERSE_ID_CONFLICT')
                return uid
            self.c.execute('INSERT INTO p4_universes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL)',
                (uid,'STAGED',canonical_bytes(p).decode(),h,m['universe_data_version'],m['generator_version'],p['schema_version'],
                 m['game_rules_version'],'',source['source_type'],source.get('repository_id'),source.get('commit_id'),json.dumps(source['verification'])))
            self.audit('STAGED',uid);self.failpoint('stage')
        return uid

    def item(self,uid):
        r=self.c.execute('SELECT * FROM p4_universes WHERE universe_id=?',(uid,)).fetchone()
        if not r:raise ValueError('universe not registered')
        return dict(r)

    def validate(self,uid):
        with self.atomic():
            r=self.item(uid);p=json.loads(r['package_json'])
            if hashlib.sha256(canonical_bytes(p)).hexdigest()!=r['package_hash']:raise ValueError('stored package changed')
            catalog=to_catalog(p)
            params=catalog.data['universe']['parameters']
            if params.get('width')!=240 or params.get('height')!=120:raise ValueError('Phase 4 requires 240 x 120 universe')
            proof=json.loads(r['verification_json'])
            if proof['status'] not in ('verified','trusted_local'):raise ValueError('source not verified')
            self.failpoint('validate')
            if r['state']=='STAGED':
                self.c.execute("UPDATE p4_universes SET state='VALIDATED',configuration_hash=? WHERE universe_id=?",(fingerprint(catalog)['sha256'],uid))
                self.audit('VALIDATED',uid)
        return catalog

    def register(self,uid):
        self.validate(uid);self.backup('register')
        with self.atomic():
            r=self.item(uid)
            if r['state']=='VALIDATED':
                self.c.execute("UPDATE p4_universes SET state='REGISTERED',registered_at=? WHERE universe_id=?",(self.now,uid))
                self.audit('REGISTERED',uid);self.failpoint('register')
            elif r['state'] not in ('REGISTERED','ACTIVE','ARCHIVED'):raise ValueError('invalid registration state')
        return uid

    def prepare(self,uid,rid,start,settings=None):
        integer(rid,1);integer(start);settings=policy(settings);self.validate(uid)
        with self.atomic():
            r=self.item(uid);existing=self.c.execute('SELECT * FROM p4_rounds WHERE round_id=?',(rid,)).fetchone()
            expected=(uid,start,start+settings['round_seconds'],canonical_bytes(settings).decode())
            if existing:
                if tuple(existing[k] for k in ('universe_id','starts_at','ends_at','policy_json'))!=expected:raise ValueError('ROUND_CONFLICT')
                return rid
            if r['state']!='REGISTERED':raise ValueError('registered unused universe required')
            composite=hashlib.sha256(canonical_bytes({'engine':r['configuration_hash'],'round':policy_hash(settings)})).hexdigest()
            self.c.execute("INSERT INTO p4_rounds VALUES(?,?,'PREPARED',?,?,NULL,0,0,?,?)",(rid,*expected,composite))
            self.audit('PREPARED',uid,rid)
        return rid

    def _archive(self,rid,uid):
        snapshot={'catalog':self.c.execute("SELECT value FROM metadata WHERE key='catalog'").fetchone()[0],
                  'tables':{t:[dict(r) for r in self.c.execute('SELECT * FROM '+t)] for t in GAME_TABLES+('players','bbs_accounts','preferences')}}
        raw=canonical_bytes(snapshot)
        self.c.execute('INSERT INTO p4_archives VALUES(?,?,?,?,?)',(rid,uid,zlib.compress(raw),hashlib.sha256(raw).hexdigest(),self.now))

    def _finish(self,rid,uid):
        r=self.c.execute('SELECT * FROM p4_rounds WHERE round_id=? AND universe_id=?',(rid,uid)).fetchone()
        if not r:raise ValueError('round/universe mismatch')
        if r['state'] in ('CLOSED','ARCHIVED'):return
        if r['state']!='ACTIVE':raise ValueError('active round required')
        self.c.execute("UPDATE p4_rounds SET state='CLOSING' WHERE round_id=?",(rid,));self.audit('CLOSING',uid,rid)
        world=self.repo._load();engine=Engine(self.repo.catalog);cutoff=min(self.now,r['ends_at'])
        if cutoff<world.game_time:raise ValueError('cannot close before committed game time')
        # Bounded catch-up chunks retain deterministic events and arrivals at cutoff.
        while world.game_time<cutoff:
            prior=world.game_time;engine.update(world,cutoff,partial=True)
            if world.game_time<=prior:raise ValueError('clock did not advance')
        self.repo._save(world)
        scores=calculate(self.c,rid,json.loads(r['policy_json']));self.failpoint('statistics')
        for pid,s in scores.items():self.c.execute('INSERT INTO p4_statistics VALUES(?,?,?)',(rid,pid,json.dumps(s,sort_keys=True)))
        for row in rankings(scores,json.loads(r['policy_json'])):
            values=tuple(row[k] for k in ('category','rank','player_id','bbs_id','user_id','display_name','score'))
            self.c.execute('INSERT INTO p4_rankings VALUES(?,?,?,?,?,?,?,?,?)',(rid,*values,row['evaluation']))
            if row['rank']<=3:self.c.execute('INSERT INTO p4_hall VALUES(?,?,?,?,?,?,?,?,?,?,?)',(rid,uid,*values,cutoff,row['evaluation']))
        self.failpoint('hall');self._archive(rid,uid)
        self.c.execute("UPDATE seasons SET status='closed' WHERE id=?",(rid,))
        self.c.execute("UPDATE p4_rounds SET state='CLOSED',closed_at=?,finalized=1,hall_saved=1 WHERE round_id=?",(cutoff,rid))
        self.c.execute("UPDATE p4_universes SET state='ARCHIVED',archived_at=? WHERE universe_id=?",(self.now,uid))
        self.audit('CLOSED',uid,rid)
        self.audit('UNIVERSE_ARCHIVED',uid,rid)

    def finish(self,rid,uid):
        self.backup('close')
        with self.atomic():self._finish(rid,uid)

    def activate(self,rid,uid,previous_round=None,previous_universe=None):
        catalog=self.validate(uid);self.backup('activate')
        # Prepare all initial data off-line, before acquiring the operational write lock.
        roundrow=self.c.execute('SELECT * FROM p4_rounds WHERE round_id=? AND universe_id=?',(rid,uid)).fetchone()
        if not roundrow:raise ValueError('round/universe mismatch')
        if self.now<roundrow['starts_at'] or self.now>=roundrow['ends_at']:raise ValueError('activation outside round')
        with tempfile.TemporaryDirectory(prefix='srt-seed-') as td:
            seed=SQLiteRepository(Path(td)/'seed.db',catalog,now=roundrow['starts_at'])
            try:rows={t:[dict(r) for r in seed.connection.execute('SELECT * FROM '+t)] for t in GAME_TABLES}
            finally:seed.close()
        oldcatalog=self.repo.catalog
        try:
            with self.atomic():
                current=self.c.execute('SELECT * FROM p4_rounds WHERE round_id=?',(rid,)).fetchone()
                if current['state']=='ACTIVE':return
                if current['state']!='PREPARED':raise ValueError('prepared round required')
                old=self.c.execute("SELECT * FROM p4_rounds WHERE state='ACTIVE'").fetchone()
                if old:
                    if (old['round_id'],old['universe_id'])!=(previous_round,previous_universe):raise ValueError('explicit previous round/universe required')
                    self._finish(previous_round,previous_universe)
                for finished in self.c.execute("SELECT round_id,universe_id FROM p4_rounds WHERE state='CLOSED'").fetchall():
                    self.c.execute("UPDATE p4_rounds SET state='ARCHIVED' WHERE round_id=?",(finished['round_id'],))
                    self.audit('ROUND_ARCHIVED',finished['universe_id'],finished['round_id'])
                identities=self.c.execute('SELECT * FROM players').fetchall()
                for table in reversed(GAME_TABLES):self.c.execute('DELETE FROM '+table)
                for table in GAME_TABLES:
                    for row in rows[table]:
                        if 'season_id' in row:row['season_id']=rid
                        if table=='seasons':row['id']=rid
                        if table=='world_identity':row['world_id']=uid
                        self.c.execute('INSERT INTO '+table+'('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
                self.c.execute("UPDATE metadata SET value=? WHERE key='catalog'",(catalog.canonical(),))
                self.repo.catalog=catalog;world=self.repo._load();engine=Engine(catalog)
                for p in identities:engine.create_player(world,p['id'],p['handle'])
                self.repo._save(world);self.failpoint('activate')
                self.c.execute("UPDATE p4_universes SET state='ACTIVE',activated_at=? WHERE universe_id=?",(self.now,uid))
                self.c.execute("UPDATE p4_rounds SET state='ACTIVE' WHERE round_id=?",(rid,))
                self.audit('ACTIVE',uid,rid)
        except BaseException:self.repo.catalog=oldcatalog;raise
        self.repo.world_id=uid

    def inspect(self):
        return {'integrity':[r[0] for r in self.c.execute('PRAGMA integrity_check')],
                'foreign_keys':[tuple(r) for r in self.c.execute('PRAGMA foreign_key_check')],
                'rounds':[dict(r) for r in self.c.execute('SELECT * FROM p4_rounds ORDER BY round_id')],
                'recovery':'SQLite transactions roll back incomplete operations; retry with identical IDs; never restore over committed new-round operations'}

    def archive(self,rid):
        r=self.c.execute('SELECT * FROM p4_archives WHERE round_id=?',(rid,)).fetchone()
        if not r:raise ValueError('archive not found')
        raw=zlib.decompress(r['snapshot'])
        if hashlib.sha256(raw).hexdigest()!=r['sha256']:raise ValueError('archive corruption')
        return json.loads(raw)
