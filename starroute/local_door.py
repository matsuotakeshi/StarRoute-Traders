"""Trusted local backend; never included in the remote BBS client distribution."""
from .network import Gateway
from . import network_security as security
from .repository import SQLiteRepository
from .clock import SystemClock
from .model import GameError
from starroute_bbs.client import ClientError
import uuid,json


class LocalDoor:
    def __init__(self,config,user_id,name,clock=None):
        from pathlib import Path
        self.config=config;self.profile=json.loads(Path(config['profile']).read_text(encoding='utf8'));self.user=user_id;self.name=name
        self.session_id=uuid.uuid4().hex;self.gateway=Gateway(config['database'],Path(config['reference_key']).read_bytes(),clock)
        self.token=None;self.reference=self.profile['configuration'];self.pending=None
    def post(self,path,body,site=False):
        try:return self.gateway.dispatch(path,self.profile['credential'] if site else self.token,body)
        except GameError as e:raise ClientError(e.code) from None
    def connect(self):
        response=self.post('connect',{'attestation':self.profile['attestation'],'configuration':self.profile['configuration']},True)
        if not response['admitted'] and response['diagnostic']['code']=='LOCAL_CONFIG_MISMATCH' and set(response['diagnostic']['local_fields'])<= {'universe_id','round_id'}:
            from starroute_bbs.client import save
            self.profile.update(self.post('rebind',{'attestation':self.profile['attestation'],'configuration':self.profile['configuration']},True));save(self.config['profile'],self.profile)
            response=self.post('connect',{'attestation':self.profile['attestation'],'configuration':self.profile['configuration']},True)
        if not response['admitted']:raise ClientError(response['diagnostic']['code'])
        self.reference=response['diagnostic']['reference']
        result=self.post('session',{'user_id':self.user,'display_name':self.name,'session_id':self.session_id,**self.target()},True)
        self.token=result['session_token'];return {'status':'connected'}
    def target(self):return {k:self.reference[k] for k in ('universe_id','round_id')}
    def language(self,value=None):
        r=SQLiteRepository(self.gateway.database)
        try:
            pid=r.resolve_account(self.profile['bbs_id'],self.user)
            if value is not None:r.set_language(pid,value)
            return r.get_language(pid,self.config.get('language','ja'))
        finally:r.close()
    def call(self,operation,arguments=None,request_id=None):
        from starroute_bbs.client import MUTATIONS
        return self.post('call',{**self.target(),'operation':operation,'arguments':arguments or {},'request_id':request_id or uuid.uuid4().hex if operation in MUTATIONS else None})
    def who(self):return self.post('who',{})
    def heartbeat(self):return self.post('heartbeat',{})
    def logout(self):
        if self.token:self.post('logout',{});self.token=None
    def resolve(self):return {'status':'none'}
    def retry_pending(self):raise ClientError('NO_PENDING_OPERATION')
    def cached(self,operation):raise ClientError('NO_PUBLIC_CACHE')
