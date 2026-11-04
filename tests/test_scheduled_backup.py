import importlib.util
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('scheduled_backup', Path(__file__).resolve().parents[1] / 'scripts/scheduled_backup.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.db = self.root / 'live.db'
        self.c = sqlite3.connect(self.db)
        self.c.execute('PRAGMA journal_mode=WAL')
        self.c.execute('CREATE TABLE assets (id INTEGER PRIMARY KEY, credits INTEGER)')
        self.c.execute('INSERT INTO assets VALUES (1,5000)')
        self.c.commit()
        self.key = self.root / 'reference.key'
        self.key.write_text('test-secret', encoding='utf-8')
        self.config = self.root / 'config.json'
        self.settings = dict(destination=str(self.root / 'backups'), database=str(self.db), files=[str(self.key)], keep=2, timeout_seconds=5)
        self.save_config()

    def save_config(self):
        self.config.write_text(json.dumps(self.settings), encoding='utf-8')

    def tearDown(self):
        self.c.close()
        self.temp.cleanup()

    def snapshot(self, prune=False):
        return Path(b.run(self.config, prune)['snapshot'])

    def test_wal_snapshot_and_verified_restore_preserve_live_data(self):
        self.c.execute('UPDATE assets SET credits=6000')
        self.c.commit()
        snap = self.snapshot()
        restored = self.root / 'restored'
        b.restore_copy(snap, restored)
        with closing(sqlite3.connect(restored / 'game.db')) as c:
            self.assertEqual(c.execute('SELECT credits FROM assets').fetchone(), (6000,))
        self.assertEqual(self.c.execute('SELECT credits FROM assets').fetchone(), (6000,))
        self.assertEqual((restored / 'file-000-reference.key').read_text(), 'test-secret')

    def test_uncommitted_transaction_is_not_in_snapshot(self):
        self.c.execute('UPDATE assets SET credits=1')
        snap = self.snapshot()
        with closing(sqlite3.connect(snap / 'game.db')) as c:
            self.assertEqual(c.execute('SELECT credits FROM assets').fetchone(), (5000,))
        self.c.rollback()

    def test_retention_opt_in_only_and_foreign_directory_preserved(self):
        snapshots = [self.snapshot() for _ in range(3)]
        foreign = self.root / 'backups' / 'manual-backup'
        foreign.mkdir()
        self.assertTrue(all(p.exists() for p in snapshots))
        self.snapshot(True)
        self.assertEqual(len(list((self.root / 'backups').glob('snapshot-*'))), 2)
        self.assertTrue(foreign.exists())

    def test_failure_does_not_publish_or_prune(self):
        previous = self.snapshot()
        with patch.object(b, 'sqlite_copy', side_effect=RuntimeError('disk failure')):
            with self.assertRaises(RuntimeError):
                self.snapshot(True)
        self.assertTrue(previous.exists())
        self.assertEqual(len(list((self.root / 'backups').glob('snapshot-*'))), 1)

    def test_tampered_backup_rejected_before_restore_and_prune(self):
        previous = self.snapshot()
        (previous / 'file-000-reference.key').write_text('tampered')
        with self.assertRaises(ValueError):
            b.restore_copy(previous, self.root / 'restore')
        with self.assertRaises(ValueError):
            self.snapshot(True)
        self.assertTrue(previous.exists())
        self.assertFalse((self.root / 'restore').exists())

    def test_existing_restore_target_refused(self):
        snap = self.snapshot()
        dest = self.root / 'restore'
        dest.mkdir()
        (dest / 'keep').write_text('untouched')
        with self.assertRaises(FileExistsError):
            b.restore_copy(snap, dest)
        self.assertEqual((dest / 'keep').read_text(), 'untouched')

    def test_missing_source_refused(self):
        self.key.unlink()
        with self.assertRaises(ValueError):
            self.snapshot()

    def test_concurrent_lock_rejected(self):
        self.snapshot()
        with b.locked(self.root / 'backups'):
            with self.assertRaises(OSError):
                self.snapshot()

    def test_config_change_during_snapshot_fails(self):
        copy = b.sqlite_copy
        def change(*args):
            copy(*args)
            self.key.write_text('changed')
        with patch.object(b, 'sqlite_copy', side_effect=change):
            with self.assertRaises(ValueError):
                self.snapshot()
        self.assertEqual(list((self.root / 'backups').glob('snapshot-*')), [])

    def test_path_traversal_in_manifest_rejected(self):
        snap = self.snapshot()
        p = snap / 'manifest.json'
        info = json.loads(p.read_text())
        info['entries'][0]['name'] = '../reference.key'
        p.write_text(json.dumps(info))
        with self.assertRaises(ValueError):
            b.verify(snap)

    @unittest.skipIf(os.name == 'nt', 'POSIX permissions and symlinks')
    def test_private_permissions_and_symlink_rejection(self):
        snap = self.snapshot()
        self.assertEqual(snap.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all((p.stat().st_mode & 0o777) == 0o600 for p in snap.iterdir()))
        self.key.unlink()
        self.key.symlink_to(self.db)
        with self.assertRaises(ValueError):
            self.snapshot()


if __name__ == '__main__':
    unittest.main()
