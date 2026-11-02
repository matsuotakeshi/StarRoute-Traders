set -eu
ROOT=/home/takeshi/starroute-ports-verification-20261102
J="$ROOT/runtime"
cp -p "$ROOT/packages-019/All/"starroute*.pkg "$J/old-packages/"
jexec srt_pkg_acceptance /usr/local/bin/starroute-maintain --db /var/db/starroute-traders/world/game.db check --supported-max-schema 11 --supported-rules-version phase3-complete-1
jexec srt_pkg_acceptance pkg add -f /old-packages/starroute-traders-client-0.19.0.pkg /old-packages/starroute-traders-0.19.0.pkg /old-packages/starroute-traders-master-0.19.0.pkg
jexec srt_pkg_acceptance pkg info -x starroute
jexec srt_pkg_acceptance /usr/local/bin/python3.12 /verification/pkg_lifecycle_fixture.py check
jexec srt_pkg_acceptance pkg check -s -g 'starroute-traders*'
jexec srt_pkg_acceptance pkg delete -y starroute-traders-master starroute-traders starroute-traders-client
jexec srt_pkg_acceptance /usr/local/bin/python3.12 /verification/pkg_lifecycle_fixture.py check
test ! -e "$J/usr/local/bin/starroute-door"
printf 'ROLLBACK_AND_DELETE_DATA_PRESERVED\n'
jexec srt_pkg_acceptance pkg install -y -r StarRouteTest starroute-traders-master
jexec srt_pkg_acceptance /usr/local/bin/python3.12 /verification/pkg_lifecycle_fixture.py check
printf 'REINSTALL_LATEST_PASS\n'
