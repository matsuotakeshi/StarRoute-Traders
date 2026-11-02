set -eu
ROOT=/home/takeshi/starroute-ports-verification-20261102
J="$ROOT/runtime"
cp "$ROOT/source-final2/tests/phase5_support.py" "$J/verification/harness/tests/"
touch "$J/verification/harness/tests/__init__.py"
cp -Rp "$ROOT/source-final2/examples" "$J/verification/harness/"
/usr/local/bin/python3.12 - "$J" <<'PY'
import sys
from pathlib import Path
j=Path(sys.argv[1]);h=j/'verification/harness'
for name in ('bbs_ui_telnet_demo.py','phase5_telnet_demo.py'):
 p=h/'scripts'/name;s=p.read_text()
 s=s.replace('sys.path.insert(0,str(ROOT))',"sys.path.insert(0,str(ROOT));sys.path.insert(0,'/usr/local/libexec/starroute-traders')")
 if name=='bbs_ui_telnet_demo.py':
  start=s.index("        wrapper=home/'door';")
  end=s.index("        doors=home/'doors.conf'",start)
  s=s[:start]+'''        wrapper=home/'door';wrapper.write_text('#!/bin/sh\\nexec /usr/local/bin/starroute-door --config '+str(config)+'\\n');wrapper.chmod(0o700)
'''+s[end:]
  s=s.replace("    base=Path(a.directory);", "    import starroute,starroute_bbs;print('INSTALLED_MODULES',starroute.__file__,starroute_bbs.__file__,flush=True)\n    assert starroute.__file__.startswith('/usr/local/libexec/starroute-traders/')\n    base=Path(a.directory);")
 p.write_text(s)
PY
printf 'HARNESS_INSTALLED_LAUNCHER_READY\n'
