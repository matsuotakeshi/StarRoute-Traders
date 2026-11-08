import hashlib,io,json,os,sys,tarfile,tempfile,threading,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ci'))
from native_ci import all_passed,require_trusted_main,parse_result,ssh_options
from native_remote import RESULT,commands_for,unpack,cleanup,host_lock,run_commands
from runner_admission import allowed
from run_tests import execute
SHA='a'*40

class CIPolicyTests(unittest.TestCase):
    def env(self):return dict(GITHUB_REPOSITORY='matsuotakeshi/StarRoute-Traders',GITHUB_REF='refs/heads/main',GITHUB_EVENT_NAME='push',GITHUB_SHA=SHA)
    def test_exact_main_only(self):
        require_trusted_main(self.env(),SHA,SHA)
        for key,value in [('GITHUB_REPOSITORY','other/repo'),('GITHUB_REF','refs/pull/1/merge'),('GITHUB_EVENT_NAME','pull_request'),('GITHUB_SHA','b'*40)]:
            env=self.env();env[key]=value
            with self.assertRaises(ValueError):require_trusted_main(env,SHA,SHA)
    def test_prejob_hook_rejects_pr_even_with_main_environment(self):
        event={'repository':{'full_name':self.env()['GITHUB_REPOSITORY']},'ref':'refs/heads/main'}
        self.assertTrue(allowed(self.env(),event));event['pull_request']={};self.assertFalse(allowed(self.env(),event))
        event.pop('pull_request');event['ref']='feature';self.assertFalse(allowed(self.env(),event))
        self.assertFalse(allowed({},{}))
    def test_owner_pr_only_on_native(self):
        env=dict(self.env(),GITHUB_EVENT_NAME='pull_request',GITHUB_REF='refs/pull/1/merge')
        repo={'full_name':env['GITHUB_REPOSITORY']}
        event={'repository':repo,'action':'opened','number':1,'pull_request':{'user':{'login':'matsuotakeshi'},'head':{'repo':dict(repo),'sha':SHA},'base':{'repo':dict(repo),'ref':'main'}}}
        self.assertTrue(allowed(env,event))
        event['pull_request']['head']['repo']['full_name']='outsider/fork';self.assertFalse(allowed(env,event))
        event['pull_request']['head']['repo']=dict(repo)
        event['pull_request']['user']['login']='outsider';self.assertFalse(allowed(env,event))
        event['pull_request']['user']['login']='matsuotakeshi';event['number']=2;self.assertFalse(allowed(env,event))
    def test_commands_use_unittest_not_bbs_make_check(self):
        for target in ('freebsd','rocky','ubuntu'):
            commands=commands_for(target);self.assertIn('ci/run_tests.py',commands[0]);self.assertNotIn('check',commands[1]);self.assertIn('runtime',commands[1]);self.assertIn('scripts/bbs_ui_telnet_demo.py',commands[2])
    def test_ssh_never_disables_host_key_or_falls_back_to_password(self):
        opts=ssh_options('/key');self.assertIn('StrictHostKeyChecking=yes',opts);self.assertIn('PasswordAuthentication=no',opts);self.assertIn('IdentitiesOnly=yes',opts)
    def test_all_os_gate_rejects_missing_duplicates_and_failure(self):
        rows=[{'target':os,'status':'passed','source_sha':SHA} for os in ('freebsd','rocky','ubuntu')];targets=[r['target'] for r in rows]
        self.assertTrue(all_passed(rows,targets,SHA));self.assertFalse(all_passed(rows[:-1],targets,SHA));self.assertFalse(all_passed(rows+[rows[0]],targets,SHA))
        for status in ('failed','cancelled','skipped'):self.assertFalse(all_passed([dict(rows[0],status=status)]+rows[1:],targets,SHA))
    def test_missing_or_wrong_worker_result_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'log';p.write_text('')
            with self.assertRaises(ValueError):parse_result(p,'freebsd',SHA)
            p.write_text(RESULT+json.dumps({'target':'freebsd','source_sha':'b'*40,'status':'passed'}))
            with self.assertRaises(ValueError):parse_result(p,'freebsd',SHA)
    def test_failure_and_skip_remain_visible(self):
        class Fixture(unittest.TestCase):
            def runTest(self):self.fail('synthetic failure')
        report=execute(unittest.TestSuite([Fixture()]),io.StringIO());self.assertFalse(report['ok']);self.assertEqual(report['failures'],1)
        self.assertFalse(execute(unittest.TestSuite(),io.StringIO())['ok'])
    def test_archive_digest_and_unsafe_paths_rejected(self):
        for name,kind in [('../escape',tarfile.REGTYPE),('/absolute',tarfile.REGTYPE),('link',tarfile.SYMTYPE)]:
            with tempfile.TemporaryDirectory() as temp:
                p=Path(temp)/'source.tar.gz'
                with tarfile.open(p,'w:gz') as tf:
                    info=tarfile.TarInfo(name);info.type=kind;info.linkname='/etc/passwd';tf.addfile(info)
                with self.assertRaises(ValueError):unpack(temp,hashlib.sha256(p.read_bytes()).hexdigest(),SHA)
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp)/'source.tar.gz').write_bytes(b'bad')
            with self.assertRaises(ValueError):unpack(temp,'0'*64,SHA)
    def test_cleanup_cannot_remove_other_project(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):cleanup(Path(temp),SHA)
            self.assertTrue(Path(temp).exists())
    def test_workflow_fixed_checks_and_no_privileged_pr(self):
        text=(ROOT/'.github/workflows/starroute-ci.yml').read_text()
        self.assertIn('    if: always()',text.split('  native-required:')[1]);self.assertNotIn('pull_request_target',text);self.assertIn('StarRoute / Required',text);self.assertIn('StarRoute / Native required',text)
        self.assertIn("github.ref == 'refs/heads/main'",text);self.assertIn('starroute-native]',text)
        import re
        for action in re.findall(r'uses: ([^\s]+)',text):self.assertRegex(action,r'@[a-f0-9]{40}$')

@unittest.skipIf(os.name=='nt','POSIX advisory locks and pipe monitoring')
class CILockTests(unittest.TestCase):
    def test_other_project_lock_waits_then_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'shared.lock';read,write=os.pipe();entered=[]
            def waiter():
                with host_lock(path,read,3,3):entered.append(True)
            try:
                with host_lock(path):
                    thread=threading.Thread(target=waiter);thread.start();os.write(write,b'alive\n');time.sleep(.3);self.assertFalse(entered)
                thread.join(3);self.assertFalse(thread.is_alive());self.assertEqual(entered,[True])
            finally:os.close(read);os.close(write)
    def test_disconnected_waiter_does_not_start_or_hold_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'shared.lock';read,write=os.pipe();os.close(write)
            try:
                with host_lock(path):
                    with self.assertRaisesRegex(RuntimeError,'disconnected'),host_lock(path,read,2,1):pass
                with host_lock(path):pass
            finally:os.close(read)
