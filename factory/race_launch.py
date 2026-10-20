"""One physics server, two independent native Gazebo views and one referee."""
import argparse
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from control import JOINTS
from world import ROOT
from race_world import build_race, LANES
from course import STAGE_NAMES

sys.path.insert(0, str(ROOT/'v2/scripts'))
from stop_session import stop_session, _signal_session


def main():
    parser = argparse.ArgumentParser(description='Ortak Gazebo fabrikasında iki kişilik kargo yarışı')
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--no-panel', action='store_true')
    parser.add_argument('--pad1', default='/dev/input/js0')
    parser.add_argument('--pad2', default='/dev/input/js1')
    parser.add_argument('--seconds', type=float, default=0)
    parser.add_argument('--probe', nargs='?', const='delivery', choices=('delivery','collision'), help='Açıkça otomatik fizik kabul testi')
    args = parser.parse_args()
    if os.path.realpath(args.pad1) == os.path.realpath(args.pad2):
        parser.error('İki oyuncu aynı gamepad olamaz')
    runtime = ROOT/'v2/.runtime/factory'
    runtime.mkdir(parents=True, exist_ok=True)
    lock = (runtime/'game.lock').open('w')
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: parser.error('Fabrika oyunu zaten açık')
    run = runtime/(time.strftime('%Y%m%d-%H%M%S')+'-race-'+uuid.uuid4().hex[:6])
    run.mkdir()
    world, configs = build_race(run)
    build_dir = ROOT/'v2/.runtime/factory-camera-build'
    if not args.headless:
        subprocess.run(['cmake','-S',str(ROOT/'factory'),'-B',str(build_dir)], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['cmake','--build',str(build_dir),'-j','2'], check=True, stdout=subprocess.DEVNULL)
    env = dict(os.environ, GZ_PARTITION='enro-'+run.name, ROS_DOMAIN_ID='83',
               ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST',
               GZ_GUI_PLUGIN_PATH=str(build_dir)+':'+os.environ.get('GZ_GUI_PLUGIN_PATH',''))
    (run/'session.json').write_text(json.dumps({'partition':env['GZ_PARTITION'],'domain':83}))
    print('Ortak fabrika oturumu: '+str(run), flush=True)
    children, streams = [], []
    stop = restart = False
    panel = None
    intro = None
    intro_file = run/'intro.done'
    def request_stop(*_):
        nonlocal stop
        stop = True
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP): signal.signal(sig,request_stop)
    def start(command, name):
        stream = (run/(name+'.log')).open('w')
        streams.append(stream)
        children.append(subprocess.Popen(command, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True))
    statuses = [run/f'p{p}-status.json' for p in (1,2)]
    gate = run/'race.json'
    if not args.headless and not args.no_panel:
        import tkinter as tk
        panel=tk.Tk()
        panel.title('ENRO — Ortak fabrika: MAVİ vs TURUNCU')
        panel.geometry(f'1050x145+{max(0,(panel.winfo_screenwidth()-1050)//2)}+32')
        panel.attributes('-topmost',True)
        banner=tk.Label(panel,text='Ortak fabrika açılıyor…',font=('Sans',15,'bold'))
        banner.pack(pady=4)
        tk.Label(panel,text='Sol: sürüş | Sağ ↔ dönüş / ↕ zoom | LB/LT: kol ↑/↓ | RB/RT: kapat/aç | Menü: duraklama').pack()
        labels=[tk.Label(panel,font=('Sans',11)) for _ in (1,2)]
        for label in labels: label.pack()
        def new_round():
            nonlocal stop,restart
            stop=restart=True
        buttons=tk.Frame(panel)
        buttons.pack(pady=8)
        tk.Button(buttons,text='Yeni yarış',command=new_round).pack(side='left',padx=10)
        tk.Button(buttons,text='Kapat',command=request_stop).pack(side='left',padx=10)
        panel.protocol('WM_DELETE_WINDOW',request_stop)
        if not args.probe:
            from intro import Intro
            intro=Intro(panel,request_stop)
    try:
        start(['gz','sim','-s','-r','-v','2',str(world)],'server')
        topics=['/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock',
                '/belt/speed@std_msgs/msg/Float64]gz.msgs.Double',
                '/belt_carton/odom@nav_msgs/msg/Odometry[gz.msgs.Odometry']
        for p in (1,2):
            prefix=f'/p{p}'
            topics += [prefix+'/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist',
                       prefix+'/physical_odom@nav_msgs/msg/Odometry[gz.msgs.Odometry',
                       prefix+'/cargo/odom@nav_msgs/msg/Odometry[gz.msgs.Odometry',
                       prefix+'/manual/joint_states@sensor_msgs/msg/JointState[gz.msgs.Model',
                       prefix+'/manual/camera_distance@std_msgs/msg/Float64]gz.msgs.Double']
            topics += [prefix+f'/manual/{j}@std_msgs/msg/Float64]gz.msgs.Double' for j in JOINTS]
        start(['ros2','run','ros_gz_bridge','parameter_bridge',*topics],'bridge')
        for p in (1,2):
            cmd=['/usr/bin/python3',str(ROOT/'factory/driver.py'),'--pad',getattr(args,f'pad{p}'),
                 '--status',str(statuses[p-1]),'--namespace',f'/p{p}',
                 '--spawn-y',str(LANES[p-1]),'--race-gate',str(gate)]
            if args.probe: cmd += ['--race-probe',args.probe,'--probe-delay',str((p-1)*5)]
            start(cmd,f'p{p}-driver')
            if not args.headless:
                start(['gz','sim','-g','-v','2','--gui-config',str(configs[p-1])],f'p{p}-gui')
        referee=['/usr/bin/python3',str(ROOT/'factory/referee.py'),str(run)]
        if args.probe: referee += ['--probe']
        if intro: referee += ['--intro-file',str(intro_file)]
        start(referee,'referee')
        began=time.monotonic()
        while not stop:
            if args.seconds and time.monotonic()-began > args.seconds: break
            if any(p.poll() is not None for p in children):
                raise RuntimeError('Bir bileşen kapandı. Oturum güvenle kapatılıyor. Log: '+str(run))
            for path in [*statuses,gate]:
                if (not path.exists() and time.monotonic()-began > 30) or (path.exists() and time.time()-path.stat().st_mtime > 2):
                    raise RuntimeError('Kontrol/hakem heartbeat kesildi; oturum kapatılıyor.')
            if panel:
                if intro and not intro.done:
                    ready=all((run/f'p{p}-camera.ready').exists() for p in (1,2))
                    for path in statuses:
                        if not path.exists(): ready=False
                        else:
                            d=json.loads(path.read_text())
                            ready &= d['connected'] and d['base'] is not None and not d['paused']
                    if intro.tick(ready): intro_file.touch()
                race_status=json.loads(gate.read_text()) if gate.exists() else {}
                if race_status: banner['text']=race_status['message']
                for p,path in enumerate(statuses):
                    if path.exists():
                        d=json.loads(path.read_text())
                        state='Bağlı değil' if not d['connected'] else 'DURAKLATILDI' if d['paused'] else 'Hazır' if d['armed'] else 'Analogları ve omuz tuşlarını bırak'
                        stage=race_status.get('stages',[0,0])[p]
                        checkpoint=f'{stage}/{len(STAGE_NAMES)} — '+(STAGE_NAMES[stage] if stage<len(STAGE_NAMES) else 'Teslimat')
                        labels[p]['text']=f'Oyuncu {p+1} — {state} | {checkpoint} | Kol %{d["lift"]*100:.0f} | Açıklık {(2*d["gap"]+.048)*1000:.0f} mm'
                panel.update()
            time.sleep(.1)
    finally:
        for child in children: _signal_session(child.pid,signal.SIGINT)
        for child in reversed(children):
            stop_session(child.pid)
            child.wait(timeout=3)
        for stream in streams: stream.close()
        if panel: panel.destroy()
    if restart: os.execv(sys.executable,[sys.executable,__file__,*sys.argv[1:]])
    return 0


if __name__=='__main__': raise SystemExit(main())
