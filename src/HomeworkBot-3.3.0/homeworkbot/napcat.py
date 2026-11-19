"""NapCat 进程管理: 配置目录 → 自动启动 → 看门狗重启 → 日志尾部 → WebUI."""
import collections, glob, os, subprocess, sys, threading, time

LAUNCHER_NAMES = ("napcat.bat", "launcher.bat", "launcher-user.bat", "NapCatWinBootMain.exe", "napcat.exe")

def find_launcher(folder):
    """在 NapCat 目录(含一层子目录 NapCat.*.Shell)里找启动脚本."""
    if not folder or not os.path.isdir(folder):
        return None
    cands = [folder] + sorted(glob.glob(os.path.join(folder, "NapCat*"))) + sorted(glob.glob(os.path.join(folder, "*")))
    for d in cands:
        if not os.path.isdir(d):
            continue
        for n in LAUNCHER_NAMES:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
    return None

class NapCatManager:
    def __init__(self, folder="", args="", log=print, popen=subprocess.Popen, sleep=time.sleep,
                 max_restarts=5, restart_window=600):
        self.folder, self.args, self.log = folder, args, log
        self.popen, self.sleep = popen, sleep
        self.proc, self.state, self.restarts = None, "stopped", 0
        self.tail = collections.deque(maxlen=200)
        self.max_restarts, self.restart_window = max_restarts, restart_window
        self._restart_times = collections.deque()
        self._stop = threading.Event()
        self._watch = None
        self.started_at = None

    @property
    def launcher(self):
        return find_launcher(self.folder)

    @property
    def running(self):
        return bool(self.proc and self.proc.poll() is None)

    def _spawn(self):
        exe = self.launcher
        if not exe:
            self.state = "missing"
            self.log(f"未找到 NapCat 启动脚本: {self.folder or '(未设置目录)'}")
            return False
        cmd = ["cmd", "/c", exe] if exe.lower().endswith(".bat") else [exe]
        if self.args:
            cmd += self.args.split()
        kw = dict(cwd=os.path.dirname(exe), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                  stdin=subprocess.DEVNULL)
        if sys.platform == "win32":
            kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        try:
            self.proc = self.popen(cmd, **kw)
        except Exception as e:
            self.state = "error"; self.log(f"启动 NapCat 失败: {e}")
            return False
        self.state, self.started_at = "running", time.time()
        self.log(f"已启动 NapCat (pid {getattr(self.proc, 'pid', '?')}): {exe}")
        if getattr(self.proc, "stdout", None) is not None:
            threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()
        return True

    def _reader(self, proc):
        try:
            for raw in iter(proc.stdout.readline, b""):
                if not raw:
                    break
                for enc in ("utf-8", "gbk"):
                    try:
                        line = raw.decode(enc).rstrip(); break
                    except UnicodeDecodeError:
                        line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    self.tail.append(line)
        except Exception:
            pass

    def start(self, watchdog=True):
        if self.running:
            return True
        self._stop.clear()
        ok = self._spawn()
        if watchdog and (self._watch is None or not self._watch.is_alive()):
            self._watch = threading.Thread(target=self._watchdog, daemon=True, name="napcat-watchdog")
            self._watch.start()
        return ok

    def check_once(self):
        """看门狗单步: 进程退出则重启(限流). 返回是否发生重启."""
        if self._stop.is_set() or self.proc is None or self.running:
            return False
        code = self.proc.poll()
        now = time.time()
        while self._restart_times and now - self._restart_times[0] > self.restart_window:
            self._restart_times.popleft()
        if len(self._restart_times) >= self.max_restarts:
            if self.state != "crashed":
                self.state = "crashed"
                self.log(f"NapCat 多次退出 (code {code}), 已停止自动重启, 请检查 NapCat 日志")
            return False
        self._restart_times.append(now)
        self.restarts += 1
        self.log(f"NapCat 已退出 (code {code}), 看门狗第 {self.restarts} 次重启")
        self.state = "restarting"
        return self._spawn()

    def _watchdog(self):
        while not self._stop.wait(5):
            try:
                self.check_once()
            except Exception as e:
                self.log(f"NapCat 看门狗出错: {e}")

    def stop(self):
        self._stop.set()
        p = self.proc
        if p and p.poll() is None:
            try:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
                else:
                    p.terminate()
            except Exception:
                pass
        self.state = "stopped"

    def status_text(self):
        return {"running": "运行中", "stopped": "未启动", "missing": "未找到 NapCat", "error": "启动失败",
                "restarting": "重启中", "crashed": "反复崩溃"}.get(self.state, self.state)
