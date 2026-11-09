"""Reproducible private distfile. No credentials, DBs or build outputs."""
import argparse,gzip,hashlib,io,re,tarfile
from pathlib import Path

def build(source,output,ports):
    source=Path(source);output=Path(output);ports=Path(ports)
    version=re.search(r'__version__\s*=\s*"([^"]+)"',(source/'starroute/__init__.py').read_text()).group(1)
    name='starroute-traders-'+version
    paths=[]
    for folder in ('starroute','starroute_bbs','srt_universe_generator','examples','tests','scripts','ci','.github'):
        paths.extend(p for p in (source/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    paths.append(source/'PORTS_COMPLETE.md')
    for p in paths:
        if p.suffix in ('.db','.key','.pem') or p.name in ('node.json','master.json'):raise ValueError('private runtime file')
    output.mkdir(parents=True,exist_ok=True);archive=output/(name+'.tar.gz')
    with archive.open('wb') as raw,gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0) as gz,tarfile.open(fileobj=gz,mode='w|') as tar:
        for p in sorted(paths):
            data=p.read_bytes();info=tarfile.TarInfo(name+'/'+p.relative_to(source).as_posix())
            # ZIP consumers require DOS timestamps >= 1980; keep a fixed epoch.
            info.size=len(data);info.mode=0o644;info.mtime=315532800;tar.addfile(info,io.BytesIO(data))
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    for port in (ports/'games').glob('starroute-traders*'):
        (port/'distinfo').write_text(f'TIMESTAMP = 1793577600\nSHA256 ({archive.name}) = {digest}\nSIZE ({archive.name}) = {archive.stat().st_size}\n',encoding='utf8',newline='\n')
    return archive,digest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',default=str(Path(__file__).resolve().parents[1]));p.add_argument('--output',required=True);p.add_argument('--ports',required=True);a=p.parse_args()
    print(*build(a.source,a.output,a.ports))
