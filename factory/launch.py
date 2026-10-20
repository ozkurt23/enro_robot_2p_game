"""Own and clean two isolated Gazebo process sessions, never the user's old game."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from control import JOINTS
from world import ROOT, build

sys.path.insert(0, str(ROOT / 'v2/scripts'))
from stop_session import stop_session, _signal_session


def main():
    parser = argparse.ArgumentParser(description='İki bağımsız gerçek Gazebo: manuel fabrika kargo modu')
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--players', type=int, choices=(1, 2), default=2)
    parser.add_argument('--pad1', default='/dev/input/js0')
    parser.add_argument('--pad2', default='/dev/input/js1')
    parser.add_argument('--probe', nargs='?', const='drop', choices=('drop', 'delivery'), help='Açıkça otomatik fizik testi; insan oyunu değil')
    parser.add_argument('--probe-player', type=int, choices=(1, 2), help='Yalnız seçilen sahaya test girdisi gönder')
    parser.add_argument('--seconds', type=float, default=0, help='Test için süre sınırı')
    parser.add_argument('--no-panel', action='store_true')
    args = parser.parse_args()
    if args.players == 2 and os.path.realpath(args.pad1) == os.path.realpath(args.pad2):
        parser.error('İki oyuncu aynı cihazı kullanamaz')
    runtime = ROOT / 'v2/.runtime/factory'
    runtime.mkdir(parents=True, exist_ok=True)
    lock = (runtime / 'game.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error('Fabrika modu zaten açık')
    run = runtime / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6])
    run.mkdir()
    camera_binary = ROOT / 'v2/.runtime/factory-camera-build/factory_camera'
    if not args.headless:
        subprocess.run(['cmake', '-S', str(ROOT/'factory'), '-B', str(camera_binary.parent)], check=True,
                       stdout=subprocess.DEVNULL)
        subprocess.run(['cmake', '--build', str(camera_binary.parent), '-j', '2'], check=True,
                       stdout=subprocess.DEVNULL)
    print(f'Fabrika oturumu: {run}', flush=True)
    children, streams, statuses, environments = [], [], [], []
    stop = False
    restart = False
    panel = None
    labels = []
    def request_stop(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGHUP, request_stop)
    if not args.headless and not args.no_panel:
        import tkinter as tk
        panel = tk.Tk()
        panel.title('ENRO — Fabrika kargo / manuel kontrol')
        panel.geometry('1050x240+30+30')
        tk.Label(panel, text='Sol: sürüş | Sağ ↔: dönüş / ↕: zoom | LB/LT: kol ↑/↓ | RB/RT: gripper kapat/aç',
                 font=('Sans', 12)).pack(pady=10)
        tk.Label(panel, text='Kutuyu başlangıç masasından YEŞİL işaretli masaya götür ve bırak. Menü: duraklat / devam.',
                 font=('Sans', 11)).pack()
        for p in range(args.players):
            label = tk.Label(panel, text=f'Oyuncu {p+1}: Gazebo açılıyor…', font=('Sans', 12))
            label.pack(pady=8)
            labels.append(label)
        def new_round():
            nonlocal stop, restart
            restart = stop = True
        buttons = tk.Frame(panel)
        buttons.pack()
        tk.Button(buttons, text='Yeni tur — iki dünyayı sıfırla', command=new_round).pack(side='left', padx=15)
        tk.Button(buttons, text='İki sahayı kapat', command=request_stop).pack(side='left', padx=15)
        panel.protocol('WM_DELETE_WINDOW', request_stop)
    def start(cmd, env, name):
        stream = (run / (name+'.log')).open('w')
        streams.append(stream)
        process = subprocess.Popen(cmd, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        children.append(process)
        return process
    try:
        for p in range(1, args.players+1):
            world = build(run / f'p{p}', p)
            env = dict(os.environ, GZ_PARTITION=f'enro-factory-{run.name}-p{p}',
                       ROS_DOMAIN_ID=str(80+p), ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST')
            environments.append(env)
            cmd = ['gz', 'sim', '-r', '-v', '2']
            if args.headless:
                cmd += ['-s']
            start(cmd+[str(world)], env, f'p{p}-gazebo')
            topics = ['/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist',
                      '/odom@nav_msgs/msg/Odometry[gz.msgs.Odometry',
                      '/cargo/odom@nav_msgs/msg/Odometry[gz.msgs.Odometry',
                      '/belt_carton/odom@nav_msgs/msg/Odometry[gz.msgs.Odometry',
                      '/manual/joint_states@sensor_msgs/msg/JointState[gz.msgs.Model',
                      '/belt/speed@std_msgs/msg/Float64]gz.msgs.Double']
            topics += ['/manual/camera_distance@std_msgs/msg/Float64]gz.msgs.Double']
            topics += [f'/manual/{j}@std_msgs/msg/Float64]gz.msgs.Double' for j in JOINTS]
            start(['ros2', 'run', 'ros_gz_bridge', 'parameter_bridge', *topics], env, f'p{p}-bridge')
            status = run / f'p{p}-status.json'
            cmd = ['/usr/bin/python3', str(ROOT/'factory/driver.py'), '--pad', args.pad1 if p == 1 else args.pad2,
                   '--status', str(status)]
            if args.probe and args.probe_player in (None, p):
                cmd += ['--probe', args.probe]
            start(cmd, env, f'p{p}-driver')
            if not args.headless:
                start([str(camera_binary)], env, f'p{p}-camera')
            statuses.append(status)
        print('Sol: sürüş | Sağ ↔: dönüş / ↕: zoom | LB/LT: kol ↑/↓ | RB/RT: kapat/aç', flush=True)
        print('Bırakınca kol/gripper hedefi korunur. Menü: duraklat. Çıkış: Ctrl+C.', flush=True)
        began = time.monotonic()
        while not stop:
            if args.seconds and time.monotonic()-began > args.seconds:
                break
            if any(child.poll() is not None for child in children):
                raise RuntimeError('Bir simülasyon bileşeni kapandı; iki saha güvenle kapatılıyor. Log: '+str(run))
            for status in statuses:
                missing = not status.exists()
                if (missing and time.monotonic()-began > 25) or (not missing and time.time()-status.stat().st_mtime > 2):
                    raise RuntimeError('Kontrol heartbeat kesildi; simülasyonlar kapatılıyor.')
            if panel:
                for p, status in enumerate(statuses):
                    if status.exists():
                        data = json.loads(status.read_text())
                        state = ('TESLİMAT TAMAM' if data['delivered'] else 'DURAKLATILDI' if data['paused']
                                 else 'Kol bağlı değil' if not data['connected'] else 'Hazır' if data['armed']
                                 else 'Analogları ve omuz tuşlarını bırak')
                        labels[p]['text'] = (f'Oyuncu {p+1} / factory_p{p+1}: {state}   |   '
                                             f'Kol %{data["lift"]*100:.0f}   |   Açıklık hedefi {(2*data["gap"]+.048)*1000:.0f} mm')
                panel.update()
            time.sleep(.1)
    finally:
        # Signal every owned session immediately; do not leave player 1 moving
        # while waiting for player 2's renderer to finish shutdown.
        for child in children:
            _signal_session(child.pid, signal.SIGINT)
        for child in reversed(children):
            stop_session(child.pid)
            child.wait(timeout=3)
        for stream in streams:
            stream.close()
        if panel:
            panel.destroy()
    if restart:
        os.execv(sys.executable, [sys.executable, __file__, *sys.argv[1:]])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
