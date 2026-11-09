"""Run only in an isolated POSIX workspace; never invoke the production entrypoint."""
import json, os, signal, sqlite3, stat, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
SCRIPT = SOURCE/'scripts/starroute-new-universe.sh'
CODE = SCRIPT.read_text().split("<<'PYTHON'\n", 1)[1].rsplit('\nPYTHON', 1)[0]

@unittest.skipIf(os.name=='nt', 'POSIX reset permissions, fork and locks')
class ResetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='reset-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ns = {'__name__':'reset_test'}
        exec(compile(CODE, str(SCRIPT), 'exec'), self.ns)
        n = self.ns
        for key, path in [('STATE','state'),('CONFIG','config'),('BACKUP_PARENT','backups'),('BIN','bin')]:
            n[key] = self.root/path; n[key].mkdir()
        n.update(CFG=n['CONFIG']/'door.json', DOOR=self.root/'door', DOORS=self.root/'doors.conf',
                 EXAMPLES=self.root/'examples', LIB=SOURCE, active_writers=lambda:None, note=lambda _:None)
        for name,module in [('admin','starroute.admin'),('maintain','starroute.maintenance'),
                            ('sites','starroute.network_admin'),('universe','srt_universe_generator')]:
            p=n['BIN']/('starroute-'+name)
            p.write_text('#!'+sys.executable+' -I\nimport sys,runpy\nsys.path.insert(0,'+repr(str(SOURCE))+')\nrunpy.run_module('+repr(module)+',run_name="__main__")\n')
            p.chmod(0o755)
        n['EXAMPLES'].mkdir()
        for name in ('release-world.json','connected-universe-trial.json','industry-levels-trial.json'):
            (n['EXAMPLES']/name).write_bytes((SOURCE/'examples'/name).read_bytes())
        old=n['STATE']/'world';old.mkdir()
        subprocess.run([str(n['BIN']/'starroute-admin'),'--db',str(old/'game.db'),'init'],check=True,capture_output=True)
        (old/'reference.key').write_bytes(b'old-secret-key-do-not-print'*2)
        (old/'site-profile.json').write_text(json.dumps({'bbs_id':'standalone','credential':'old-do-not-print'}))
        n['CFG'].write_text(json.dumps(dict(mode='standalone',database=str(old/'game.db'),reference_key=str(old/'reference.key'),profile=str(old/'site-profile.json'),language='ja',ansi=True)))
        n['DOOR'].write_text('old wrapper');n['DOOR'].chmod(0o755)
        n['DOORS'].write_text('existing BBS registration')
        self.original=n['CFG'].read_bytes()
        self.old_hashes={p:n['digest'](p) for p in old.iterdir() if p.is_file()}
        self.mask=signal.pthread_sigmask(signal.SIG_BLOCK,set())
        self.addCleanup(signal.pthread_sigmask,signal.SIG_SETMASK,self.mask)

    def perform(self):
        self.ns['perform']((os.getuid(),os.getgid()))

    def preserved(self):
        n=self.ns
        self.assertEqual(n['CFG'].read_bytes(),self.original)
        for p,h in self.old_hashes.items():self.assertEqual(n['digest'](p),h)
        self.assertEqual(n['DOORS'].read_text(),'existing BBS registration')

    def test_success_new_world_and_retained_original(self):
        self.perform();n=self.ns;c=json.loads(n['CFG'].read_text())
        self.assertNotEqual(n['CFG'].read_bytes(),self.original)
        for p,h in self.old_hashes.items():self.assertEqual(n['digest'](p),h)
        self.assertEqual(stat.S_IMODE(n['DOOR'].stat().st_mode),0o644)
        new=Path(c['database']).parent
        con=sqlite3.connect(c['database'])
        self.assertEqual(con.execute('SELECT COUNT(*) FROM planets').fetchone()[0],49)
        self.assertEqual(con.execute('SELECT COUNT(*) FROM player_state').fetchone()[0],0)
        self.assertEqual(con.execute('SELECT ends_at-starts_at FROM p4_rounds').fetchone()[0],2592000)
        con.close()
        template=json.loads((new/'template.json').read_text())
        original=json.loads((SOURCE/'examples/release-world.json').read_text())
        for old,newrow in zip(original['navigation']['plans'],template['navigation']['plans']):
            self.assertEqual(newrow['normal_seconds'],(old['normal_seconds']+59)//60)
            for a,b in zip(old['warp_options'],newrow['warp_options']):
                self.assertEqual(b['seconds'],(a['seconds']+59)//60);self.assertEqual(a['fuel_cost'],b['fuel_cost'])
        self.assertEqual(len(list(n['BACKUP_PARENT'].glob('*/state-and-config.tar'))),1)

    def test_failures_never_switch(self):
        for stage in ('door_closed','backup_verified','new_active','validated','before_switch'):
            with self.subTest(stage=stage):
                def fail(name):
                    if name==stage:raise RuntimeError('injected')
                self.ns['checkpoint']=fail
                with self.assertRaisesRegex(RuntimeError,'injected'):self.perform()
                self.preserved()
                self.assertEqual(stat.S_IMODE(self.ns['DOOR'].stat().st_mode),0o644)

    def test_generation_rejection(self):
        (self.ns['EXAMPLES']/'release-world.json').write_text('{}')
        with self.assertRaises(KeyError):self.perform()
        self.preserved()

    def test_backup_failure(self):
        with patch.object(sys.modules['tarfile'],'open',side_effect=OSError('backup full')):
            with self.assertRaises(OSError):self.perform()
        self.preserved()

    def test_rename_failure(self):
        real=os.replace
        def fail(src,dst):
            if Path(dst)==self.ns['CFG']:raise OSError('rename denied')
            return real(src,dst)
        with patch.object(os,'replace',side_effect=fail):
            with self.assertRaisesRegex(OSError,'rename denied'):self.perform()
        self.preserved()

    def test_writer_rejection_before_maintenance(self):
        def fail():raise RuntimeError('writer active')
        self.ns['active_writers']=fail
        with self.assertRaisesRegex(RuntimeError,'writer active'):self.perform()
        self.preserved()
        self.assertEqual(stat.S_IMODE(self.ns['DOOR'].stat().st_mode),0o755)

    def test_wrong_mode_rejected(self):
        self.ns['CFG'].write_text('{"mode":"inter-bbs"}')
        with self.assertRaisesRegex(RuntimeError,'standalone'):self.perform()
        self.assertEqual(stat.S_IMODE(self.ns['DOOR'].stat().st_mode),0o755)

if __name__=='__main__':unittest.main(verbosity=2)
