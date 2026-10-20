"""Repeated real-world delivery trials, isolated from physical gamepads.

The normal launcher owns child cleanup. A probe only supplies manual robot
commands; this suite never sets entity poses or attaches cargo to a gripper.
"""
import argparse
import json
from pathlib import Path
import re
import signal
import statistics
import subprocess
import time
from verify_race import verify,verify_collision

ROOT=Path(__file__).resolve().parents[1]


def capture_player(run,name):
    """Capture only the test's Gazebo view, never the desktop or unrelated apps."""
    import gi
    gi.require_version('Gdk','3.0');gi.require_version('GdkX11','3.0')
    from gi.repository import Gdk,GdkX11
    inventory=subprocess.run(['xwininfo','-root','-tree'],text=True,capture_output=True,check=True).stdout
    matches=re.findall(r'(0x[0-9a-f]+) "ENRO — Oyuncu 1 / MAVİ"',inventory)
    if len(matches)!=1:return
    window=GdkX11.X11Window.foreign_new_for_display(Gdk.Display.get_default(),int(matches[0],16))
    if window:
        pixels=Gdk.pixbuf_get_from_window(window,0,0,window.get_width(),window.get_height())
        if pixels:
            pixels.savev(str(run/(name+'.png')),'png',[],[])
            return True
    return False


def trial(gui=False,mode='delivery',seconds=600):
    command=[str(ROOT/'start_factory_game.sh'),'--probe',mode,'--no-panel',
             '--pad1','/dev/input/enro-test-p1','--pad2','/dev/input/enro-test-p2','--seconds',str(seconds)]
    if not gui:command.append('--headless')
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    run=None;samples=[];finished=None;captured=set()
    try:
        # Launcher emits this after world generation, before starting components.
        for line in process.stdout:
            print(line.rstrip(),flush=True)
            if line.startswith('Ortak fabrika oturumu: '):
                run=Path(line.split(': ',1)[1].strip());break
        if run is None:raise RuntimeError('Launcher did not create a session')
        start=time.monotonic()
        while time.monotonic()-start<seconds-1:
            if process.poll() is not None:raise RuntimeError('Simulation ended early')
            path=run/'race.json'
            if path.exists():
                try:data=json.loads(path.read_text())
                except json.JSONDecodeError:continue
                samples.append(data)
                if mode=='delivery' and data['phase']=='running':
                    for player in (1,2):
                        try:state=json.loads((run/f'p{player}-status.json').read_text())
                        except (OSError,ValueError):continue
                        if state.get('probe_phase')==4 and state.get('cargo') and state['cargo'][2]<.5:
                            raise AssertionError(f'P{player} dropped its physical cargo; stage={data["stages"][player-1]}; run={run}')
                if gui:
                    try:
                        status=json.loads((run/'p1-status.json').read_text())
                        for stage,name in ((0,'loading'),(1,'slalom'),(4,'hairpin'),(5,'return'),(6,'underpass'),(8,'delivery')):
                            if status['base'] and data['stages'][0]==stage and name not in captured:
                                if capture_player(run,name):captured.add(name)
                    except (OSError,ValueError,TypeError):pass
                if data['phase']=='finished':
                    finished=finished or time.monotonic()
                    if time.monotonic()-finished>4:break
            if mode=='collision' and time.monotonic()-start>27:break
            time.sleep(1)
        if mode=='delivery':verify(run)
        else:verify_collision(run)
        rates=[(b['simtime']-a['simtime'])/(b['time']-a['time']) for a,b in zip(samples,samples[1:])
               if a['phase']=='running' and b['time']-a['time']>.1]
        return dict(run=str(run),gui=gui,mode=mode,passed=True,wall_seconds=time.monotonic()-start,
                    rtf_median=statistics.median(rates) if rates else None)
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            process.wait(timeout=25)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    parser.add_argument('--runs',type=int,default=3)
    parser.add_argument('--gui-last',action='store_true')
    parser.add_argument('--collision',action='store_true')
    args=parser.parse_args()
    results=[]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.output.exists():parser.error('Choose a new output path; existing evidence is preserved')
    try:
        for n in range(args.runs):
            result=trial(gui=args.gui_last and n==args.runs-1)
            results.append(result);print(json.dumps(result),flush=True)
            args.output.write_text(json.dumps(results,indent=2))
        if args.collision:
            results.append(trial(mode='collision',seconds=35))
            args.output.write_text(json.dumps(results,indent=2))
    except Exception as error:
        results.append(dict(passed=False,error=str(error)))
        args.output.write_text(json.dumps(results,indent=2))
        raise
