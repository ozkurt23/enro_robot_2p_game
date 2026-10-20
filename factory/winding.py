"""Physical U-shaped race circuit: outbound slalom, hairpin, return obstacles."""
from world import fixed,el
from course import (OUT_Y, RETURN_Y, RAMP_START, RAMP_END, DECK_START,
                    DECK_END, DECK_HEIGHT, COURSE_WIDTH, CORRIDOR_WIDTH, SLALOM_GATES,
                    ROUGH_START, TUNNEL_START, TUNNEL_END, TUNNEL_CLEARANCE)


def build_course(world,player,lane,tint,beam):
    prefix=f'p{player}_course'
    out=lane+OUT_Y;back=lane+RETURN_Y
    # Closed perimeter and divider mean no straight line connects both stations.
    # Low walls preserve sight of the opponent, but block wheels/chassis.
    for name,x,y,sx,sy in (
        ('outer_south',10.8,lane-3.3,24.6,.18),
        ('outer_north',10.8,lane+3.3,24.6,.18),
        ('start_back',-1.5,lane,.18,6.6),
        ('turn_back',23.1,lane,.18,6.6),
        ('divider',9.4,lane,21.8,.18)):
        fixed(world,prefix+'_'+name,f'{x} {y} .45',f'{sx} {sy} .9','.30 .35 .38 1')
        fixed(world,prefix+'_'+name+'_cap',f'{x} {y} .91',f'{sx} {sy} .04',tint)
    beam(world,prefix+'_up',RAMP_START,DECK_START,out,.005,DECK_HEIGHT,COURSE_WIDTH,.08,'.34 .39 .42 1')
    beam(world,prefix+'_deck',DECK_START,DECK_END,out,DECK_HEIGHT,DECK_HEIGHT,COURSE_WIDTH,.16,'.24 .30 .33 1')
    beam(world,prefix+'_down',DECK_END,RAMP_END,out,DECK_HEIGHT,.005,COURSE_WIDTH,.08,'.34 .39 .42 1')
    for side in (-1,1):
        y=out+side*(COURSE_WIDTH/2+.015)
        for label,a,b,z0,z1 in (('up',RAMP_START,DECK_START,.005,DECK_HEIGHT),('deck',DECK_START,DECK_END,DECK_HEIGHT,DECK_HEIGHT),('down',DECK_END,RAMP_END,DECK_HEIGHT,.005)):
            beam(world,f'{prefix}_{label}_edge_{side}',a,b,y,z0+.09,z1+.09,.055,.09,tint)
    for n in range(9):
        paint=fixed(world,f'{prefix}_deck_stripe_{n}',f'{DECK_START+.07+n*.15} {out} {DECK_HEIGHT+.001}', '.07 1.85 .002',tint if n%2==0 else '.14 .16 .17 1')
        # Painted stripes must not introduce 2 mm collision edges into wheel contacts.
        link=paint.find('link');link.remove(link.find('collision'))
    # Alternate solid gate blocks leave 1.85 m clearance on opposite sides.
    for n,(x,dy) in enumerate(SLALOM_GATES):
        half_gap=CORRIDOR_WIDTH/2
        low,high=(-3.21,dy-half_gap) if n!=1 else (dy+half_gap,-.09)
        fixed(world,f'{prefix}_slalom_block_{n}',f'{x} {lane+(low+high)/2} .48',f'.24 {high-low} .96','.83 .59 .10 1')
        for z in (.23,.49,.75):
            fixed(world,f'{prefix}_slalom_stripe_{n}_{z}',f'{x-.126} {lane+(low+high)/2} {z}',f'.008 {high-low} .065','.10 .13 .15 1')
    # Return route has the tested full-width rough wave faces.
    for n,height in enumerate((.025,.04,.03)):
        x=ROUGH_START+n*1.05
        beam(world,f'{prefix}_rough_{n}_up',x,x+.5,back,.003,height,2.05,.07,'.38 .37 .34 1')
        beam(world,f'{prefix}_rough_{n}_down',x+.5,x+1.,back,height,.003,2.05,.07,'.38 .37 .34 1')
    for side in (-1,1):
        fixed(world,f'{prefix}_tunnel_wall_{side}',f'{(TUNNEL_START+TUNNEL_END)/2} {back+side*1.16} {TUNNEL_CLEARANCE/2}',
              f'{TUNNEL_END-TUNNEL_START} .12 {TUNNEL_CLEARANCE}','.25 .30 .33 1')
    roof=fixed(world,f'{prefix}_tunnel_roof',f'{(TUNNEL_START+TUNNEL_END)/2} {back} {TUNNEL_CLEARANCE+.6}',
               f'{TUNNEL_END-TUNNEL_START} 2.44 1.2','.75 .53 .12 1')
    el(roof.find('link/visual'),'transparency',.55)
