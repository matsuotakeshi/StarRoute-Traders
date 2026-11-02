set -eu
ROOT=/home/takeshi/starroute-ports-verification-20261102
jexec -U srtbbs srt_pkg_acceptance env PYTHONDONTWRITEBYTECODE=1 /usr/local/bin/python3.12 /verification/harness/scripts/bbs_ui_telnet_demo.py --directory /verification/bbs/telnet-020 --liner /verification/liner > "$ROOT/logs/telnet-020.log" 2>&1
tail -5 "$ROOT/logs/telnet-020.log"

