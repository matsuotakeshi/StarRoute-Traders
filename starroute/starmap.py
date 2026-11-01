"""ASCII terminal projection, independent of engine and persistence."""
from .model import integer

WIDTH,HEIGHT=240,120


def render(planets,position,*,width=78,height=20,names=False,color=True,bounds=(240,120),docked_id=None):
    integer(width,1,WIDTH);integer(height,1,HEIGHT)
    # Old small universes are projected without changing their simulation distances.
    def point(xy):
        return [max(0,min(WIDTH-1,xy[0]*(WIDTH-1)//max(1,bounds[0]-1))),
                max(0,min(HEIGHT-1,xy[1]*(HEIGHT-1)//max(1,bounds[1]-1)))]
    ship=point(position);left=max(0,min(WIDTH-width,ship[0]-width//2));top=max(0,min(HEIGHT-height,ship[1]-height//2))
    grid=[[' ']*width for _ in range(height)];marks={};green=set()
    for p in planets:
        x,y=point(p['position']);x-=left;y-=top
        if 0<=x<width and 0<=y<height:
            marks[x,y]='*'
            if p['planet_id']==docked_id:green.add((x,y))
    sx,sy=ship[0]-left,ship[1]-top
    # A docked planet remains a green *, with the ship + adjacent if a cell is free.
    if docked_id and (sx,sy) in marks:
        for x,y in ((sx+1,sy),(sx-1,sy),(sx,sy+1),(sx,sy-1)):
            if 0<=x<width and 0<=y<height and (x,y) not in marks:sx,sy=x,y;break
    marks[sx,sy]='+';green.add((sx,sy))
    if names:
        for p in planets:
            x,y=point(p['position']);x=x-left+2;y-=top
            if not 0<=y<height:continue
            label=''.join(ch for ch in p['name_en'] if 32<=ord(ch)<127)
            if x+len(label)>width:x=max(0,x-3-len(label))
            for i,ch in enumerate(label):
                if 0<=x+i<width and (x+i,y) not in marks and grid[y][x+i]==' ':grid[y][x+i]=ch
    for (x,y),ch in marks.items():grid[y][x]=ch
    return '\n'.join(''.join(('\x1b[32m'+ch+'\x1b[0m') if color and (x,y) in green else ch
                             for x,ch in enumerate(row)) for y,row in enumerate(grid))
