set -eu
ROOT=/home/takeshi/starroute-ports-verification-20261102
J="$ROOT/runtime"
mv "$J/repo" "$J/repo-019"
mkdir "$J/repo"
cp -Rp "$ROOT/packages-020/All" "$J/repo/"
pkg repo "$J/repo" "rsa:$ROOT/repo-test.key"
jexec srt_pkg_acceptance pkg update -f
jexec srt_pkg_acceptance /usr/local/bin/python3.12 /verification/pkg-abort.py
jexec srt_pkg_acceptance /usr/local/bin/python3.12 /verification/pkg_lifecycle_fixture.py check
jexec srt_pkg_acceptance pkg upgrade -y -g -r StarRouteTest 'starroute-traders*'
jexec srt_pkg_acceptance pkg info -x starroute
jexec srt_pkg_acceptance /usr/local/bin/python3.12 /verification/pkg_lifecycle_fixture.py check
jexec srt_pkg_acceptance /usr/local/bin/starroute-maintain --db /var/db/starroute-traders/world/game.db check --supported-max-schema 11 --supported-rules-version phase3-complete-1
jexec srt_pkg_acceptance /usr/local/bin/starroute-maintain --db /var/db/starroute-traders/world/game.db backup --output /verification/pkg-backup.db
jexec srt_pkg_acceptance /usr/local/bin/starroute-maintain --db /var/db/starroute-traders/world/game.db migrate-copy --backup /verification/migration-backup.db --output /verification/migrated.db
jexec srt_pkg_acceptance /usr/local/bin/python3.12 /verification/pkg_lifecycle_fixture.py check
printf 'PKG_UPGRADE_PRESERVATION_PASS\n'
