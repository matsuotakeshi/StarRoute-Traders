"""Cell-sized pure terminal rendering, independent of game state and IO."""
from .terminal import clean,clip,width

def pad(text,columns):
    value=clip(text,columns)
    return value+' '*max(0,columns-width(value))

def wrap(text,columns):
    result=[]
    for line in str(text).split('\n'):
        part=''
        for ch in clean(line):
            if width(part+ch)>columns:
                result.append(part);part=''
            part+=ch
        result.append(part)
    return result

def geometry(columns,rows):
    w=max(19,columns-1);h=max(4,rows-8)
    if columns>=60:
        right=min(32,max(26,w//3+4));return w,h,w-right-3,right,False
    map_h=max(2,h//3);return w,h,w-2,w-2,True

def _chart(definition,flight,status,w,h,names=False,ansi=False,center=None):
    x,y=flight.get('position',[0,0]);cx,cy=center or (x,y)
    left=max(0,min(240-w,cx-w//2));top=max(0,min(120-h,cy-h//2))
    grid=[[' ']*w for _ in range(h)];marks=[];occupied=set()
    for p in definition.get('planets',[]):
        coords=p.get('coordinates')
        if not coords:continue
        px,py=coords['x']-left,coords['y']-top
        if 0<=px<w and 0<=py<h:
            marks.append((px,py,p));occupied.add((px,py))
    occupied.add((x-left,y-top))
    for px,py,p in marks:
        grid[py][px]='*'
        if names:
            tx=px+1
            for ch in ' '+clean(p['name']):
                cells=width(ch)
                if not cells:continue
                if tx+cells>w or any((xx,py) in occupied for xx in range(tx,tx+cells)):break
                grid[py][tx]=ch
                for xx in range(tx+1,tx+cells):grid[py][xx]=''
                tx+=cells
    sx,sy=x-left,y-top;highlight=None
    if 0<=sx<w and 0<=sy<h:
        grid[sy][sx]='+' if status.get('destination_id') or status.get('planet_id') is None else '*';highlight=(sx,sy)
    rows=[]
    for py,row in enumerate(grid):
        rows.append(''.join('\x1b[32m'+ch+'\x1b[0m' if ansi and (px,py)==highlight else ch for px,ch in enumerate(row)))
    return rows

def starmap(definition,flight,status,w,h,names=False,ansi=False,center=None):
    """Axes occupy reserved cells, never the planet/ship drawing area."""
    iw=min(240,max(1,w-4));ih=min(120,max(1,h-2))
    x,y=flight.get('position',[0,0]);cx,cy=center or (x,y)
    left=max(0,min(240-iw,cx-iw//2));top=max(0,min(120-ih,cy-ih//2))
    axis=[' ']*iw
    for value in range(((left+4)//5)*5,left+iw,5):
        offset=value-left;label=str(value)
        if offset+len(label)<=iw:axis[offset:offset+len(label)]=label
    rows=[pad('X   '+''.join(axis),w)]
    chart=_chart(definition,flight,status,iw,ih,names,ansi,center)
    for i,row in enumerate(chart):
        absolute=top+i;label=f'{absolute:3} ' if absolute%5==0 or i==0 else '    '
        rows.append(label+row+' '*max(0,w-iw-4))
    rows.append(pad(f'POS X={x} Y={y}',w))
    return rows[:h]


def compose(columns,rows,title,summary,map_rows,panel,footer,notice,prompt):
    w,h,lw,rw,stacked=geometry(columns,rows)
    lines=[clip(title,w),clip(summary,w)]
    if not stacked:
        border='+'+'-'*lw+'+'+'-'*rw+'+'
        lines.append(border)
        for n in range(h):
            # Map lines already have fixed cell width; preserve their ANSI colours.
            left=map_rows[n] if n<len(map_rows) else ' '*lw
            lines.append('|'+left+'|'+pad(panel[n] if n<len(panel) else '',rw)+'|')
        lines.append(border)
    else:
        mh=max(2,h//3);lines.append('+'+'-'*lw+'+')
        lines.extend('|'+line+'|' for line in map_rows[:mh]);lines.append('+'+'-'*lw+'+')
        lines.extend(clip(line,w) for line in panel[:h-mh])
        while len(lines)<rows-4:lines.append('')
    lines.extend([clip(footer,w),clip(notice,w),clip(prompt,w)])
    return lines[:rows-1]
