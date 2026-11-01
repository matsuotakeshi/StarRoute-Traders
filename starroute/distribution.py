"""Offline-capable, pinned Git transport and SSH signed-manifest verification.

Never checks out or executes repository content. Trust files are operator-owned.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile

_settings=json.loads((Path(__file__).parent/'config/distribution.json').read_text(encoding='utf8'))
LIMIT=_settings['maximum_blob_bytes']
TIMEOUT=_settings['command_timeout_seconds']
if type(LIMIT) is not int or LIMIT<1 or type(TIMEOUT) is not int or TIMEOUT<1:raise ValueError('distribution settings')
NAMESPACE='starroute-universe'


def safe_path(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_./-]+',value):raise ValueError('unsafe package path')
    p=PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or str(p)!=value or value.startswith('-'):raise ValueError('unsafe package path')
    return value


def read_limited(path,limit=LIMIT):
    with open(path,'rb') as f:data=f.read(limit+1)
    if len(data)>limit:raise ValueError('size limit')
    return data


def run(args,*,data=None,env=None,limit=LIMIT):
    # Disk-backed output prevents an untrusted Git blob from exhausting memory.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            p=subprocess.run(args,input=data,stdout=out,stderr=err,env=env,timeout=TIMEOUT)
        except (OSError,subprocess.TimeoutExpired):raise ValueError('external tool unavailable or timed out') from None
        if p.returncode:raise ValueError('transport or signature verification failed')
        if out.tell()>limit:raise ValueError('size limit')
        out.seek(0);return out.read(limit+1)


def verify(package,manifest,signature,allowed_signers,identity):
    if not identity or '\n' in identity:raise ValueError('signer identity required')
    m=json.loads(manifest)
    if set(m)!={'format','package_sha256','universe_id'} or m['format']!='srt-signed-manifest-v1':raise ValueError('manifest format')
    if hashlib.sha256(package).hexdigest()!=m['package_sha256']:raise ValueError('package hash mismatch')
    if json.loads(package)['metadata']['universe_id']!=m['universe_id']:raise ValueError('manifest universe mismatch')
    trust=Path(allowed_signers).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='srt-verify-') as td:
        sig=Path(td)/'manifest.sig';sig.write_bytes(signature)
        run(['ssh-keygen','-Y','verify','-f',str(trust),'-I',identity,'-n',NAMESPACE,'-s',str(sig)],data=manifest)
    return {'status':'verified','method':'ssh-signed-manifest-v1','signer':identity,
            'trust_sha256':hashlib.sha256(read_limited(trust)).hexdigest(),
            'manifest_sha256':hashlib.sha256(manifest).hexdigest()}


def fetch(repository,commit,package_path,*,allowed_signers,identity,key=None,known_hosts=None,local_test=False):
    if not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})',commit):raise ValueError('full immutable commit required')
    package_path=safe_path(package_path)
    env=os.environ.copy()
    for k in list(env):
        if k.startswith('GIT_'):del env[k]
    env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,GIT_TERMINAL_PROMPT='0')
    if local_test:
        repository=str(Path(repository).resolve(strict=True));protocol='file'
    else:
        if not re.fullmatch(r'git@github\.com:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git',repository):raise ValueError('GitHub SSH repository required')
        if not key or not known_hosts:raise ValueError('dedicated read-only deploy key and trusted hosts required')
        # Git's SSH command is shell-interpreted: reject shell metacharacters in paths.
        paths=[str(Path(p).resolve(strict=True)) for p in (key,known_hosts)]
        if any(re.search(r'["`$\r\n!%]',p) for p in paths):raise ValueError('unsafe SSH configuration path')
        env['GIT_SSH_COMMAND']='ssh -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no -o UserKnownHostsFile="'+paths[1]+'" -i "'+paths[0]+'"'
        protocol='ssh'
    with tempfile.TemporaryDirectory(prefix='srt-fetch-') as td:
        base=['git','-c','core.hooksPath='+os.devnull,'-c','protocol.allow=never','-c','protocol.'+protocol+'.allow=always','-C',td]
        run(base+['init','--bare'],env=env)
        run(base+['fetch','--no-tags','--depth=1',repository,commit],env=env)
        if run(base+['rev-parse','FETCH_HEAD^{commit}'],env=env).decode().strip()!=commit:raise ValueError('commit mismatch')
        def blob(path):
            path=safe_path(path)
            listing=run(base+['ls-tree',commit,'--',path],env=env).decode().split()
            if len(listing)!=4 or listing[0]!='100644' or listing[1]!='blob' or listing[3]!=path:raise ValueError('regular package file required')
            if int(run(base+['cat-file','-s',listing[2]],env=env))>LIMIT:raise ValueError('size limit')
            return run(base+['cat-file','blob',listing[2]],env=env)
        package=blob(package_path);manifest=blob(package_path+'.manifest.json');signature=blob(package_path+'.manifest.json.sig')
        proof=verify(package,manifest,signature,allowed_signers,identity)
        return package,dict(source_type='LocalGitTest' if local_test else 'GitHub',repository_id=repository,commit_id=commit,verification=proof)
