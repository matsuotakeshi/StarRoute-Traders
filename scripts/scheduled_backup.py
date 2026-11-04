#!/usr/bin/env python3
"""Private SQLite snapshots; no live restore, service control or cron installation."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import time
import uuid


FORMAT = 'starroute-scheduled-backup-1'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def safe_path(path):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('symlinks are not supported')
    return path


def private_dir(path):
    safe_path(path)
    if not path.exists():
        path.mkdir(mode=0o700, parents=True)
    if not path.is_dir():
        raise ValueError('not a directory')
    if os.name != 'nt' and (stat.S_IMODE(path.stat().st_mode) & 0o077):
        raise ValueError('backup directory must have mode 0700')
    if os.name != 'nt' and path.stat().st_uid != os.geteuid():
        raise ValueError('backup directory must be owned by the executing user')


def write_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        os.chmod(path, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def sync_dir(path):
    if os.name != 'nt':
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


@contextmanager
def locked(root):
    path = safe_path(root / '.backup.lock')
    with path.open('a+b') as stream:
        os.chmod(path, 0o600)
        if os.name == 'nt':
            import msvcrt
            stream.seek(0)
            stream.write(b'0')
            stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def db_check(path):
    c = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        if c.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('SQLite integrity check failed')
        if c.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('SQLite foreign key check failed')
    finally:
        c.close()


def sqlite_copy(source, target, timeout):
    with target.open('xb'):
        os.chmod(target, 0o600)
    source_db = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=5)
    output = sqlite3.connect(target)
    deadline = time.monotonic() + timeout

    def progress(*unused):
        if time.monotonic() > deadline:
            raise TimeoutError('SQLite backup deadline exceeded')

    try:
        source_db.backup(output, pages=256, progress=progress, sleep=0.1)
        # Make the snapshot self-contained even when the live database uses WAL.
        output.execute('PRAGMA journal_mode=DELETE')
    finally:
        output.close()
        source_db.close()
    db_check(target)
    with target.open('r+b') as stream:
        os.fsync(stream.fileno())


def load_config(path):
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    if set(raw) != {'destination', 'database', 'files', 'keep', 'timeout_seconds'}:
        raise ValueError('invalid configuration fields')
    if type(raw['keep']) is not int or raw['keep'] < 1:
        raise ValueError('keep must be a positive integer')
    if type(raw['timeout_seconds']) is not int or raw['timeout_seconds'] < 1:
        raise ValueError('timeout_seconds must be a positive integer')
    if not isinstance(raw['files'], list):
        raise ValueError('files must be a list')
    paths = [raw['destination'], raw['database'], *raw['files']]
    if any(not isinstance(p, str) or not Path(p).is_absolute() for p in paths):
        raise ValueError('all configured paths must be absolute')
    root, db, *files = map(safe_path, paths)
    if len(set([db, *files])) != len(files) + 1:
        raise ValueError('duplicate source')
    for p in [db, *files]:
        if not p.is_file() or root == p or root in p.parents:
            raise ValueError('source missing or inside backup destination')
    return raw, root, db, files


def verify(folder):
    folder = safe_path(folder)
    manifest_path = safe_path(folder / 'manifest.json')
    info = json.loads(manifest_path.read_text(encoding='utf-8'))
    if info.get('format') != FORMAT or info.get('complete') is not True:
        raise ValueError('not a completed backup')
    if not isinstance(info.get('entries'), list) or not info['entries']:
        raise ValueError('missing entries')
    names = set()
    database_count = 0
    for entry in info['entries']:
        name = entry['name']
        if not isinstance(name, str) or '/' in name or '\\' in name or name in ('.', '..', 'manifest.json') or name in names:
            raise ValueError('invalid backup filename')
        names.add(name)
        p = safe_path(folder / name)
        if not p.is_file() or digest(p) != entry['sha256']:
            raise ValueError('backup hash mismatch')
        if entry['kind'] == 'database':
            database_count += 1
            db_check(p)
        elif entry['kind'] != 'file':
            raise ValueError('unknown entry kind')
    if database_count != 1 or {p.name for p in folder.iterdir()} != names | {'manifest.json'}:
        raise ValueError('unexpected backup contents')
    return info


def prune(root, keep):
    # Only verified, completed generations created by this tool are candidates.
    candidates = []
    for p in root.glob('snapshot-*'):
        if not p.is_dir() or p.is_symlink():
            raise ValueError('unsafe retention candidate')
        info = verify(p)
        candidates.append((info['created_utc'], p.name, p))
    candidates.sort(reverse=True)
    removed = []
    for _, name, path in candidates[keep:]:
        if path.resolve().parent != root.resolve():
            raise ValueError('retention path outside destination')
        shutil.rmtree(path)
        removed.append(name)
    return removed


def run(config, delete_old=False):
    raw, root, db, files = load_config(config)
    private_dir(root)
    with locked(root):
        ident = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '-' + uuid.uuid4().hex[:8]
        pending = root / ('.pending-' + ident)
        pending.mkdir(mode=0o700)
        before = {str(p): digest(p) for p in files}
        entries = []
        # Configuration/key edits and round switches must be excluded operationally.
        for i, p in enumerate(files):
            name = f'file-{i:03d}-{p.name}'
            target = pending / name
            with p.open('rb') as source, target.open('xb') as dest:
                os.chmod(target, 0o600)
                shutil.copyfileobj(source, dest)
                dest.flush()
                os.fsync(dest.fileno())
            if digest(target) != before[str(p)]:
                raise ValueError('source changed during backup')
            st = p.stat()
            entries.append({'name': name, 'kind': 'file', 'source': str(p), 'sha256': digest(target),
                            'mode': stat.S_IMODE(st.st_mode), 'uid': getattr(st, 'st_uid', None), 'gid': getattr(st, 'st_gid', None)})
        sqlite_copy(db, pending / 'game.db', raw['timeout_seconds'])
        if any(digest(p) != before[str(p)] for p in files):
            raise ValueError('configuration changed during database snapshot')
        st = db.stat()
        entries.append({'name': 'game.db', 'kind': 'database', 'source': str(db), 'sha256': digest(pending / 'game.db'),
                        'mode': stat.S_IMODE(st.st_mode), 'uid': getattr(st, 'st_uid', None), 'gid': getattr(st, 'st_gid', None)})
        write_json(pending / 'manifest.json', {'format': FORMAT, 'complete': True,
                   'created_utc': datetime.now(timezone.utc).isoformat(), 'entries': entries})
        verify(pending)
        sync_dir(pending)
        completed = root / ('snapshot-' + ident)
        pending.rename(completed)
        sync_dir(root)
        removed = prune(root, raw['keep']) if delete_old else []
        return {'status': 'ok', 'snapshot': str(completed), 'pruned': removed}


def restore_copy(snapshot, destination):
    info = verify(snapshot)
    destination = safe_path(destination)
    for entry in info['entries']:
        source = safe_path(entry['source'])
        if destination == source or destination in source.parents or source in destination.parents:
            raise ValueError('restore destination overlaps original data')
    destination.mkdir(mode=0o700, parents=False)  # Refuse every existing destination.
    for entry in info['entries']:
        shutil.copyfile(Path(snapshot) / entry['name'], destination / entry['name'])
        os.chmod(destination / entry['name'], 0o600)
    shutil.copyfile(Path(snapshot) / 'manifest.json', destination / 'manifest.json')
    os.chmod(destination / 'manifest.json', 0o600)
    verify(destination)
    return {'status': 'verified_restore_copy', 'directory': str(destination), 'live_data_changed': False}


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('run')
    p.add_argument('--config', required=True)
    p.add_argument('--prune', action='store_true', help='delete only older verified generations after a successful snapshot')
    for command in ('verify', 'restore-copy'):
        p = sub.add_parser(command)
        p.add_argument('--snapshot', required=True)
        if command == 'restore-copy':
            p.add_argument('--destination', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'run':
            result = run(args.config, args.prune)
        elif args.command == 'verify':
            verify(args.snapshot)
            result = {'status': 'verified'}
        else:
            result = restore_copy(args.snapshot, args.destination)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as error:
        # Exception text might contain private paths/config values. Keep cron output bounded.
        print(json.dumps({'status': 'failed', 'error_type': type(error).__name__,
                          'hint': 'Check permissions, paths, available space, lock and snapshot integrity; live data was not restored.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
