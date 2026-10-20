"""Offline, deterministic industrial art layer, separate from gameplay physics.

Detailed geometry is batched into one mesh per material. Machines and structures
use a small set of explicit box colliders outside the race corridor. No runtime
downloads, random assets, moving scenery or changes to robot/contact parameters.
"""
from collections import defaultdict
import json
import math
from pathlib import Path
import struct
import xml.etree.ElementTree as E
import numpy as np
from world import el

PALETTE={
    'steel':(.14,.19,.23,1), 'edge':(.29,.36,.40,1),
    'silver':(.61,.68,.70,1), 'white':(.86,.89,.86,1),
    'dark':(.055,.075,.088,1), 'teal':(.045,.35,.36,1),
    'blue':(.10,.36,.69,1), 'orange':(.90,.32,.075,1),
    'yellow':(.96,.67,.13,1), 'red':(.65,.12,.09,1),
    'green':(.14,.63,.40,1), 'glass':(.16,.32,.40,1),
    'wood':(.46,.31,.18,1), 'carton':(.65,.48,.30,1),
    'floor':(.28,.33,.35,1), 'paint':(.53,.58,.58,1),
    'light':(.78,.94,1.,1),
}

# Compact CAD stencil lettering: merged horizontal runs, not texture downloads.
FONT={
 'A':'01110/10001/10001/11111/10001/10001/10001',
 'B':'11110/10001/10001/11110/10001/10001/11110',
 'C':'01111/10000/10000/10000/10000/10000/01111',
 'D':'11110/10001/10001/10001/10001/10001/11110',
 'E':'11111/10000/10000/11110/10000/10000/11111',
 'F':'11111/10000/10000/11110/10000/10000/10000',
 'G':'01111/10000/10000/10111/10001/10001/01111',
 'H':'10001/10001/10001/11111/10001/10001/10001',
 'I':'11111/00100/00100/00100/00100/00100/11111',
 'J':'00111/00010/00010/00010/10010/10010/01100',
 'K':'10001/10010/10100/11000/10100/10010/10001',
 'L':'10000/10000/10000/10000/10000/10000/11111',
 'M':'10001/11011/10101/10101/10001/10001/10001',
 'N':'10001/11001/11001/10101/10011/10011/10001',
 'O':'01110/10001/10001/10001/10001/10001/01110',
 'P':'11110/10001/10001/11110/10000/10000/10000',
 'Q':'01110/10001/10001/10001/10101/10010/01101',
 'R':'11110/10001/10001/11110/10100/10010/10001',
 'S':'01111/10000/10000/01110/00001/00001/11110',
 'T':'11111/00100/00100/00100/00100/00100/00100',
 'U':'10001/10001/10001/10001/10001/10001/01110',
 'V':'10001/10001/10001/10001/10001/01010/00100',
 'W':'10001/10001/10001/10101/10101/11011/10001',
 'X':'10001/10001/01010/00100/01010/10001/10001',
 'Y':'10001/10001/01010/00100/00100/00100/00100',
 'Z':'11111/00001/00010/00100/01000/10000/11111',
 '0':'01110/10001/10011/10101/11001/10001/01110',
 '1':'00100/01100/00100/00100/00100/00100/01110',
 '2':'01110/10001/00001/00010/00100/01000/11111',
 '3':'11110/00001/00001/01110/00001/00001/11110',
 '4':'00010/00110/01010/10010/11111/00010/00010',
 '5':'11111/10000/10000/11110/00001/00001/11110',
 '6':'01110/10000/10000/11110/10001/10001/01110',
 '7':'11111/00001/00010/00100/01000/01000/01000',
 '8':'01110/10001/10001/01110/10001/10001/01110',
 '9':'01110/10001/10001/01111/00001/00001/01110',
 '-':'00000/00000/00000/11111/00000/00000/00000',
 '.':'00000/00000/00000/00000/00000/00110/00110',
 '/':'00001/00001/00010/00100/01000/10000/10000',
 ' ':'00000/00000/00000/00000/00000/00000/00000',
}


class Geometry:
    def __init__(self):
        self.triangles=defaultdict(list)
        self.solids=[]
        self.labels=[]

    def box(self,material,center,size,yaw=0):
        points=np.array([(x,y,z) for z in (-.5,.5) for y in (-.5,.5) for x in (-.5,.5)])*size
        c,s=math.cos(yaw),math.sin(yaw)
        points=points@np.array(((c,s,0),(-s,c,0),(0,0,1)))+center
        faces=((0,2,3,1),(4,5,7,6),(0,1,5,4),(2,6,7,3),(0,4,6,2),(1,3,7,5))
        for a,b,c,d in faces:
            self.triangles[material].extend((points[[a,b,c]],points[[a,c,d]]))

    def cylinder(self,material,a,b,radius,sides=12):
        a,b=np.array(a,dtype=float),np.array(b,dtype=float)
        axis=(b-a)/np.linalg.norm(b-a)
        u=np.cross(axis,[0,0,1] if abs(axis[2])<.9 else [1,0,0]);u/=np.linalg.norm(u)
        v=np.cross(axis,u)
        ring=[radius*(u*math.cos(i*2*math.pi/sides)+v*math.sin(i*2*math.pi/sides)) for i in range(sides)]
        for i,p in enumerate(ring):
            q=ring[(i+1)%sides]
            self.triangles[material].extend((np.array([a+p,a+q,b+q]),np.array([a+p,b+q,b+p]),np.array([a,a+q,a+p]),np.array([b,b+p,b+q])))

    def solid(self,name,center,size):
        self.solids.append(dict(name=name,center=center,size=size))

    def text(self,text,center,height,material='white',facing='south'):
        """Signs face -Y, -X (entry), +X (return), or +Z (floor)."""
        self.labels.append(text)
        unit=height/7; width=(len(text)*6-1)*unit
        for index,char in enumerate(text):
            for row,line in enumerate(FONT[char].split('/')):
                col=0
                while col<5:
                    if line[col]=='0':col+=1;continue
                    end=col+1
                    while end<5 and line[end]=='1':end+=1
                    u=-width/2+(index*6+(col+end)/2)*unit
                    v=height/2-(row+.5)*unit
                    x,y,z=center
                    if facing=='south':self.box(material,(x+u,y,z+v),((end-col)*unit,.012,unit))
                    elif facing=='entry':self.box(material,(x,y-u,z+v),(.012,(end-col)*unit,unit))
                    elif facing=='return':self.box(material,(x,y+u,z+v),(.012,(end-col)*unit,unit))
                    else:self.box(material,(x-v,y-u,z),(unit,(end-col)*unit,.001))
                    col=end

    def write(self,world,directory):
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        model=el(world,'model',name='facility_detail');el(model,'static','true')
        link=el(model,'link',name='architecture')
        for name,triangles in sorted(self.triangles.items()):
            path=directory/(name+'.stl')
            with path.open('wb') as stream:
                stream.write(b'ENRO deterministic facility mesh'.ljust(80,b'\0'))
                stream.write(struct.pack('<I',len(triangles)))
                for tri in triangles:
                    normal=np.cross(tri[1]-tri[0],tri[2]-tri[0]);normal/=np.linalg.norm(normal)
                    stream.write(struct.pack('<12fH',*normal,*tri.flatten(),0))
            visual=el(link,'visual',name=name)
            el(el(el(visual,'geometry'),'mesh'),'uri',path.resolve().as_uri())
            mat=el(visual,'material');color=' '.join(map(str,PALETTE[name]))
            el(mat,'ambient',color);el(mat,'diffuse',color)
            el(mat,'specular','.18 .18 .18 1' if name in ('silver','steel','glass') else '.02 .02 .02 1')
            pbr=el(el(mat,'pbr'),'metal')
            el(pbr,'roughness',.38 if name in ('silver','glass') else .65 if name in ('steel','edge') else .9)
            el(pbr,'metalness',.55 if name in ('silver','steel','edge') else 0.)
            el(visual,'cast_shadows','false' if name in ('light','paint','white','yellow','green') else 'true')
            if name=='light':el(mat,'emissive','.45 .65 .72 1')
        for solid in self.solids:
            collision=el(link,'collision',name=solid['name'])
            el(collision,'pose',' '.join(map(str,solid['center']))+' 0 0 0')
            el(el(el(collision,'geometry'),'box'),'size',' '.join(map(str,solid['size'])))
        manifest=dict(triangles=sum(map(len,self.triangles.values())),materials=len(self.triangles),
                      colliders=self.solids,labels=self.labels)
        (directory/'manifest.json').write_text(json.dumps(manifest,indent=2))
        return manifest


def rack(g,x,y):
    for dx in (-1.4,1.4):
        for dy in (-.55,.55):
            g.box('orange',(x+dx,y+dy,1.5),(.10,.10,3.))
    for level in (.22,1.25,2.28):
        g.box('steel',(x,y,level),(2.9,1.2,.12))
        for n in range(3):
            bx=x-1+n
            g.box('wood',(bx,y,level+.13),(.84,.91,.14))
            g.box('carton',(bx,y,level+.49),(.72,.78,.58))
            g.box('white',(bx,y-.394,level+.49),(.23,.012,.15))
            g.box('wood',(bx,y,level+.784),(.08,.79,.01))
    g.solid(f'rack_{x}_{y}',(x,y,1.5),(2.95,1.2,3.))


def machine(g,x,y,n):
    g.box('dark',(x,y,.16),(2.25,1.7,.32))
    g.box('teal',(x,y,1.1),(2.1,1.55,1.7))
    g.box('white',(x,y-.79,1.2),(1.8,.08,1.35))
    for dx in (-.44,.44):
        g.box('glass',(x+dx,y-.84,1.34),(.77,.05,.89))
        g.box('silver',(x+dx+.29,y-.90,1.15),(.045,.04,.31))
    g.box('steel',(x+.91,y-1.,1.3),(.38,.22,.62))
    g.box('light',(x+.91,y-1.12,1.43),(.26,.015,.23))
    for dx in (-.07,.07):g.cylinder('red' if dx<0 else 'green',(x+.91+dx,y-1.13,1.13),(x+.91+dx,y-1.16,1.13),.028)
    for i in range(7):g.box('dark',(x-.75+i*.25,y-.795,.5),(.15,.012,.04))
    g.cylinder('steel',(x+.75,y,1.96),(x+.75,y,2.45),.035)
    for i,col in enumerate(('green','yellow','red')):g.cylinder(col,(x+.75,y,2.18+i*.085),(x+.75,y,2.25+i*.085),.07)
    g.text('CNC '+str(n),(x,y-.835,1.95),.13)
    g.solid(f'machine_{n}',(x,y-.1,1.2),(2.3,1.9,2.4))


def tank(g,x,y,n):
    for dx in (-.4,.4):g.box('steel',(x+dx,y,.26),(.14,.65,.52))
    g.cylinder('silver',(x,y,.4),(x,y,2.25),.60,24)
    for z in (.52,2.12):g.cylinder('edge',(x,y,z),(x,y,z+.08),.63,24)
    g.cylinder('teal',(x,y,2.25),(x,y,2.42),.23,16)
    g.cylinder('red',(x,y-.65,1.0),(x,y-.82,1.0),.15,16)
    g.text('T'+str(n),(x,y-.61,1.55),.24,'dark')
    g.solid(f'tank_{n}',(x,y,1.25),(1.3,1.4,2.5))


def design(world,directory):
    """Install the art layer without changing the established race geometry."""
    g=Geometry()
    # Retire the blockout scenery, never the robots, belt or course colliders.
    old=('rack_','stock_','steel_column_','overhead_pipe_','pipe_stanchion_')
    for model in list(world.findall('model')):
        if model.get('name').startswith(old):world.remove(model)
    floor=world.find("model[@name='concrete_floor']")
    for size in floor.findall('.//box/size'):size.text='32 26 .2'
    for color in floor.findall('.//material/ambient')+floor.findall('.//material/diffuse'):color.text='.39 .43 .44 1'
    back=world.find("model[@name='back_wall']")
    back.find('pose').text='10 13 2.6 0 0 0'
    for size in back.findall('.//box/size'):size.text='32 .2 5.2'
    far=world.find("model[@name='side_wall']")
    far.find('pose').text='26 0 2.6 0 0 0'
    for size in far.findall('.//box/size'):size.text='.2 26 5.2'
    scene=world.find('scene');scene.find('ambient').text='.43 .47 .50 1'
    scene.find('background').text='.65 .72 .77 1'
    # Open cutaway roof and tall perimeter steel: keep both chase cameras clear.
    for x in (-4.,2.,8.,14.,20.,25.):
        for y in (-8.,8.):
            g.box('steel',(x,y,2.6),(.16,.38,5.2))
            for dx in (-.13,.13):g.box('edge',(x+dx,y,2.6),(.10,.46,5.2))
            g.box('yellow',(x,y,.40),(.46,.55,.8))
            g.solid(f'column_{x}_{y}',(x,y,2.6),(.46,.55,5.2))
        g.box('steel',(x,0,5.18),(.18,16.4,.22))
        for y in (-6.,6.):
            g.box('white',(x,y,4.9),(.4,2.,.10))
            g.box('light',(x,y,4.84),(.32,1.85,.025))
    for y in (-8.,8.):g.box('steel',(10.5,y,5.2),(30.,.32,.4))
    # Wall panel rhythm, clerestory windows, service conduits.
    for x in range(-4,26,2):
        g.box('edge',(x,8.87,2.6),(.045,.06,5.2))
        g.box('glass',(x,8.84,3.8),(1.65,.07,1.1))
        for z in (3.23,4.37):g.box('silver',(x,8.78,z),(1.75,.06,.06))
    for y in (-7.4,7.4):
        for z,col,r in ((3.5,'teal',.075),(3.8,'silver',.055),(4.1,'orange',.045)):
            g.cylinder(col,(-4,y,z),(24,y,z),r,12)
        for x in (0,6,12,18,24):g.box('steel',(x,y,3.85),(.08,.3,.95))
    # Floor zoning and expansion joints are visual only: zero wheel bumps.
    for x in range(-6,27,2):g.box('paint',(x,0,.0008),(.012,18,.001))
    for y in range(-8,9,2):g.box('paint',(10,y,.0008),(32,.012,.001))
    for y in (-6.6,6.6):
        g.box('floor',(10,y,.002),(29,1.0,.001))
        for edge in (-.53,.53):g.box('yellow',(10,y+edge,.004),(29,.045,.002))
    for x in (0,9,20):
        for i in range(9):g.box('white',(x+i*.15-0.6,-6.6,.006),(.075,.85,.002))
    for x,y in ((-2,7.4),(1.2,7.4),(4.4,7.4),(-2,-7.4)):
        rack(g,x,y)
    for i,x in enumerate((9.,12.3,15.6),1):machine(g,x,6.1,i)
    for i,x in enumerate((9.,11.,13.),1):tank(g,x,-6.0,i)
    g.cylinder('teal',(9,-6,2.4),(13,-6,2.4),.09)
    g.cylinder('teal',(13,-6,2.4),(13,-6,3.5),.09)
    # Raised side maintenance gallery, railings and stairs; no race-lane overlap.
    g.box('steel',(19.2,6.6,2.7),(4.8,2.2,.18))
    g.solid('gallery',(19.2,6.6,2.7),(4.8,2.2,.18))
    for x in (17.,21.4):
        for y in (5.6,7.6):
            g.box('steel',(x,y,1.32),(.15,.15,2.64))
            g.solid(f'gallery_leg_{x}_{y}',(x,y,1.32),(.15,.15,2.64))
    for x in np.linspace(16.9,21.5,9):g.box('yellow',(x,5.55,3.25),(.045,.045,1.0))
    for z in (3.,3.7):g.box('yellow',(19.2,5.55,z),(4.8,.055,.055))
    for i in range(12):
        x=22.+i*.23;z=2.7-i*.225
        g.box('silver',(x,6.4,z),(.27,1.0,.08))
        g.solid(f'stair_{i}',(x,6.4,z),(.27,1.0,.08))
    # Substation and cable reels in the side service bay.
    for i in range(3):
        x=17.+i*.95;y=-6.1
        g.box('white',(x,y,1.05),(.82,.65,2.1))
        g.box('edge',(x,y-.34,1.08),(.72,.04,1.86))
        g.box('dark',(x,y-.375,1.5),(.36,.018,.25))
        g.box('yellow',(x,y-.39,.75),(.2,.014,.2),math.pi/4)
        g.solid(f'cabinet_{i}',(x,y,1.05),(.82,.75,2.1))
    for x in (21.5,23.):
        g.cylinder('dark',(x,-6.0,.65),(x,-5.2,.65),.47,24)
        for y in (-6.05,-5.15):g.cylinder('wood',(x,y-.06,.65),(x,y+.06,.65),.65,24)
        g.solid(f'reel_{x}',(x,-5.6,.65),(1.3,1.05,1.3))
    # Destination loading doors and illuminated dock headers, viewed from -X.
    for n,y in enumerate((-4.8,0.,4.8),1):
        g.box('dark',(25.85,y,1.65),(.12,3.8,3.3))
        g.box('silver',(25.76,y,1.65),(.10,3.3,2.95))
        for z in np.arange(.3,3.1,.23):g.box('edge',(25.70,y,z),(.025,3.3,.018))
        for dy in (-1.8,1.8):g.box('yellow',(25.65,y+dy,.62),(.22,.22,1.24))
        g.text('DOCK 0'+str(n),(25.67,y,3.55),.32,'white','entry')
    g.text('ENRO INDUSTRIAL ROBOTICS',(10,8.72,4.8),.38)
    g.text('WAREHOUSE',(-1.4,7.98,3.6),.30,'yellow')
    g.text('PRODUCTION',(12.3,8.70,2.8),.32,'teal')
    g.text('SERVICE',(18,-6.51,2.55),.27,'white')
    # Move peripheral machinery outwards; stretch only high cross-building beams.
    for triangles in g.triangles.values():
        for tri in triangles:
            tri[:,1]+=np.where(tri[:,1]>4.2,4.,np.where(tri[:,1]<-4.2,-4.,0.))
    for solid in g.solids:
        x,y,z=solid['center']
        solid['center']=(x,y+(4 if y>4.2 else -4 if y<-4.2 else 0),z)
    from course import LANES, OUT_Y, RETURN_Y, SLALOM_GATES
    for lane,col in zip(LANES,('blue','orange')):
        for x,dy,label in ((2.8,OUT_Y,'01 / RAMP'),(9.,OUT_Y,'02-04 / SLALOM'),
                            (21.6,0.,'05 / U TURN'),(13.5,RETURN_Y,'06 / TERRAIN'),
                            (8.2,RETURN_Y,'07 / LOW 1.3M'),(3.,RETURN_Y,'08 / DELIVERY')):
            g.box('dark',(x,lane+dy,2.8),(.08,2.6,.46))
            g.box(col,(x-.047,lane+dy,3.045),(.03,2.6,.05))
            g.text(label,(x-.049,lane+dy,2.8),.16,'white','entry')
            g.text(label,(x+.049,lane+dy,2.8),.16,'white','return')
            # Both faces stay legible on the outbound and returning approach.
            for side in (-1,1):
                g.cylinder('steel',(x,lane+dy+side*1.22,3.03),(x,lane+dy+side*1.22,5.15),.018,8)
        for x,dy in ((2.1,OUT_Y),(8.75,OUT_Y),*SLALOM_GATES,(19.6,OUT_Y)):
            for yy,yaw in ((-.15,-math.pi/4),(.15,math.pi/4)):
                g.box(col,(x,lane+dy+yy,.008),(.36,.065,.003),yaw)
        g.text('LOWER ARM',(9.,lane+RETURN_Y,.010),.20,'yellow','floor')
        g.text('DELIVERY',(3.,lane+RETURN_Y,.010),.23,col,'floor')
        for x in (18.,14.,9.,5.,3.):
            for yy,yaw in ((-.15,math.pi/4),(.15,-math.pi/4)):
                g.box(col,(x,lane+RETURN_Y+yy,.008),(.36,.065,.003),yaw)
    return g.write(world,Path(directory)/'facility_assets')
