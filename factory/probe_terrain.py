"""Isolated wheel/terrain smoke test. No ROS, pads, cargo attachment or live-game commands."""
import json
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as E
from race_world import build_race
from world import ROOT
from control import JOINTS,HIGH,Targets
from course import LANES, OUT_Y, RETURN_Y, ROUGH_START, ROUGH_END, TUNNEL_START, TUNNEL_END

sys.path.insert(0,str(ROOT/'v2/scripts'))
from stop_session import stop_session


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--section',choices=('rough','tunnel-low','tunnel-high','straight'),default='rough')
    args=parser.parse_args()
    run=ROOT/'v2/.runtime/factory'/('terrain-'+uuid.uuid4().hex[:8])
    path,_=build_race(run)
    tree=E.parse(path);world=tree.find('world');world.set('name','terrain_probe')
    for model in list(world.findall('model')):
        name=model.get('name')
        prefix='p1_course_' if args.section=='straight' else 'p1_course_rough_' if args.section=='rough' else 'p1_course_tunnel_'
        if name not in ('robot_p1','concrete_floor') and not name.startswith(prefix):
            world.remove(model)
    start=8.9 if args.section=='straight' else ROUGH_START-1. if args.section=='rough' else TUNNEL_START-1.2
    lane=LANES[0]+(OUT_Y if args.section=='straight' else RETURN_Y)
    world.find("model[@name='robot_p1']/pose").text=f'{start} {lane} .002 0 0 0'
    tree.write(path,encoding='unicode')
    env=dict(os.environ,GZ_PARTITION='enro-'+run.name)
    with (run/'server.log').open('w') as log:
        server=subprocess.Popen(['gz','sim','-s','-r',str(path)],env=env,stdout=log,stderr=log,start_new_session=True)
        try:
            time.sleep(3)
            if args.section=='tunnel-high':
                for j,value,initial in zip(JOINTS,HIGH,Targets().joints()):
                    subprocess.run(['gz','topic','-t',f'/p1/manual/{j}','-m','gz.msgs.Double','-p',f'data: {value-initial}'],
                                   env=env,check=True,capture_output=True,timeout=5)
                time.sleep(7)
            began=time.monotonic(); last=None; samples=[]
            while time.monotonic()-began<55:
                speed=.20 if args.section=='tunnel-high' else .55
                subprocess.run(['gz','topic','-t','/p1/cmd_vel','-m','gz.msgs.Twist','-p',f'linear {{ x: {speed} }}'],
                               env=env,check=True,capture_output=True,timeout=5)
                result=subprocess.run(['gz','topic','-e','-t','/p1/physical_odom','--json-output','-n','1'],
                                      env=env,capture_output=True,text=True,timeout=5,check=True)
                # Some gz CLI builds append a duplicate sample during teardown.
                last=json.JSONDecoder().raw_decode(result.stdout.strip())[0]['pose']['position']
                samples.append(last)
                print(last,flush=True)
                if args.section=='tunnel-high' and time.monotonic()-began>18:
                    # Native velocity servos can push and deflect an unloaded
                    # arm through sustained contact: this is not a rigid lock.
                    # Verify the collision response, not permanent immobilization.
                    contact=[p for p in samples if TUNNEL_START-1.<p.get('x',0)<TUNNEL_END+.3]
                    assert any(p.get('z',0)>.02 and abs(p.get('y',lane)-lane)>.05 for p in contact), 'No raised-arm ceiling contact response'
                    print('PASS: raised arm causes physical chassis lift/deflection; not a hard stop. '+str(run),flush=True)
                    return
                if args.section=='straight' and time.monotonic()-began>35:
                    assert max(p.get('x',0) for p in samples)<23.1, 'Straight input bypassed the perimeter'
                    assert max(p.get('x',0) for p in samples)>start+.2, 'Robot never drove'
                    assert all(p.get('y',0)<LANES[0] for p in samples), 'Straight input reached the return lane'
                    (run/'evidence.json').write_text(json.dumps(dict(section=args.section,passed=True,samples=samples)))
                    print('PASS: constant forward cannot reach the separated return/delivery lane. '+str(run),flush=True)
                    return
                if args.section in ('rough','tunnel-low') and last.get('x',0)>(ROUGH_END+.5 if args.section=='rough' else TUNNEL_END+.8):
                    print('PASS: '+args.section+' collision traversal. '+str(run),flush=True)
                    return
                time.sleep(2)
            raise RuntimeError('Terrain blocked the chassis: '+str(last)+'; '+str(run))
        finally:
            stop_session(server.pid)
            server.wait(timeout=3)


if __name__=='__main__':main()
