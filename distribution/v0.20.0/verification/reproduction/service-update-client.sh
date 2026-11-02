set -eu
ROOT=/home/takeshi/starroute-ports-verification-20261102
J="$ROOT/runtime"
jexec srt_pkg_acceptance service starroute_master onestart
sleep 1
PID=$(cat "$J/var/run/starroute-traders/master.pid")
LOG_HASH=$(sha256 -q "$J/var/log/starroute-traders/master.log")
jexec srt_pkg_acceptance pkg install -y -f -r StarRouteTest starroute-traders-master > "$ROOT/logs/service-pkg-reinstall.log" 2>&1
test "$PID" = "$(cat "$J/var/run/starroute-traders/master.pid")"
test "$LOG_HASH" = "$(sha256 -q "$J/var/log/starroute-traders/master.log")"
jexec srt_pkg_acceptance service starroute_master onestatus
printf 'PKG_REINSTALL_DID_NOT_STOP_SERVICE_OR_TOUCH_LOG\n'
jexec srt_pkg_acceptance kill -KILL "$PID"
sleep 1
if jexec srt_pkg_acceptance service starroute_master onestatus; then exit 1; fi
jexec srt_pkg_acceptance service starroute_master onestart
sleep 1
jexec srt_pkg_acceptance service starroute_master onestatus
jexec srt_pkg_acceptance service starroute_master onestop
printf 'CRASH_EXPLICIT_RESTART_PASS\n'
jexec srt_pkg_acceptance pkg delete -y starroute-traders-master starroute-traders > "$ROOT/logs/client-only-remove-master.log" 2>&1
test ! -e "$J/usr/local/libexec/starroute-traders/starroute/__init__.py"
test ! -e "$J/usr/local/bin/starroute-master"
jexec srt_pkg_acceptance /usr/local/bin/starroute-door --help
jexec srt_pkg_acceptance /usr/local/bin/starroute-node --help
jexec srt_pkg_acceptance /usr/local/bin/python3.12 /verification/pkg_lifecycle_fixture.py check
printf 'CLIENT_ONLY_INSTALL_HAS_NO_ENGINE_OR_MASTER_TOOLS\n'
jexec srt_pkg_acceptance pkg install -y -r StarRouteTest starroute-traders-master > "$ROOT/logs/client-only-restore.log" 2>&1
printf 'SERVICE_UPDATE_CRASH_AND_CLIENT_BOUNDARY_PASS\n'
