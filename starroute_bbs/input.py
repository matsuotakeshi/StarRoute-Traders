"""Bounded UTF-8 input with idle/resize polling on POSIX PTYs."""
import os,codecs

class Input:
    def __init__(self,stream):self.stream=stream;self.buffer='';self.saved=None;self.after_cr=False;self.decoder=codecs.getincrementaldecoder('utf8')('replace')
    def __enter__(self):
        try:
            if os.name=='posix' and self.stream.isatty():
                import termios,tty
                self.fd=self.stream.fileno();self.saved=termios.tcgetattr(self.fd);tty.setcbreak(self.fd)
                current=termios.tcgetattr(self.fd);current[0]&=~termios.ICRNL;termios.tcsetattr(self.fd,termios.TCSANOW,current)
        except (OSError,AttributeError,ValueError):self.saved=None
        return self
    def read(self,timeout=.25):
        if self.saved is None:
            line=self.stream.readline(4097)
            return None if not line else line.rstrip('\r\n')
        import select
        if not select.select([self.fd],[],[],timeout)[0]:return False
        raw=os.read(self.fd,1)
        if not raw:return None
        ch=self.decoder.decode(raw)
        if ch=='\n' and self.after_cr:self.after_cr=False;return False
        if ch:self.after_cr=ch=='\r'
        if ch in ('\r','\n'):
            result=self.buffer;self.buffer='';return result
        if ch in ('\x7f','\b'):self.buffer=self.buffer[:-1]
        elif ch=='\x04':return None
        elif ch and ch>=' ' and ch!='\x1b' and len(self.buffer)<4096:self.buffer+=ch
        return False
    def __exit__(self,*args):
        if self.saved is not None:
            import termios
            termios.tcsetattr(self.fd,termios.TCSANOW,self.saved)
