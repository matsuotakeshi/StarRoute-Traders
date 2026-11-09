"""Exploration UI only: prices, travel times and mutations come from the server."""
from .client import ClientError
from .screen import wrap
import time
ACTIONS=('device','coordinates','return_planet','guild','notebook','name_star','discoverers')

def open_menu(m,action):
    if action=='explore':m.push('EXPLORE',list(ACTIONS),'explore')
    elif action=='device':m.confirm('buy_device',{},m.facts({'cost':m.info['exploration']['device_price']}))
    elif action=='guild':m.confirm('guild',{},m.facts({'cost':m.info['exploration']['guild_price']}))
    elif action=='coordinates':m.push('COORD_X',{},'coordinates')
    elif action=='return_planet':m.push('RETURN',m.backend.call('nearby'),'return_planet')
    elif action=='name_star':m.push('STAR_NAME',None,'name_star')
    elif action=='notebook':
        lines=[]
        for r in m.backend.call('notebook'):
            lines+=wrap(time.strftime('%Y-%m-%d %H:%M UTC',time.gmtime(r['at']))+' '+m.text('rumor_'+str(r['template']),planet=r.get('planet_name',planet_name(m,r['planet_id']))),m.size()[1])+['']
        m.push('TEXT',lines,'notebook')
    elif action=='discoverers':m.show('discoverers',m.backend.call('discoverers'))
    else:return False
    return True

def planet_name(m,pid):
    return next((p['name'] for p in m.definition.get('planets',[]) if p['planet_id']==pid),pid)

def travel(m,mode='normal',level=None):
    args={**m.selected,'mode':mode,'level':level}
    q=m.backend.call('coordinate_quote',args)
    m.confirm('coordinate_depart',{**args,'quote_id':q['quote_id']},m.facts(q)+m.facts({'cash':m.status.get('cash')}),q)

def handle(m,line):
    key=line.lower()
    if m.state in ('COORD_X','COORD_Y','STAR_NAME'):
        if key==':cancel':m.back();return True
        if not line:return True
        if m.state=='STAR_NAME':
            m.confirm('name_star',{'value':line},m.facts({'personal_name':line}));return True
        if not line.isascii() or not line.isdigit():raise ClientError('INVALID_COORDINATES')
        value=int(line);axis='x' if m.state=='COORD_X' else 'y'
        if value>(239 if axis=='x' else 119):raise ClientError('INVALID_COORDINATES')
        if axis=='x':m.push('COORD_Y',{'x':value},'coordinates')
        else:
            m.selected={**m.data,'y':value};m.push('COORD_MODE',[None]+m.info['exploration']['coordinate_warps'],'coordinates')
        return True
    return False

def select(m,line):
    row=m.selected_row(line)
    if m.state=='EXPLORE':open_menu(m,row)
    elif m.state=='RETURN':
        m.selected={'x':row['x'],'y':row['y']};m.push('COORD_MODE',[None]+m.info['exploration']['coordinate_warps'],'coordinates')
    elif m.state=='COORD_MODE':travel(m,'normal' if row is None else 'warp',row)

def row(m,n,value):
    if m.state=='EXPLORE':return str(n)+' '+m.text(value)
    if m.state=='RETURN':return str(n)+' '+value['name']+' ('+str(value['x'])+','+str(value['y'])+') d='+str(value.get('navigation_distance',value['distance']))
    if m.state=='COORD_MODE':return str(n)+' '+(m.text('normal_free') if value is None else 'Warp '+str(value))
    return None

def panel(m):
    if m.state in ('COORD_X','COORD_Y','STAR_NAME'):
        return [m.text(m.action),m.text({'COORD_X':'enter_x','COORD_Y':'enter_y','STAR_NAME':'enter_name'}[m.state]),m.text('literal_cancel')]
    return None
