set -eu
ROOT=/home/takeshi/starroute-ports-verification-20261102
J="$ROOT/runtime"
cp -Rp "$ROOT/export/repo" "$J/release-repo"
sed -i '' 's@file:///repo@file:///release-repo@' "$J/usr/local/etc/pkg/repos/StarRouteTest.conf"
jexec srt_pkg_acceptance pkg update -f -r StarRouteTest
jexec srt_pkg_acceptance pkg rquery -r StarRouteTest '%n %v'
jexec srt_pkg_acceptance pkg install -y -f -r StarRouteTest starroute-traders-master starroute-traders starroute-traders-client > "$ROOT/logs/release-three-package-install.log" 2>&1
jexec srt_pkg_acceptance /usr/local/bin/python3.12 /verification/pkg_lifecycle_fixture.py check
jexec srt_pkg_acceptance pkg check -s -g 'starroute-traders*'
if jexec srt_pkg_acceptance service starroute_master onestatus; then exit 1; fi
jail -r srt_pkg_acceptance
umount "$J/dev"
printf 'RELEASE_REPOSITORY_VERIFIED_TEST_JAIL_STOPPED\n'
