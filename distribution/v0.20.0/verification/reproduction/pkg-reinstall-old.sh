set -eu
ROOT=/home/takeshi/starroute-ports-verification-20261102
J="$ROOT/runtime"
cp -p "$ROOT/packages-019/All/"*.pkg "$J/repo/All/"
pkg repo "$J/repo" "rsa:$ROOT/repo-test.key" > "$ROOT/logs/repo-019-final.log" 2>&1
jexec srt_pkg_acceptance pkg delete -y starroute-traders-master starroute-traders starroute-traders-client
jexec srt_pkg_acceptance pkg update -f -r StarRouteTest
jexec srt_pkg_acceptance pkg install -y -r StarRouteTest starroute-traders-master
jexec srt_pkg_acceptance pkg info -x starroute
if jexec srt_pkg_acceptance service starroute_master onestatus; then exit 1; fi
jexec srt_pkg_acceptance /usr/local/bin/python3.12 /verification/pkg_lifecycle_fixture.py create
jexec srt_pkg_acceptance /usr/local/bin/python3.12 /verification/pkg_lifecycle_fixture.py check
printf 'CLEAN_INSTALL_WITH_SQLITE_PASS\n'
