"""TLS-verified client with scoped public cache and uncertain-result journal."""
import hashlib,json,os,ssl,time,uuid
from http.client import HTTPException
from pathlib import Path
from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler,ProxyHandler
from urllib.parse import urlsplit
from urllib.error import HTTPError,URLError

MUTATIONS={'register','buy','sell','invest','navigate','dock','buy_ship','donate','insure','bankrupt','buy_device','coordinate_depart','guild','name_star'}
CACHEABLE={'map','market','development','production','routes','news','rankings','hall','rounds','exploration'}


class ClientError(Exception):
    def __init__(self,code):super().__init__(code);self.code=code


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def save(path,data):
    path=Path(path);path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w',encoding='utf8') as f:json.dump(data,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)


class Client:
    def __init__(self,config,user_id,name,session_id=None):
        if os.name!='nt' and Path(config['profile']).stat().st_mode & 0o077:raise ClientError('INSECURE_CREDENTIAL_FILE')
        self.config=config;self.profile=json.loads(Path(config['profile']).read_text(encoding='utf8'))
        self.profile_stamp=Path(config['profile']).stat().st_mtime_ns
        self.user_id=user_id;self.name=name;self.session_id=session_id or uuid.uuid4().hex
        self.reference=self.profile['configuration'];self.token=None;self.connected=False
        url=urlsplit(config['url'])
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('','/'):raise ClientError('TLS_REQUIRED')
        self.context=ssl.create_default_context(cafile=config['ca_file']);self.context.minimum_version=ssl.TLSVersion.TLSv1_2
        scope=hashlib.sha256(json.dumps([self.profile['bbs_id'],user_id],ensure_ascii=False).encode()).hexdigest()
        self.directory=Path(config['state_directory'])/scope;self.directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        save(self.directory/'owner.json',{'bbs_id':self.profile['bbs_id'],'user_id':user_id})
        self.pending=self.directory/'pending.json';self.cache=self.directory/'public-cache.json'

    def audit(self,action,code):
        fd=os.open(self.directory/'client-audit.jsonl',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        with os.fdopen(fd,'a',encoding='utf8') as f:f.write(json.dumps({'at':int(time.time()),'action':action,'code':code})+'\n')

    def post(self,path,body,site=False):
        token=self.profile['credential'] if site else self.token
        request=Request(self.config['url'].rstrip('/')+'/v1/'+path,json.dumps(body).encode(),
                        headers={'Content-Type':'application/json','Authorization':'Bearer '+(token or '')},method='POST')
        try:
            try:response=build_opener(ProxyHandler({}),HTTPSHandler(context=self.context),NoRedirect()).open(request,timeout=self.config.get('timeout',5))
            except HTTPError as e:response=e
            with response:
                raw=response.read(2*1024*1024+1)
                if len(raw)>2*1024*1024:raise ClientError('RESPONSE_TOO_LARGE')
                value=json.loads(raw)
                if not isinstance(value,dict) or type(value.get('ok')) is not bool:raise ValueError('invalid response')
                if value['ok'] and 'result' not in value:raise ValueError('missing result')
            if not value.get('ok'):
                self.audit(path,value.get('error','INVALID_RESPONSE'));raise ClientError(value.get('error','INVALID_RESPONSE'))
            self.audit(path,'OK')
            return value['result']
        except (OSError,URLError,ValueError,HTTPException):
            self.connected=False;self.token=None;self.audit(path,'MASTER_UNAVAILABLE');raise ClientError('MASTER_UNAVAILABLE') from None

    def connect(self):
        self.connected=False
        stamp=Path(self.config['profile']).stat().st_mtime_ns
        if stamp!=self.profile_stamp:
            self.profile=json.loads(Path(self.config['profile']).read_text(encoding='utf8'));self.profile_stamp=stamp
        result=self.post('connect',{'attestation':self.profile['attestation'],'configuration':self.profile['configuration']},site=True)
        if not result['admitted'] and result['diagnostic']['code']=='LOCAL_CONFIG_MISMATCH' and set(result['diagnostic']['local_fields'])<= {'universe_id','round_id'}:
            updated=self.post('rebind',{'attestation':self.profile['attestation'],'configuration':self.profile['configuration']},site=True)
            self.profile.update(updated);save(self.config['profile'],self.profile)
            self.cache.unlink(missing_ok=True)
            result=self.post('connect',{'attestation':self.profile['attestation'],'configuration':self.profile['configuration']},site=True)
        if not result['admitted']:raise ClientError(result['diagnostic']['code'])
        self.reference=result['diagnostic']['reference']
        result=self.post('session',{'user_id':self.user_id,'display_name':self.name,'session_id':self.session_id,
                                   'universe_id':self.reference['universe_id'],'round_id':self.reference['round_id']},site=True)
        self.token=result['session_token'];self.connected=True
        if self.pending.exists():return self.resolve()
        return {'status':'connected'}

    def target(self):return {k:self.reference[k] for k in ('universe_id','round_id')}

    def language(self,value=None):
        path=self.directory/'preferences.json'
        if value is not None:
            if value not in ('ja','en'):raise ClientError('INVALID_LANGUAGE')
            save(path,{'language':value})
        return json.loads(path.read_text())['language'] if path.exists() else self.config.get('language','ja')

    def call(self,operation,arguments=None,request_id=None):
        if not self.connected:raise ClientError('MASTER_UNAVAILABLE')
        if operation in MUTATIONS and self.pending.exists():raise ClientError('OPERATION_UNCERTAIN')
        body={**self.target(),'operation':operation,'arguments':arguments or {},'request_id':request_id or uuid.uuid4().hex if operation in MUTATIONS else None}
        if operation in MUTATIONS:save(self.pending,body)
        try:result=self.post('call',body)
        except ClientError as e:
            if operation in MUTATIONS and e.code not in ('MASTER_UNAVAILABLE','SERVER_ERROR','RETRY_SAME_REQUEST'):
                self.pending.unlink(missing_ok=True)
            if e.code in ('SESSION_EXPIRED','AUTH_FAILED','WORLD_TARGET_MISMATCH','CONFIG_VERIFICATION_FAILED'):
                self.connected=False;self.token=None
                if self.cache.exists():self.cache.unlink()
            raise
        if operation in MUTATIONS:self.pending.unlink(missing_ok=True)
        if operation in CACHEABLE:
            old=json.loads(self.cache.read_text()) if self.cache.exists() else {}
            if old.get('target')!=self.target():old={'target':self.target(),'items':{}}
            value=[r for r in result if r.get('public') is True] if operation=='news' else result
            if operation=='market':
                # Personal cargo and cash-derived limits must not enter public cache.
                value={**result,'entries':[{k:v for k,v in row.items() if k not in ('owned','free_capacity','max_buy','max_sell')} for row in result['entries']]}
            old['items'][operation]={'at':int(time.time()),'value':value};save(self.cache,old)
        return result

    def cached(self,operation):
        if operation not in CACHEABLE or not self.cache.exists():raise ClientError('NO_PUBLIC_CACHE')
        data=json.loads(self.cache.read_text())
        if data['target']!=self.target() or operation not in data['items']:raise ClientError('NO_PUBLIC_CACHE')
        return {'stale':True,'target':data['target'],**data['items'][operation]}

    def resolve(self):
        if not self.pending.exists():return {'status':'none'}
        body=json.loads(self.pending.read_text())
        result=self.post('result',{k:body[k] for k in ('universe_id','round_id','operation','request_id')})
        if result['status']=='committed':self.pending.unlink()
        elif result.get('closed_round'):
            save(self.directory/('unexecuted-old-round-'+body['request_id']+'.json'),body);self.pending.unlink()
        return result

    def retry_pending(self):
        if not self.connected or not self.pending.exists():raise ClientError('NO_PENDING_OPERATION')
        body=json.loads(self.pending.read_text())
        if {k:body[k] for k in ('universe_id','round_id')}!=self.target():raise ClientError('OLD_ROUND_PENDING')
        result=self.post('call',body);self.pending.unlink();return result

    def who(self):
        if not self.connected:raise ClientError('MASTER_UNAVAILABLE')
        return self.post('who',{})

    def heartbeat(self):
        if not self.connected:raise ClientError('MASTER_UNAVAILABLE')
        return self.post('heartbeat',{})

    def logout(self):
        try:
            if self.connected:self.post('logout',{})
        finally:self.connected=False;self.token=None
