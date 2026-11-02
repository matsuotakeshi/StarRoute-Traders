set -eu
ROOT=/home/takeshi/starroute-ports-verification-20261102
jexec srt_pkg_acceptance /usr/local/bin/python3.12 - <<'PY'
import sys,json,sqlite3
from pathlib import Path
sys.path.insert(0,'/usr/local/libexec/starroute-traders')
from starroute.maintenance import migrate_copy,inspect
source=Path('/var/db/starroute-traders/world/game.db')
def fail(step):
 if step=='after_migration':raise RuntimeError('injected failure before publication')
destination=Path('/verification/failed-migration.db')
try:migrate_copy(source,destination,'/verification/failure-backup.db',fail)
except RuntimeError:pass
else:raise AssertionError('fault not injected')
assert not destination.exists()
assert json.loads(Path(str(destination)+'.migration.json').read_text())['state']=='failed'
assert inspect('/verification/failure-backup.db')['integrity']=='ok'
print('MIGRATION_FAILURE_ORIGINAL_AND_BACKUP_PRESERVED')
# Restore a new test copy from the backup and validate it, never overwrite source.
c=sqlite3.connect('/verification/failure-backup.db');out=sqlite3.connect('/verification/restored.db');c.backup(out);out.close();c.close()
assert inspect('/verification/restored.db')['integrity']=='ok'
print('BACKUP_RESTORE_COPY_PASS')
PY
jexec srt_pkg_acceptance /usr/local/bin/python3.12 /verification/pkg_lifecycle_fixture.py check
