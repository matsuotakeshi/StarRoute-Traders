#!/bin/sh
# StarRoute v0.21.0 standalone: prepare completely, then switch configuration.
# Run as root: /bin/sh starroute-new-universe.sh --writers-stopped
set -eu
umask 077
if [ "$#" -ne 1 ] || [ "$1" != --writers-stopped ]; then
    echo 'Usage: /bin/sh starroute-new-universe.sh --writers-stopped' >&2
    echo 'First stop scheduled game updates and ask all game users to exit.' >&2
    exit 2
fi
ADMIN=/usr/local/bin/starroute-admin
test -x "$ADMIN"
PY=$(sed -n '1s/^#!//p' "$ADMIN" | awk '{print $1}')
case "$PY" in /usr/local/bin/python3*) ;; *) echo 'Unexpected package Python' >&2; exit 1;; esac
test -x "$PY"
exec "$PY" -I - <<'PYTHON'
import fcntl
import hashlib
import json
import os
import pwd
import re
import secrets
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

STATE = Path('/var/db/starroute-traders')
CONFIG = Path('/usr/local/etc/starroute-traders')
CFG = CONFIG / 'door.json'
DOOR = Path('/usr/local/libexec/liner-notes/starroute-door')
DOORS = Path('/usr/local/etc/liner-notes/doors.conf')
BACKUP_PARENT = Path('/root')
LOCK = Path('/var/run/starroute-new-universe.lock')
EXAMPLES = Path('/usr/local/share/examples/starroute-traders')
LIB = Path('/usr/local/libexec/starroute-traders')
BIN = Path('/usr/local/bin')
SPEEDUP = 60
ROUND_DAYS = 30

def checkpoint(name):
    """Fault-injection seam for isolated tests; no production environment override."""
    pass

def note(message):
    print(message, flush=True)

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())

def digest(path):
    with Path(path).open('rb') as stream:
        return stream_digest(stream)

def stream_digest(stream):
    h = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        h.update(chunk)
    return h.hexdigest()

def regular(path):
    if not stat.S_ISREG(Path(path).lstat().st_mode):
        raise RuntimeError('Not a regular file: ' + str(path))

def no_links_tree(path):
    if Path(path).is_symlink():
        raise RuntimeError('Symlink not supported: ' + str(path))
    for base, dirs, files in os.walk(path):
        for name in dirs + files:
            p = Path(base) / name
            mode = p.lstat().st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise RuntimeError('Special file/symlink not supported: ' + str(p))

def active_writers():
    result = subprocess.run(['ps', '-axo', 'pid=,command='],
                            check=True, capture_output=True, text=True)
    pattern = re.compile(r'starroute-(?:door|master|admin|maintain|sites)(?:\s|$)|'
                         r'starroute_bbs\.door|starroute\.(?:master|admin|network_admin)|'
                         r'scheduled_backup\.py|\bstarroute\s.*\btick\b')
    found = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2 and int(fields[0]) != os.getpid() and pattern.search(fields[1]):
            found.append(int(fields[0]))
    if found:
        raise RuntimeError('Game/maintenance processes still running; PIDs: ' + ','.join(map(str, found)))

def run(tool, arguments, backup, label):
    result = subprocess.run([str(BIN / tool), *map(str, arguments)],
                            capture_output=True, text=True, encoding='utf-8', timeout=300)
    # Private administrator logs only; never print captured process output.
    (backup / (label + '.log')).write_text(result.stdout + '\n' + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(label + ' failed; inspect the private backup log')
    return json.loads(result.stdout)

def prerequisites():
    if os.geteuid() != 0 or not sys.platform.startswith('freebsd'):
        raise RuntimeError('Run on FreeBSD as root')
    account = pwd.getpwnam('liner_notes')
    for p in (CFG, DOOR, DOORS, EXAMPLES / 'release-world.json',
              EXAMPLES / 'connected-universe-trial.json', EXAMPLES / 'industry-levels-trial.json',
              LIB / 'starroute/config/phase4.json'):
        regular(p)
    if not os.access(DOOR, os.X_OK):
        raise RuntimeError('Door is already disabled; investigate before starting another reset')
    for tool in ('starroute-admin', 'starroute-maintain', 'starroute-sites', 'starroute-universe'):
        regular(BIN / tool)
        if not os.access(BIN / tool, os.X_OK):
            raise RuntimeError('Missing executable: ' + tool)
    for package in ('starroute-traders', 'starroute-traders-client'):
        version = subprocess.check_output(['pkg', 'query', '%v', package], text=True).strip()
        if version != '0.21.0':
            raise RuntimeError('This script requires installed v0.21.0 packages')
    no_links_tree(STATE)
    no_links_tree(CONFIG)
    return account.pw_uid, account.pw_gid

def validate_new(new, uid, config, backup):
    run('starroute-admin', ['--db', new/'game.db', 'check'], backup, 'new-admin-check')
    run('starroute-maintain', ['--db', new/'game.db', 'check'], backup, 'new-db-check')
    assert len(read_json(new/'universe.json')['world']['planets']) == 48
    connection = sqlite3.connect((new/'game.db').as_uri() + '?mode=ro', uri=True)
    try:
        assert connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
        row = connection.execute("SELECT universe_id, ends_at-starts_at FROM p4_rounds WHERE state='ACTIVE'").fetchall()
        assert row == [(uid, ROUND_DAYS * 86400)]
        assert connection.execute('SELECT COUNT(*) FROM player_state').fetchone()[0] == 0
        assert connection.execute('SELECT COUNT(*) FROM planets').fetchone()[0] == 49
    finally:
        connection.close()
    # Verify the real standalone connection handshake without creating a player/session.
    sys.path.insert(0, str(LIB))
    from starroute.network import Gateway
    profile = read_json(new/'site-profile.json')
    gateway = Gateway(str(new/'game.db'), (new/'reference.key').read_bytes())
    reply = gateway.dispatch('connect', profile['credential'],
                             {'attestation': profile['attestation'], 'configuration': profile['configuration']})
    if not reply.get('admitted'):
        raise RuntimeError('New standalone profile was not admitted')

def perform(owner):
    original = CFG.read_bytes()
    cfg_stat = CFG.stat()
    config = json.loads(original)
    if config.get('mode') != 'standalone':
        raise RuntimeError('Only standalone mode is supported')
    for field in ('database', 'reference_key', 'profile'):
        p = Path(config[field])
        regular(p)
        if not p.is_absolute() or not p.resolve().is_relative_to(STATE.resolve()):
            raise RuntimeError('Existing state path is outside the expected state directory')
    old_profile = read_json(config['profile'])
    bbs_id = old_profile['bbs_id']
    if not isinstance(bbs_id, str) or not bbs_id:
        raise RuntimeError('Invalid existing BBS identity')
    active_writers()
    total = sum(p.stat().st_size for p in STATE.rglob('*') if p.is_file())
    if shutil.disk_usage(BACKUP_PARENT).free < total * 2 + 128*1024*1024:
        raise RuntimeError('Insufficient backup space')
    if shutil.disk_usage(STATE).free < 128*1024*1024:
        raise RuntimeError('Insufficient new-world space')
    backup = Path(tempfile.mkdtemp(prefix='starroute-reset-backup.', dir=BACKUP_PARENT))
    os.chmod(backup, 0o700)
    note('Private backup: ' + str(backup))
    shutil.copy2(DOOR, backup/'starroute-door.before')
    shutil.copy2(DOORS, backup/'doors.conf.before')
    shutil.copy2(CFG, backup/'door.json.before')
    write_json(backup/'original-mode.json', {'door_mode': stat.S_IMODE(DOOR.stat().st_mode)})
    doors_hash = digest(DOORS)
    # Leave the Door closed on BOTH failure and success. Operator reopens after review.
    DOOR.chmod(0o644)
    active_writers()
    checkpoint('door_closed')
    run('starroute-maintain', ['--db', config['database'], 'backup', '--output', backup/'game.before.db'], backup, 'old-db-backup')
    with tarfile.open(backup/'state-and-config.tar', 'x') as archive:
        archive.add(STATE, arcname='state')
        archive.add(CONFIG, arcname='config')
    # Read every archived regular file back and verify it against the stopped source.
    with tarfile.open(backup/'state-and-config.tar', 'r') as archive:
        for member in archive:
            if member.isfile():
                head, *tail = Path(member.name).parts
                source = (STATE if head == 'state' else CONFIG).joinpath(*tail)
                with archive.extractfile(member) as stream:
                    if stream_digest(stream) != digest(source):
                        raise RuntimeError('Backup verification failed')
    checkpoint('backup_verified')
    new = Path(tempfile.mkdtemp(prefix='world-new.', dir=STATE))
    note('New world (not active in Door): ' + str(new))
    template = read_json(EXAMPLES/'release-world.json')
    for plan in template['navigation']['plans']:
        plan['normal_seconds'] = max(1, (plan['normal_seconds']+SPEEDUP-1)//SPEEDUP)
        for option in plan['warp_options']:
            option['seconds'] = max(1, (option['seconds']+SPEEDUP-1)//SPEEDUP)
    write_json(new/'template.json', template)
    shutil.copyfile(EXAMPLES/'connected-universe-trial.json', new/'generator.json')
    shutil.copyfile(EXAMPLES/'industry-levels-trial.json', new/'levels.json')
    policy = read_json(LIB/'starroute/config/phase4.json')
    policy['round_seconds'] = ROUND_DAYS * 86400
    write_json(new/'round-policy.json', policy)
    generated = run('starroute-universe', ['--template', new/'template.json',
        '--parameters', new/'generator.json', '--levels', new/'levels.json',
        '--seed', secrets.token_hex(32), '--output', new/'universe.json'], backup, 'generate')
    uid = generated['universe_id']
    db = new/'game.db'
    def admin(label, *args):
        return run('starroute-admin', ['--db', db, *args], backup, label)
    admin('init', 'init')
    admin('stage', 'stage', '--package', new/'universe.json')
    admin('validate', 'validate', '--universe', uid)
    admin('register', 'register', '--universe', uid)
    admin('prepare', 'prepare', '--universe', uid, '--round', '1', '--policy', new/'round-policy.json')
    admin('activate', 'activate', '--universe', uid, '--round', '1')
    checkpoint('new_active')
    site_args = ['--db', db, '--reference-key', new/'reference.key']
    run('starroute-sites', [*site_args, 'init'], backup, 'site-init')
    run('starroute-sites', [*site_args, 'add', '--bbs-id', bbs_id, '--name', 'Liner notes',
                          '--output', new/'site-profile.json'], backup, 'site-add')
    config.update(database=str(db), reference_key=str(new/'reference.key'), profile=str(new/'site-profile.json'))
    if 'state_directory' in config:
        (new/'client-state').mkdir(mode=0o700)
        config['state_directory'] = str(new/'client-state')
    validate_new(new, uid, config, backup)
    checkpoint('validated')
    for directory, dirs, files in os.walk(new):
        os.chown(directory, *owner)
        os.chmod(directory, 0o700)
        for name in files:
            p = Path(directory)/name
            regular(p)
            os.chown(p, *owner)
            os.chmod(p, 0o600)
    # Confirm the BBS UID can read the new files and write the state directory.
    pid = os.fork()
    if pid == 0:
        try:
            if os.geteuid() != owner[0]:
                os.setgroups([]); os.setgid(owner[1]); os.setuid(owner[0])
            for p in (db, new/'reference.key', new/'site-profile.json'):
                with p.open('rb') as f: f.read(1)
            probe = new/'.write-check'
            with probe.open('x') as f: f.write('ok')
            probe.unlink()
            os._exit(0)
        except BaseException:
            os._exit(1)
    if os.waitpid(pid, 0)[1] != 0:
        raise RuntimeError('BBS user cannot access the new state')
    active_writers()
    if CFG.read_bytes() != original or digest(DOORS) != doors_hash:
        raise RuntimeError('Configuration changed concurrently; refusing switch')
    prepared = CONFIG/('door.json.prepared-' + secrets.token_hex(8))
    write_json(prepared, config)
    os.chown(prepared, cfg_stat.st_uid, cfg_stat.st_gid)
    os.chmod(prepared, stat.S_IMODE(cfg_stat.st_mode))
    write_json(backup/'prepared.json', {'new_world': str(new), 'universe_id': uid,
        'round_id': 1, 'speedup': SPEEDUP, 'round_days': ROUND_DAYS,
        'old_config_sha256': hashlib.sha256(original).hexdigest(), 'new_config_sha256': digest(prepared)})
    # All fallible validation/logging finishes BEFORE the single configuration commit.
    os.sync()
    checkpoint('before_switch')
    note('Validation complete. Committing Door configuration; Door stays CLOSED.')
    # Do not report an ordinary interrupt as a pre-commit failure after rename.
    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
    os.replace(prepared, CFG)

def main():
    os.umask(0o077)
    def interrupted(signum, frame):
        raise RuntimeError('Interrupted; inspect configuration and backup before reopening')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    fd = None
    try:
        owner = prerequisites()
        fd = os.open(LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        perform(owner)
        return 0
    except Exception as error:
        print('STOP: ' + str(error), file=sys.stderr)
        print('Do not reopen the Door or rerun blindly. Old state is retained; inspect the private backup.', file=sys.stderr)
        return 1
    finally:
        if fd is not None:
            os.close(fd)

if __name__ == '__main__':
    raise SystemExit(main())
PYTHON
