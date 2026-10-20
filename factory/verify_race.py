"""Acceptance evidence from real physics telemetry, never a mocked world."""
import argparse
import json
import math
import xml.etree.ElementTree as E
from pathlib import Path
from course import TARGET_X, TARGET_DY, LANES, OUT_Y, RETURN_Y, DECK_HEIGHT, STAGE_NAMES, SLALOM_GATES


def verify(directory):
    directory=Path(directory)
    race=json.loads((directory/'race.json').read_text())
    assert race['phase']=='finished' and race['winner'] in (0,1,2), race
    assert race['checkpoint']==[True,True],race
    assert race['stages']==[len(STAGE_NAMES)]*2,race
    for player in (1,2):
        rows=[json.loads(line) for line in (directory/f'p{player}-status.jsonl').read_text().splitlines()]
        held=[r for r in rows if r['cargo'] and r['lift']>.69 and r['gap']<0]
        assert max(r['cargo'][2] for r in held)>1.30, 'Raised transport pose not reached'
        assert any(r['base'][2]>DECK_HEIGHT-.07 and 4.85<r['base'][0]<5.95 for r in held), 'Ramp crossing failed'
        assert any(r['base'][0]>2.5 and r['cargo'][2]>1.02 for r in held), 'Physical carry failed'
        assert max(r.get('base_speed',0) for r in rows)>.8,'Faster driving not observed'
        assert any(6.7<r['base'][0]<7.35 and abs(r['base'][1]-RETURN_Y)<.4 and r['cargo'][2]<1.27 and r['gap']<0 for r in rows if r['base'] and r['cargo']), 'Low underpass carry missing'
        assert any(r['base'][0]>20.5 and abs(r['base'][1]-RETURN_Y)<.4 and abs(abs(r['base'][3])-math.pi)<.25 for r in rows if r['base']), 'Real U turn missing'
        for x,dy in SLALOM_GATES:
            assert any(abs(r['base'][0]-x)<.3 and abs(r['base'][1]-dy)<.4 for r in rows if r['base']), 'Slalom passage missing'
        print(f'P{player}: physically lifted to {max(r["cargo"][2] for r in held):.3f} m; carried beyond x=2.5 m')
        if race['winner'] in (0,player):
            delivered=rows[-1]
            assert math.dist(delivered['cargo'],[TARGET_X,LANES[player-1]+TARGET_DY,.8995])<.075, delivered['cargo']
            assert delivered['gap']>.03 and not delivered['armed'], 'Finish must release and lock control'
        stopped=[r for r in rows[-15:] if not r['armed']]
        assert len(stopped)>=5, 'Need post-finish observations'
        assert math.dist(stopped[0]['base'][:3],stopped[-1]['base'][:3])<.025, 'Base still moving after finish'
    print(f'PASS: winner={race["winner"]} after physical release; both controls stop.')


def box_overlap(center,rotation,half,other_center,other_half):
    """Signed 3-D OBB/AABB overlap, including roll/pitch and local box offset."""
    import numpy as np
    axes=[*np.eye(3),*rotation.T]
    axes += [np.cross(a,b) for a in np.eye(3) for b in rotation.T]
    delta=np.asarray(other_center)-center
    overlaps=[]
    for axis in axes:
        norm=np.linalg.norm(axis)
        if norm<1e-8:continue
        axis=axis/norm
        overlaps.append(sum(half*abs(rotation.T@axis))+sum(other_half*abs(axis))-abs(delta@axis))
    return min(overlaps)


def verify_collision(directory):
    import numpy as np
    from scipy.spatial.transform import Rotation
    world=E.parse(Path(directory)/'factory_race.sdf').find('world')
    for player in (1,2):
        cabinet=world.find(f"model[@name='p{player}_pickup_bench_cabinet']")
        cabinet_center=np.array(list(map(float,cabinet.findtext('pose').split()[:3])))
        cabinet_half=np.array(list(map(float,cabinet.findtext('.//box/size').split())))/2
        chassis=world.find(f"model[@name='robot_p{player}']/link[@name='base_footprint']/collision[@name='base_footprint_fixed_joint_lump__base_link_collision']")
        local=np.array(list(map(float,chassis.findtext('pose').split())))
        half=np.array(list(map(float,chassis.findtext('geometry/box/size').split())))/2
        path=Path(directory)/f'p{player}-status.jsonl'
        rows=[json.loads(line) for line in path.read_text().splitlines()]
        overlaps=[]
        for row in rows:
            if not row['base']: continue
            assert row.get('base_quaternion'), 'Full orientation needed; rerun this collision trial'
            rotation=Rotation.from_quat(row['base_quaternion']).as_matrix()
            base=np.array(row['base'][:3]);base[1]+=LANES[player-1]
            center=base+rotation@local[:3]
            overlap=box_overlap(center,rotation@Rotation.from_euler('xyz',local[3:]).as_matrix(),half,cabinet_center,cabinet_half)
            overlaps.append(overlap)
        assert rows[-1]['age']>23 and max(r['base'][0] for r in rows if r['base'])>.2
        assert max(overlaps)<.02, 'Chassis penetrated cabinet'
        assert abs(rows[-1]['cargo'][2]-.8975)<.002, 'Cargo disturbed without grasp'
        print(f'P{player}: full-forward collision test passed; maximum 3-D contact overlap {max(overlaps)*1000:.1f} mm')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('directory')
    parser.add_argument('--collision',action='store_true')
    args=parser.parse_args()
    (verify_collision if args.collision else verify)(args.directory)
