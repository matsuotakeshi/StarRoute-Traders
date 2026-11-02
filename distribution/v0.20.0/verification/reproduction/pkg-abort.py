"""Kill pkg at its pre-commit confirmation prompt in the disposable jail."""
import os,pty,select,subprocess,time
master,slave=pty.openpty()
p=subprocess.Popen(['pkg','-o','ASSUME_ALWAYS_YES=no','upgrade','-g','-r','StarRouteTest','starroute-traders*'],stdin=slave,stdout=slave,stderr=slave,close_fds=True)
os.close(slave);buf=b'';deadline=time.monotonic()+60
try:
 while time.monotonic()<deadline:
  if select.select([master],[],[],1)[0]:buf+=os.read(master,65536)
  if b'[y/N]' in buf or b'[Y/n]' in buf:
   p.kill();p.wait();assert p.returncode<0
   print('PKG_SIGKILL_AT_PRECOMMIT_PROMPT',p.returncode);break
  if p.poll() is not None:raise AssertionError(buf.decode(errors='replace'))
 else:raise TimeoutError('pkg confirmation prompt missing')
finally:
 if p.poll() is None:p.kill();p.wait()
 os.close(master)
versions=subprocess.check_output(['pkg','query','-g','%n %v','starroute-traders*'],text=True)
assert all(line.endswith(' 0.19.0') for line in versions.splitlines()),versions
print(versions);print('INTERRUPTED_UPDATE_LEFT_OLD_PACKAGES_INTACT')
