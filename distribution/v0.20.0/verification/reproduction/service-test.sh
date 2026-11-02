set -eu
ROOT=/home/takeshi/starroute-ports-verification-20261102
J="$ROOT/runtime"
jexec srt_pkg_acceptance pw useradd starroute -u 62019 -d /nonexistent -s /usr/sbin/nologin
jexec srt_pkg_acceptance mkdir -m 700 /verification/service-world
jexec srt_pkg_acceptance cp /verification/pkg-backup.db /verification/service-world/game.db
jexec srt_pkg_acceptance cp /var/db/starroute-traders/world/reference.key /verification/service-world/reference.key
jexec srt_pkg_acceptance openssl req -x509 -newkey rsa:2048 -nodes -keyout /verification/service-world/server-key.pem -out /verification/service-world/server-cert.pem -days 1 -subj /CN=localhost -addext subjectAltName=DNS:localhost,IP:127.0.0.1 >/dev/null 2>&1
cat > "$J/usr/local/etc/starroute-traders/master.json" <<'EOF'
{"database":"/verification/service-world/game.db","reference_key":"/verification/service-world/reference.key","host":"127.0.0.1","port":18493,"certificate":"/verification/service-world/server-cert.pem","private_key":"/verification/service-world/server-key.pem"}
EOF
jexec srt_pkg_acceptance chown -R starroute:starroute /verification/service-world
jexec srt_pkg_acceptance chmod -R go-rwx /verification/service-world
jexec srt_pkg_acceptance sysrc starroute_master_enable=YES
jexec srt_pkg_acceptance service starroute_master start
sleep 2
jexec srt_pkg_acceptance service starroute_master status
PID=$(cat "$J/var/run/starroute-traders/master.pid")
test "$(jexec srt_pkg_acceptance ps -o user= -p "$PID" | tr -d ' ')" = starroute
printf 'NONROOT_SERVICE_USER_CONFIRMED\n'
jexec srt_pkg_acceptance service starroute_master restart
sleep 2
jexec srt_pkg_acceptance service starroute_master status
jexec srt_pkg_acceptance service starroute_master stop
if jexec srt_pkg_acceptance service starroute_master status; then exit 1; fi
jexec srt_pkg_acceptance sysrc starroute_master_enable=NO
printf 'RC_START_STATUS_RESTART_STOP_PASS\n'
