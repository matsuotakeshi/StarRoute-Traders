set -eu
ROOT=/home/takeshi/starroute-ports-verification-20261102
/usr/local/bin/python3.12 - "$ROOT/runtime/verification/harness/scripts/bbs_ui_telnet_demo.py" <<'PY'
import sys
from pathlib import Path
p=Path(sys.argv[1]);s=p.read_text();start=s.index("        wrapper=home/'door';");end=s.index("        doors=home/'doors.conf'",start)
s=s[:start]+'''        wrapper=home/'door';wrapper.write_text('#!'+sys.executable+'\\nimport os\\nos.execv("/usr/local/bin/starroute-door", ["starroute-door", "--config", '+repr(str(config))+'])\\n');wrapper.chmod(0o700)
'''+s[end:];p.write_text(s)
PY
jexec srt_pkg_acceptance env PYTHONDONTWRITEBYTECODE=1 /usr/local/bin/python3.12 /verification/harness/scripts/bbs_ui_telnet_demo.py --directory /verification/telnet-019c --liner /verification/liner > "$ROOT/logs/telnet-019c.log" 2>&1
tail -5 "$ROOT/logs/telnet-019c.log"
