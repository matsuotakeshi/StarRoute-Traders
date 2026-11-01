"""Apply the isolated-build NAWS-to-PTY fix. Never invoke against production.

Usage: python prepare_resize_copy.py COPY_DIRECTORY
The caller first creates a fresh copy of Liner notes source. Original sources
and binaries are not edited by the StarRoute installation.
"""
from pathlib import Path
import sys,difflib,json,hashlib
root=Path(sys.argv[1]).resolve()
if not (root/'STARROUTE_ISOLATED_COPY').is_file():raise SystemExit('isolated-copy marker required')
changes={}
for name in ('doors.h','doors.c','runtime.c'):
 p=root/'src'/name;old=p.read_text();new=old
 if name=='doors.h':new=old.replace('void door_stop(Door *);','int door_resize(Door *,unsigned,unsigned);\nvoid door_stop(Door *);')
 elif name=='doors.c':new=old+'''
/* Isolated StarRoute integration: propagate Telnet NAWS to the live PTY. */
int door_resize(Door *d,unsigned columns,unsigned rows) {
#ifndef _WIN32
    if(!d || columns<20 || columns>240 || rows<12 || rows>120)return 0;
    struct winsize current={0};
    if(ioctl(d->fd,TIOCGWINSZ,&current))return 0;
    if(current.ws_col==columns && current.ws_row==rows)return 1;
    current.ws_col=(unsigned short)columns;current.ws_row=(unsigned short)rows;
    return ioctl(d->fd,TIOCSWINSZ,&current)==0;
#else
    (void)d;(void)columns;(void)rows;return 0;
#endif
}
'''
 else:
  needle='    if(!done && c->queued<=OUT_CAP/2)done=door_pump(c->door,zbytes,c,now);'
  if old.count(needle)!=1:raise SystemExit('unexpected Liner notes source')
  new=old.replace(needle,'''    if(c->terminal.mode==TERMINAL_TELNET && c->terminal.telnet.width && c->terminal.telnet.height) {
        session_dimensions(s,c->terminal.telnet.width,c->terminal.telnet.height);
        door_resize(c->door,s->columns,s->rows);
    }
'''+needle)
 if new==old:raise SystemExit('unexpected source')
 p.write_text(new);changes[name]={'before':hashlib.sha256(old.encode()).hexdigest(),'after':hashlib.sha256(new.encode()).hexdigest()}
 with (root/'starroute-resize.patch').open('a') as f:f.writelines(difflib.unified_diff(old.splitlines(True),new.splitlines(True),'a/src/'+name,'b/src/'+name))
(root/'starroute-resize-changes.json').write_text(json.dumps(changes,indent=2))
