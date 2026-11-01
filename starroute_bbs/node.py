"""Operator-only mode transition journal. Temporary disconnects never invoke it."""
import argparse,json,os,sqlite3,time,uuid
from pathlib import Path
from .client import Client,ClientError,save


def read(path):return json.loads(Path(path).read_text(encoding='utf8'))


def backup_db(path,dest):
    source=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    fd=os.open(dest,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd);target=sqlite3.connect(dest)
    try:
        source.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or target.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('backup invalid')
    finally:source.close();target.close()


def pause(path,value):
    c=sqlite3.connect(path)
    try:
        c.execute('BEGIN IMMEDIATE');c.execute("INSERT INTO metadata VALUES('node_paused',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(value),));c.commit()
    finally:c.close()


def join(config,new_config,failpoint=lambda step:None):
    config=Path(config);old=read(config);new=read(new_config)
    if old['mode']!='standalone' or new['mode']!='inter-bbs':raise ValueError('explicit standalone to inter-bbs transition required')
    client=Client(new,'node-check','Node verification')
    result=client.post('connect',{'attestation':client.profile['attestation'],'configuration':client.profile['configuration']},site=True)
    if not result['admitted']:raise ClientError(result['diagnostic']['code'])
    if any(Path(new['state_directory']).rglob('pending.json')):raise ClientError('OPERATION_UNCERTAIN')
    directory=config.parent/('transition-'+uuid.uuid4().hex);directory.mkdir(mode=0o700)
    backup_db(old['database'],directory/'standalone-backup.db');save(directory/'previous-config.json',old)
    journal=config.with_suffix('.transition.json')
    if journal.exists() and read(journal)['state'] not in ('COMMITTED','RECOVERED'):raise ValueError('recover existing transition first')
    record={'state':'PREPARED','kind':'JOIN','old':old,'new':new,'backup':str(directory),'at':int(time.time())};save(journal,record)
    pause(old['database'],1);failpoint('paused')
    save(config,new);record['state']='COMMITTED';save(journal,record);return {'state':'COMMITTED','backup':str(directory)}


def recover(config):
    config=Path(config);journal=config.with_suffix('.transition.json');record=read(journal)
    if record['state']=='COMMITTED':return {'state':'COMMITTED','action':'no rollback; inspect committed operations before any manual restore'}
    if record['kind']=='JOIN':
        save(config,record['old']);pause(record['old']['database'],0);record['state']='RECOVERED';save(journal,record);return {'state':'RECOVERED'}
    if record['kind']=='LEAVE':
        client=Client(record['old'],'node-check','Node verification')
        client.post('leave',{**client.target(),'confirm_bbs_id':client.profile['bbs_id']},site=True)
        settle(record['old'],client)
        save(config,record['new']);record['state']='COMMITTED';save(journal,record);return {'state':'COMMITTED'}
    raise ClientError('TRANSITION_INVALID')


def settle(config,client):
    import hashlib
    for pending in Path(config['state_directory']).rglob('pending.json'):
        owner=read(pending.parent/'owner.json');operation=read(pending)
        if owner['bbs_id']!=client.profile['bbs_id']:raise ClientError('INVALID_PENDING_OWNER')
        result=client.post('site-result',{'user_id':owner['user_id'],**{k:operation[k] for k in ('universe_id','round_id','operation','request_id')}},site=True)
        save(pending.with_name('departure-result-'+operation['request_id']+'.json'),{'operation':operation,'status':result['status'],
             'receipt_sha256':hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()})
        pending.unlink()


def leave(config,local_config):
    config=Path(config);old=read(config);new=read(local_config)
    if old['mode']!='inter-bbs' or new['mode']!='standalone':raise ValueError('explicit inter-bbs to standalone transition required')
    # New local universe must be generated/imported separately before irreversible leave.
    c=sqlite3.connect(Path(new['database']).resolve().as_uri()+'?mode=ro',uri=True)
    try:
        row=c.execute("SELECT universe_id FROM p4_rounds WHERE state='ACTIVE'").fetchone()
        if not row or c.execute('SELECT count(*) FROM players').fetchone()[0]:raise ValueError('fresh activated local universe required')
        profile=read(old['profile'])
        if row[0]==profile['configuration']['universe_id']:raise ValueError('new universe required')
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('local integrity')
    finally:c.close()
    journal=config.with_suffix('.transition.json')
    record={'state':'PREPARED','kind':'LEAVE','old':old,'new':new,'at':int(time.time())}
    save(config.with_name(config.name+'.before-leave-'+uuid.uuid4().hex),old);save(journal,record)
    client=Client(old,'node-check','Node verification')
    client.post('leave',{**client.target(),'confirm_bbs_id':client.profile['bbs_id']},site=True)
    record['state']='MASTER_LEFT';save(journal,record)
    settle(old,client)
    save(config,new);record['state']='COMMITTED';save(journal,record);return {'state':'COMMITTED'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('recover')
    for cmd in ('join','leave'):s=sub.add_parser(cmd);s.add_argument('--new-config',required=True)
    a=p.parse_args();result=recover(a.config) if a.command=='recover' else join(a.config,a.new_config) if a.command=='join' else leave(a.config,a.new_config)
    print(json.dumps(result))


if __name__=='__main__':main()
