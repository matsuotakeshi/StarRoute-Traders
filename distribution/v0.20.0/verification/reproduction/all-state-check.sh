set -eu
ROOT=/home/takeshi/starroute-ports-verification-20261102
J="$ROOT/runtime"
mount -t devfs devfs "$J/dev"
devfs -m "$J/dev" rule -s 4 applyset
jail -c name=srt_pkg_acceptance path="$J" host.hostname=srt-pkg persist ip4.addr=127.0.0.1
trap 'jail -r srt_pkg_acceptance; umount "$J/dev"' EXIT
jexec srt_pkg_acceptance /usr/local/bin/python3.12 - <<'PY'
import hashlib,json,sqlite3,subprocess
from pathlib import Path
root=Path('/var/db/starroute-traders/world')
def snapshot():
 c=sqlite3.connect((root/'game.db').as_uri()+'?mode=ro',uri=True)
 try:
  assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  assert not c.execute('PRAGMA foreign_key_check').fetchall()
  rows=c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
  digest=hashlib.sha256('\n'.join(c.iterdump()).encode()).hexdigest()
 finally:c.close()
 paths=[p for p in root.rglob('*') if p.is_file() and p.name!='game.db' and not p.name.endswith(('-wal','-shm'))]
 paths += [Path('/usr/local/etc/starroute-traders/standalone.json'),Path('/usr/local/etc/starroute-traders/master.json'),Path('/var/log/starroute-traders/master.log')]
 return {'db_dump_hash':digest,'table_count':len(rows),'files':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
before=snapshot()
commands=[['pkg','add','-f','/old-packages/starroute-traders-client-0.19.0.pkg','/old-packages/starroute-traders-0.19.0.pkg','/old-packages/starroute-traders-master-0.19.0.pkg'],['pkg','upgrade','-y','-g','-r','StarRouteTest','starroute-traders*'],['pkg','delete','-y','starroute-traders-master','starroute-traders','starroute-traders-client'],['pkg','install','-y','-r','StarRouteTest','starroute-traders-master']]
for command in commands:
 result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 assert result.returncode==0,result.stdout
 assert snapshot()==before,command
 print('ALL_STATE_PRESERVED',command[1],before['table_count'],'tables',len(before['files']),'private/config/log files')
Path('/verification/all-state-result.json').write_text(json.dumps({'all_tables':before['table_count'],'preserved_files':len(before['files']),'actions':['downgrade','upgrade','delete','install'],'integrity':'ok'},indent=2))
PY
cp "$J/verification/all-state-result.json" "$ROOT/export/verification/"
chown takeshi:takeshi "$ROOT/export/verification/all-state-result.json"
printf 'ALL_TABLES_AND_RUNTIME_FILES_PRESERVED\n'
