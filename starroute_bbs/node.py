"""Operator-only mode transition journal. Temporary disconnects never invoke it."""
import argparse,json,os,sqlite3,stat,tempfile,time,uuid
from contextlib import contextmanager
from pathlib import Path
from .client import Client,ClientError,save


def read(path):return json.loads(Path(path).read_text(encoding='utf8'))


TERMINAL = ('COMMITTED', 'RECOVERED')


def sync_directory(directory):
    if os.name == 'posix':
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def persist(path, data):
    save(path, data)
    sync_directory(Path(path).parent)


def publish_config(path, data):
    # Keep the installed Door account's access when an administrator does the switch.
    previous = path.stat()
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.node-config-')
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            if os.name == 'posix':
                current = os.fstat(stream.fileno())
                if (current.st_uid, current.st_gid) != (previous.st_uid, previous.st_gid):
                    os.fchown(stream.fileno(), previous.st_uid, previous.st_gid)
                os.fchmod(stream.fileno(), stat.S_IMODE(previous.st_mode))
            os.fsync(stream.fileno())
        os.replace(name, path)
        sync_directory(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def set_gate(config, blocked):
    pending = config.with_suffix('.transition.pending')
    if blocked:
        pending.touch(mode=0o600)
    else:
        # Only marker existence is public. Door users need no access to journal contents.
        config.with_suffix('.transition.ready').touch(mode=0o600)
        sync_directory(config.parent)
        pending.unlink(missing_ok=True)
    sync_directory(config.parent)


def door_config(config):
    config = Path(config)
    def check():
        if config.with_suffix('.transition.pending').exists():
            raise ClientError('TRANSITION_PENDING')
        journal = config.with_suffix('.transition.json')
        if not config.with_suffix('.transition.ready').exists() and journal.exists():
            try:
                if read(journal)['state'] not in TERMINAL:
                    raise ClientError('TRANSITION_PENDING')
            except (OSError, ValueError, KeyError) as error:
                raise ClientError('TRANSITION_PENDING') from error
    check()
    result = read(config)
    check()
    return result


@contextmanager
def operator_lock(config):
    fd = os.open(config.with_suffix('.transition.lock'), os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ClientError('TRANSITION_BUSY') from error
        yield
    finally:
        os.close(fd)


def require_idle(config):
    journal = config.with_suffix('.transition.json')
    if config.with_suffix('.transition.pending').exists() or (journal.exists() and read(journal)['state'] not in TERMINAL):
        raise ClientError('TRANSITION_PENDING')


def record_state(config, record, state):
    record['state'] = state
    persist(config.with_suffix('.transition.json'), record)


def finish(config, record, state):
    record_state(config, record, state)
    set_gate(config, False)
    return {'state': state}


def verify_master(config):
    client = Client(config, 'node-check', 'Node verification')
    reply = client.post('connect', {'attestation': client.profile['attestation'],
                                    'configuration': client.profile['configuration']}, site=True)
    if not reply['admitted']:
        raise ClientError(reply['diagnostic']['code'])


def backup_db(path,dest):
    source=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    fd=os.open(dest,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd);target=sqlite3.connect(dest)
    try:
        source.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or target.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('backup invalid')
    finally:source.close();target.close()


def pause(path,value):
    c=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=rw',uri=True)
    try:
        c.execute('BEGIN IMMEDIATE');c.execute("INSERT INTO metadata VALUES('node_paused',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(value),));c.commit()
    finally:c.close()


def join(config,new_config,failpoint=lambda step:None):
    config = Path(config)
    with operator_lock(config):
        require_idle(config)
        old, new = read(config), read(new_config)
        if old['mode'] != 'standalone' or new['mode'] != 'inter-bbs':
            raise ValueError('explicit standalone to inter-bbs transition required')
        verify_master(new)
        if any(Path(new['state_directory']).rglob('pending.json')):
            raise ClientError('OPERATION_UNCERTAIN')
        directory = config.parent/('transition-'+uuid.uuid4().hex)
        directory.mkdir(mode=0o700)
        record = {'format': 2, 'kind': 'JOIN', 'old': old, 'new': new, 'backup': str(directory), 'at': int(time.time())}
        record_state(config, record, 'PREPARED')
        set_gate(config, True)
        pause(old['database'], 1)
        failpoint('paused')
        backup_db(old['database'], directory/'standalone-backup.db')
        persist(directory/'previous-config.json', old)
        record_state(config, record, 'PUBLISHING')
        failpoint('publishing')
        publish_config(config, new)
        failpoint('published')
        result = finish(config, record, 'COMMITTED')
        return {**result, 'backup': str(directory)}


def recover(config):
    config = Path(config)
    with operator_lock(config):
        record = read(config.with_suffix('.transition.json'))
        state = record['state']
        if state in TERMINAL:
            expected = record['new'] if state == 'COMMITTED' else record['old']
            if read(config) != expected:
                set_gate(config, True)
                raise ClientError('TRANSITION_UNCERTAIN')
            set_gate(config, False)
            return {'state': state}
        set_gate(config, True)
        old, new = record['old'], record['new']
        if record['kind'] == 'JOIN':
            pause(old['database'], 1)
            current = read(config)
            if state == 'PREPARED' and current == old and record.get('format') == 2:
                pause(old['database'], 0)
                return finish(config, record, 'RECOVERED')
            if (state not in ('PREPARED', 'PUBLISHING') or current not in (old, new)
                    or (current == old and state != 'PUBLISHING')):
                raise ClientError('TRANSITION_UNCERTAIN')
            # A published legacy JOIN or durable publication intent is forward-only.
            verify_master(new)
            if current != new:
                publish_config(config, new)
            return finish(config, record, 'COMMITTED')
        if record['kind'] == 'LEAVE' and state in ('PREPARED', 'MASTER_LEFT') and read(config) in (old, new):
            return complete_leave(config, record)
        raise ClientError('TRANSITION_UNCERTAIN')


def settle(config,client):
    import hashlib
    for pending in Path(config['state_directory']).rglob('pending.json'):
        owner=read(pending.parent/'owner.json');operation=read(pending)
        if owner['bbs_id']!=client.profile['bbs_id']:raise ClientError('INVALID_PENDING_OWNER')
        result=client.post('site-result',{'user_id':owner['user_id'],**{k:operation[k] for k in ('universe_id','round_id','operation','request_id')}},site=True)
        save(pending.with_name('departure-result-'+operation['request_id']+'.json'),{'operation':operation,'status':result['status'],
             'receipt_sha256':hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()})
        pending.unlink()


def leave(config,local_config):
    config = Path(config)
    with operator_lock(config):
        require_idle(config)
        return prepare_leave(config, read(config), read(local_config))


def prepare_leave(config, old, new):
    if old['mode']!='inter-bbs' or new['mode']!='standalone':raise ValueError('explicit inter-bbs to standalone transition required')
    # New local universe must be generated/imported separately before irreversible leave.
    c=sqlite3.connect(Path(new['database']).resolve().as_uri()+'?mode=ro',uri=True)
    try:
        row=c.execute("SELECT universe_id FROM p4_rounds WHERE state='ACTIVE'").fetchone()
        if not row or c.execute('SELECT count(*) FROM players').fetchone()[0]:raise ValueError('fresh activated local universe required')
        profile=read(old['profile'])
        if row[0]==profile['configuration']['universe_id']:raise ValueError('new universe required')
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('local integrity')
    finally:c.close()
    record={'state':'PREPARED','kind':'LEAVE','old':old,'new':new,'at':int(time.time())}
    persist(config.with_name(config.name+'.before-leave-'+uuid.uuid4().hex),old)
    record_state(config, record, 'PREPARED')
    set_gate(config, True)
    return complete_leave(config, record)


def complete_leave(config, record):
    old = record['old']
    client = Client(old, 'node-check', 'Node verification')
    client.post('leave', {**client.target(), 'confirm_bbs_id': client.profile['bbs_id']}, site=True)
    record_state(config, record, 'MASTER_LEFT')
    settle(old, client)
    publish_config(config, record['new'])
    return finish(config, record, 'COMMITTED')


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('recover')
    for cmd in ('join','leave'):s=sub.add_parser(cmd);s.add_argument('--new-config',required=True)
    a=p.parse_args();result=recover(a.config) if a.command=='recover' else join(a.config,a.new_config) if a.command=='join' else leave(a.config,a.new_config)
    print(json.dumps(result))


if __name__=='__main__':main()
