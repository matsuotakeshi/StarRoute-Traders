"""Read-only viewport state; departure is a separate confirmed engine request."""
from .client import ClientError

def open_view(m):m.push('MAP_VIEW',None,'map_view')
def handle(m,line):
    if m.state not in ('VIEW_X','VIEW_Y'):return False
    if line.lower() in ('q','quit','exit','menu','main','m','back','?','help'):return False
    if line.lower()==':cancel':m.back();return True
    if not line:return True
    if not line.isascii() or not line.isdigit():raise ClientError('INVALID_COORDINATES')
    value=int(line)
    if value>(239 if m.state=='VIEW_X' else 119):raise ClientError('INVALID_COORDINATES')
    if m.state=='VIEW_X':m.push('VIEW_Y',{'x':value},'map_view')
    else:m.view_center=[m.data['x'],value];m.state='MAP_VIEW';m.action='map_view';m.data=None;m.page=0
    return True

def select(m,key):
    if key=='1':m.push('VIEW_X',{},'map_view')
    elif key=='2':m.view_center=None
    elif key=='3':
        m.allowed('coordinates')
        if not m.info.get('exploration',{}).get('device'):raise ClientError('DEVICE_REQUIRED')
        if m.view_center is None:raise ClientError('VIEW_TARGET_REQUIRED')
        m.selected=dict(zip(('x','y'),m.view_center));m.push('COORD_MODE',[None]+m.info['exploration']['coordinate_warps'],'coordinates')
    else:raise ClientError('INVALID_SELECTION')

def panel(m):
    if m.state in ('VIEW_X','VIEW_Y'):return [m.text('map_view'),m.text('view_only'),m.text('enter_x' if m.state=='VIEW_X' else 'enter_y'),m.text('literal_cancel')]
    if m.state=='MAP_VIEW':return [m.text('map_view'),m.text('view_only'),m.text('view_target',target=m.view_center or m.text('follow_ship')),m.text('view_jump'),m.text('view_follow'),m.text('view_depart'),m.text('back_keys')]
    return None
