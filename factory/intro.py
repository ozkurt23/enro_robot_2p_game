"""Ten-second, large-print controller briefing before manual driving is enabled."""
import tkinter as tk
import time


class Intro:
    def __init__(self, root, close):
        self.root = root
        self.since = None
        self.done = False
        self.window = tk.Toplevel(root)
        self.window.configure(bg='#101b24')
        self.window.attributes('-fullscreen', True)
        self.window.attributes('-topmost', True)
        self.window.protocol('WM_DELETE_WINDOW', close)
        self.window.bind('<Escape>', lambda _: close())
        scale = max(18, min(38, root.winfo_screenheight()//40))
        def label(text, factor=1, color='#f3f5f6'):
            tk.Label(self.window,text=text,bg='#101b24',fg=color,
                     font=('Sans',int(scale*factor),'bold')).pack(pady=scale//3)
        tk.Frame(self.window,bg='#101b24',height=scale).pack()
        label('KUTUYU İLK BIRAKAN KAZANIR',1.3)
        label('SOL EKRAN: MAVİ       |       SAĞ EKRAN: TURUNCU',.8,'#f0b775')
        label('Sol analog  →  SÜR',1.1)
        label('Sağ analog  →  DÖN  /  YUKARI–AŞAĞI ZOOM',.9)
        label('LB: KALDIR      LT: İNDİR')
        label('RB: TUT           RT: BIRAK')
        label('Omuz tuşlarını basılı tut. Bırakınca konum korunur.',.65)
        label('Yokuş → 3 zikzak → U dönüşü → engebe → alçak geçit → teslimat',.7)
        label('Dönüşte kolu alçalt, yavaş dön. Alçak geçitte LT ile indir.',.65)
        label('Menü: duraklat / devam',.65)
        self.counter=tk.Label(self.window,bg='#101b24',fg='#7be3b0',font=('Sans',int(scale*1.3),'bold'))
        self.counter.pack(pady=scale//2)
        self.counter['text']='Gazebo ve oyun kolları hazırlanıyor…'
        root.withdraw()

    def tick(self, ready, now=None):
        if self.done: return True
        now=time.monotonic() if now is None else now
        if not ready:
            self.since=None
            self.counter['text']='İki gamepad ve iki görüntü bekleniyor…'
        else:
            if self.since is None: self.since=now
            remaining=max(0,10-int(now-self.since))
            self.counter['text']=f'{remaining} saniye sonra başlıyoruz — analogları bırak'
            if remaining == 0:
                self.done=True
                self.window.destroy()
                self.root.deiconify()
                self.root.lift()
        return self.done
