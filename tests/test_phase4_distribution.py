import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from starroute.distribution import run,fetch,verify


class DistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        cls.key=cls.root/'issuer';cls.trust=cls.root/'allowed_signers'
        run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(cls.key)])
        cls.trust.write_text('issuer '+Path(str(cls.key)+'.pub').read_text(),encoding='utf8')
        cls.repo=cls.root/'repo';cls.repo.mkdir()
        cls.package=b'{"metadata":{"universe_id":"test"}}'
        cls.manifest=json.dumps({'format':'srt-signed-manifest-v1','universe_id':'test','package_sha256':hashlib.sha256(cls.package).hexdigest()}).encode()
        (cls.repo/'u.json').write_bytes(cls.package)
        mp=cls.repo/'u.json.manifest.json';mp.write_bytes(cls.manifest)
        run(['ssh-keygen','-Y','sign','-f',str(cls.key),'-n','starroute-universe',str(mp)])
        cls.signature=Path(str(mp)+'.sig').read_bytes()
        cls.git=['git','-C',str(cls.repo)]
        run(cls.git+['init']);run(cls.git+['add','.'])
        run(cls.git+['-c','user.name=Test','-c','user.email=test@example.invalid','-c','commit.gpgsign=false','commit','-m','test fixture'])
        cls.commit=run(cls.git+['rev-parse','HEAD']).decode().strip()

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def fetch(self,**kwargs):
        return fetch(str(self.repo),self.commit,'u.json',allowed_signers=self.trust,identity='issuer',local_test=True,**kwargs)

    def test_signed_fetch(self):
        raw,proof=self.fetch();self.assertEqual(raw,self.package)
        self.assertEqual(proof['commit_id'],self.commit);self.assertEqual(proof['verification']['status'],'verified')

    def test_repeated_fetch(self):self.assertEqual(self.fetch(),self.fetch())

    def test_manifest_changed(self):
        changed=self.manifest+b' '
        with self.assertRaises(ValueError):verify(self.package,changed,self.signature,self.trust,'issuer')

    def test_hash_changed(self):
        with self.assertRaises(ValueError):verify(self.package+b' ',self.manifest,self.signature,self.trust,'issuer')

    def test_wrong_signer(self):
        with self.assertRaises(ValueError):verify(self.package,self.manifest,self.signature,self.trust,'unknown')

    def test_bad_signature(self):
        with self.assertRaises(ValueError):verify(self.package,self.manifest,b'invalid',self.trust,'issuer')

    def test_nonexistent_commit(self):
        with self.assertRaises(ValueError):fetch(str(self.repo),'0'*40,'u.json',allowed_signers=self.trust,identity='issuer',local_test=True)

    def test_missing_file(self):
        with self.assertRaises(ValueError):fetch(str(self.repo),self.commit,'absent',allowed_signers=self.trust,identity='issuer',local_test=True)

    def test_network_requires_dedicated_credentials(self):
        with self.assertRaises(ValueError):fetch('git@github.com:example/private.git',self.commit,'u.json',allowed_signers=self.trust,identity='issuer')

    def test_strict_ssh_and_no_global_git_config(self):
        from unittest.mock import patch
        with patch('starroute.distribution.run',side_effect=ValueError('test stop before transport')) as mocked:
            with self.assertRaises(ValueError):fetch('git@github.com:example/private.git',self.commit,'u.json',allowed_signers=self.trust,identity='issuer',key=self.key,known_hosts=self.trust)
        env=mocked.call_args.kwargs['env'];ssh=env['GIT_SSH_COMMAND']
        for expected in ('StrictHostKeyChecking=yes','BatchMode=yes','IdentitiesOnly=yes','PasswordAuthentication=no'):self.assertIn(expected,ssh)
        self.assertEqual(env['GIT_CONFIG_NOSYSTEM'],'1');self.assertEqual(env['GIT_TERMINAL_PROMPT'],'0')
