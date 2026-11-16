"""Small native OS surface checks; game rules remain in the FreeBSD suite."""
import os,signal,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1]

class PlatformSmokeTests(unittest.TestCase):
    def test_import_and_cli_entrypoints(self):
        for module in ('starroute','starroute_bbs.door','srt_universe_generator'):
            subprocess.run([sys.executable,'-c','import '+module],cwd=ROOT,check=True,capture_output=True,timeout=20)
        for module in ('starroute','starroute_bbs.door'):
            subprocess.run([sys.executable,'-m',module,'--help'],cwd=ROOT,check=True,capture_output=True,timeout=20)

    def test_sqlite_path_rollback_and_reopen(self):
        with tempfile.TemporaryDirectory(prefix='srt-os-') as temp:
            path=Path(temp)/'space 日本語.db'
            with closing(sqlite3.connect(path)) as db:
                db.execute('create table sample (id integer primary key, n integer not null)')
                db.execute('insert into sample values (1,10)');db.commit()
            with closing(sqlite3.connect(path)) as db:
                db.execute('update sample set n=99');db.rollback()
                self.assertEqual(db.execute('select n from sample').fetchone(),(10,))
                self.assertEqual(db.execute('pragma integrity_check').fetchone(),('ok',))

    @unittest.skipIf(os.name=='nt','POSIX process groups')
    def test_signal_reaps_only_spawned_group(self):
        p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],start_new_session=True)
        try:
            os.killpg(p.pid,signal.SIGTERM)
            self.assertEqual(p.wait(timeout=5),-signal.SIGTERM)
        finally:
            if p.poll() is None:os.killpg(p.pid,signal.SIGKILL);p.wait()
