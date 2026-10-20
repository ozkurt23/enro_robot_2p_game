"""Isolated, reproducible idle physics/render-load benchmark; never drives robots.

Each trial owns a unique Gazebo partition and its process sessions. RTF is
simulation seconds per wall second, not FPS. RSS includes shared pages in each
process and is therefore an upper bound, not unique physical memory usage.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import uuid
import psutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'v2/scripts'))
from stop_session import stop_session, _signal_session
import signal


def measure(world, seconds, gui, output):
    output.mkdir(parents=True,exist_ok=False)
    env=dict(os.environ,GZ_PARTITION='enro-benchmark-'+uuid.uuid4().hex,
             GZ_GUI_PLUGIN_PATH=str(ROOT/'v2/.runtime/factory-camera-build')+':'+os.environ.get('GZ_GUI_PLUGIN_PATH',''))
    children=[]; streams=[]; samples=[]
    def start(command,name):
        stream=(output/(name+'.log')).open('w'); streams.append(stream)
        child=subprocess.Popen(command,env=env,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        children.append(child)
    try:
        start(['gz','sim','-s','-r','-v','2',str(world)],'server')
        if gui:
            for p in (1,2):
                start(['gz','sim','-g','-v','2','--gui-config',str(world.parent/f'player{p}.config')],f'gui{p}')
        # Keep one subscriber alive. Repeated `gz topic -n 1` invocations hit a
        # transport CLI teardown race (duplicate JSON / occasional SIGSEGV).
        start(['gz','topic','-e','-t','/world/factory_race/stats','--json-output'],'stats')
        began=time.monotonic()
        while time.monotonic()-began<seconds+10:
            if any(p.poll() is not None for p in children):raise RuntimeError('Gazebo component exited')
            records=(output/'stats.log').read_text().splitlines()
            data=None
            for line in reversed(records):
                try:data=json.loads(line);break
                except json.JSONDecodeError:continue
            if data is None:
                if time.monotonic()-began>20:raise RuntimeError('No world statistics received')
                time.sleep(.2);continue
            elapsed=time.monotonic()-began
            processes=[]
            for child in children:
                try:processes.extend([psutil.Process(child.pid),*psutil.Process(child.pid).children(recursive=True)])
                except psutil.NoSuchProcess:pass
            rss=cpu=0
            for process in processes:
                try:
                    rss+=process.memory_info().rss
                    times=process.cpu_times();cpu+=times.user+times.system
                except psutil.NoSuchProcess:pass
            stamp=data.get('simTime',data.get('sim_time',{}))
            samples.append(dict(wall=elapsed,sim=float(stamp.get('sec',0))+float(stamp.get('nsec',0))/1e9,
                                rtf=data.get('realTimeFactor',data.get('real_time_factor',0)),rss_mb=rss/2**20,cpu_seconds=cpu))
            time.sleep(1)
        warm=[s for s in samples if s['wall']>=10]
        rates=[(b['sim']-a['sim'])/(b['wall']-a['wall']) for a,b in zip(warm,warm[1:])]
        if len(rates)<5 or max(rates)<=0:raise RuntimeError('Missing useful physics samples')
        summary=dict(world=str(world),gui=gui,duration=seconds,samples=len(warm),
                     rtf_median=statistics.median(rates),rtf_p10=sorted(rates)[int(len(rates)*.1)],
                     rss_peak_mb=max(s['rss_mb'] for s in warm),
                     rss_growth_mb=warm[-1]['rss_mb']-warm[0]['rss_mb'],
                     rss_late_growth_mb=warm[-1]['rss_mb']-warm[len(warm)//2]['rss_mb'],
                     cpu_cores=(warm[-1]['cpu_seconds']-warm[0]['cpu_seconds'])/(warm[-1]['wall']-warm[0]['wall']))
        (output/'measurements.json').write_text(json.dumps(dict(summary=summary,samples=samples),indent=2))
        print(json.dumps(summary),flush=True)
        return summary
    finally:
        for child in children:_signal_session(child.pid,signal.SIGINT)
        for child in reversed(children):
            stop_session(child.pid);child.wait(timeout=3)
        for stream in streams:stream.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('world',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--seconds',type=float,default=60)
    parser.add_argument('--repeats',type=int,default=2)
    parser.add_argument('--gui',action='store_true')
    args=parser.parse_args()
    for n in range(args.repeats):
        measure(args.world.resolve(),args.seconds,args.gui,args.output.resolve()/f'trial-{n+1}')
