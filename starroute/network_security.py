"""Master-owned site registry and authenticated configuration evidence.

Provisioning is an administrator operation, never a player API. A thin BBS has
no engine rules; its approved compatibility descriptor is signed by the master.
"""
import hashlib,hmac,json,secrets
from .rules import canonical_bytes,fingerprint
from .catalog import identifier,display_name
from .model import GameError

PROTOCOL=1
CONFIG_FIELDS=('rules_version','config_schema_version','game_rules_hash','universe_id','round_id','protocol','client_version')


def digest(token):return hashlib.sha256(token.encode()).hexdigest()


def seal(key,value):return {'value':value,'mac':hmac.new(key,canonical_bytes(value),hashlib.sha256).hexdigest()}


def verified(key,envelope):
    if not isinstance(envelope,dict) or set(envelope)!={'value','mac'}:raise GameError('CONFIG_VERIFICATION_FAILED')
    expected=seal(key,envelope['value'])['mac']
    if not isinstance(envelope['mac'],str) or not hmac.compare_digest(envelope['mac'],expected):raise GameError('CONFIG_VERIFICATION_FAILED')
    return envelope['value']


def schema(c):
    for sql in (
        '''CREATE TABLE IF NOT EXISTS p5_sites(bbs_id TEXT PRIMARY KEY,name TEXT NOT NULL,credential_hash TEXT NOT NULL,
           state TEXT NOT NULL CHECK(state IN ('ENABLED','DISABLED','LEFT')),approved TEXT NOT NULL,verified_config TEXT,
           verified_at INTEGER,created_at INTEGER NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS p5_sessions(token_hash TEXT PRIMARY KEY,bbs_id TEXT NOT NULL REFERENCES p5_sites(bbs_id),
           user_id TEXT NOT NULL,display_name TEXT NOT NULL,session_id TEXT NOT NULL,last_seen INTEGER NOT NULL,
           universe_id TEXT NOT NULL,round_id INTEGER NOT NULL,UNIQUE(bbs_id,user_id,session_id))''',
        '''CREATE TABLE IF NOT EXISTS p5_audit(sequence INTEGER PRIMARY KEY,at INTEGER NOT NULL,bbs_id TEXT,user_id TEXT,
           action TEXT NOT NULL,code TEXT NOT NULL,details TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS p5_references(universe_id TEXT NOT NULL,round_id INTEGER NOT NULL,reference_json TEXT NOT NULL,
           PRIMARY KEY(universe_id,round_id))''',
    ):c.execute(sql)
    c.execute("INSERT OR IGNORE INTO metadata VALUES('network_schema_version','1')")


def effective(repo):
    r=repo.connection.execute("SELECT * FROM p4_rounds WHERE state='ACTIVE'").fetchone()
    if not r:raise GameError('ROUND_NOT_ACTIVE')
    f=fingerprint(repo.catalog)
    from .phase4_db import policy_hash
    actual=hashlib.sha256(canonical_bytes({'engine':f['sha256'],'round':policy_hash(json.loads(r['policy_json']))})).hexdigest()
    if actual!=r['configuration_hash']:raise GameError('CONFIG_VERIFICATION_FAILED')
    return dict(rules_version=f['rules_version'],config_schema_version=f['config_schema_version'],
                game_rules_hash=r['configuration_hash'],universe_id=r['universe_id'],round_id=r['round_id'],protocol=PROTOCOL,client_version=1)


def publish(repo,key):
    value=effective(repo);signed=seal(key,value)
    repo.connection.execute('INSERT INTO p5_references VALUES(?,?,?) ON CONFLICT(universe_id,round_id) DO UPDATE SET reference_json=excluded.reference_json',
                            (value['universe_id'],value['round_id'],json.dumps(signed)))
    return signed


def reference(repo,key):
    value=effective(repo)
    row=repo.connection.execute('SELECT reference_json FROM p5_references WHERE universe_id=? AND round_id=?',(value['universe_id'],value['round_id'])).fetchone()
    if not row:raise GameError('REFERENCE_CONFIG_UNAVAILABLE')
    try:trusted=verified(key,json.loads(row[0]))
    except (ValueError,GameError):raise GameError('CONFIG_VERIFICATION_FAILED') from None
    if canonical_bytes(trusted)!=canonical_bytes(value):raise GameError('CONFIG_VERIFICATION_FAILED')
    return trusted


def audit(c,now,site,user,action,code,details=None):
    c.execute('INSERT INTO p5_audit VALUES(NULL,?,?,?,?,?,?)',(now,site,user,action,code,json.dumps(details or {},sort_keys=True)))


def provision(repo,key,bbs_id,name,now,claim=None):
    identifier(bbs_id);display_name(name)
    if bbs_id=='local':raise GameError('RESERVED_NAMESPACE')
    claim=reference(repo,key) if claim is None else claim
    if set(claim)!=set(CONFIG_FIELDS):raise GameError('CONFIG_VERIFICATION_FAILED')
    envelope=seal(key,dict(bbs_id=bbs_id,configuration=claim));token=secrets.token_urlsafe(32)
    repo.connection.execute('INSERT INTO p5_sites VALUES(?,?,?,\'ENABLED\',?,NULL,NULL,?)',(bbs_id,name,digest(token),json.dumps(envelope),now))
    audit(repo.connection,now,bbs_id,None,'site_register','OK')
    return dict(bbs_id=bbs_id,credential=token,attestation=envelope,configuration=claim)


def authenticate(c,token):
    if not isinstance(token,str) or len(token)>256:raise GameError('AUTH_FAILED')
    r=c.execute('SELECT * FROM p5_sites WHERE credential_hash=?',(digest(token),)).fetchone()
    if not r or r['state']!='ENABLED':raise GameError('AUTH_FAILED')
    return r


def assess(repo,key,site,attestation,observed,now,peer=None):
    ref=reference(repo,key);value=verified(key,attestation)
    if value.get('bbs_id')!=site['bbs_id'] or attestation!=json.loads(site['approved']):raise GameError('CONFIG_VERIFICATION_FAILED')
    if canonical_bytes(value.get('configuration'))!=canonical_bytes(observed):raise GameError('CONFIG_VERIFICATION_FAILED')
    differences=[k for k in CONFIG_FIELDS if canonical_bytes(observed.get(k))!=canonical_bytes(ref[k])]
    repo.connection.execute('UPDATE p5_sites SET verified_config=?,verified_at=? WHERE bbs_id=?',(json.dumps(observed),now,site['bbs_id']))
    remote=None;remote_diff=[];observed_peer=None
    if peer:
        r=repo.connection.execute('SELECT * FROM p5_sites WHERE bbs_id=?',(peer,)).fetchone()
        if r and r['state']=='ENABLED' and r['verified_config'] and now-r['verified_at']<=300:
            approved=verified(key,json.loads(r['approved']))
            observed_peer=json.loads(r['verified_config'])
            if canonical_bytes(approved['configuration'])==canonical_bytes(observed_peer):
                remote_diff=[k for k in CONFIG_FIELDS if canonical_bytes(observed_peer.get(k))!=canonical_bytes(ref[k])];remote=not remote_diff
    local=not differences
    code=('CONFIG_VERIFICATION_FAILED' if peer and remote is None else 'BOTH_CONFIG_MISMATCH' if not local and remote is False else 'LOCAL_CONFIG_MISMATCH' if not local else
          'REMOTE_CONFIG_MISMATCH' if remote is False else 'CONFIG_VERIFICATION_FAILED' if peer and remote is None else 'OK')
    result=dict(code=code,local='normal' if local else 'mismatch',remote='normal' if remote else 'mismatch' if remote is False else 'not_requested' if not peer else 'unavailable',
                local_fields=differences,remote_fields=remote_diff,reference=ref,local_configuration=observed,remote_configuration=observed_peer)
    audit(repo.connection,now,site['bbs_id'],None,'configuration',code,result)
    return result


def session(c,token,now,ttl):
    if not isinstance(token,str):raise GameError('AUTH_FAILED')
    row=c.execute('SELECT s.*,b.state FROM p5_sessions s JOIN p5_sites b ON b.bbs_id=s.bbs_id WHERE token_hash=?',(digest(token),)).fetchone()
    if not row or row['state']!='ENABLED' or now-row['last_seen']>ttl:raise GameError('SESSION_EXPIRED')
    return row
