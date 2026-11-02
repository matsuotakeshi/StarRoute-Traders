set -eu
ROOT=/home/takeshi/starroute-ports-verification-20261102
jexec srt_pkg_acceptance pw useradd srtbbs -u 62020 -d /verification/bbs -s /usr/sbin/nologin
jexec srt_pkg_acceptance install -d -m 700 -o srtbbs /verification/bbs
jexec -U srtbbs srt_pkg_acceptance env PYTHONDONTWRITEBYTECODE=1 /usr/local/bin/python3.12 /verification/harness/scripts/bbs_ui_telnet_demo.py --directory /verification/bbs/telnet-019 --liner /verification/liner > "$ROOT/logs/telnet-019-pass.log" 2>&1
tail -5 "$ROOT/logs/telnet-019-pass.log"
