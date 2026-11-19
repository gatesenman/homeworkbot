"""Windows 系统集成: 开机自启、Toast 通知、托盘图标. 非 Windows 下全部安全降级."""
import os, sys, threading

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_KEY = "HomeworkBot"

def launch_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    main = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
    return f'"{pyw if os.path.exists(pyw) else sys.executable}" "{main}" --minimized'

def set_autostart(enable):
    if sys.platform != "win32":
        return False
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enable:
            winreg.SetValueEx(k, APP_KEY, 0, winreg.REG_SZ, launch_command())
        else:
            try: winreg.DeleteValue(k, APP_KEY)
            except FileNotFoundError: pass
    return True

def get_autostart():
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_KEY); return True
    except OSError:
        return False

def toast(title, msg, icon=None):
    """Windows 10/11 Toast 通知; 失败时静默."""
    def run():
        try:
            from win11toast import toast as t
            t(title, msg, icon=icon, duration="short")
        except Exception:
            try:
                from plyer import notification
                notification.notify(title=title, message=msg[:250], app_name="作业小助手", app_icon=icon, timeout=6)
            except Exception:
                pass
    threading.Thread(target=run, daemon=True).start()

class Tray:
    """pystray 托盘图标. actions: dict(show, start, stop, quit)."""
    def __init__(self, icon_path, actions):
        self.icon = None
        try:
            import pystray
            from PIL import Image
            # 托盘优先用 PNG; 失败再试同目录 ico
            path = icon_path
            if not path or not os.path.exists(path):
                alt = os.path.splitext(icon_path or "")[0] + ".ico"
                path = alt if os.path.exists(alt) else icon_path
            img = Image.open(path).convert("RGBA")
            if max(img.size) > 64:
                img = img.resize((64, 64), Image.Resampling.LANCZOS)
            menu = pystray.Menu(
                pystray.MenuItem("打开主界面", lambda: actions["show"](), default=True),
                pystray.MenuItem("开始监听", lambda: actions["start"]()),
                pystray.MenuItem("停止监听", lambda: actions["stop"]()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", lambda: actions["quit"]()))
            self.icon = pystray.Icon("HomeworkBot", img, "作业小助手", menu)
            threading.Thread(target=self.icon.run, daemon=True).start()
        except Exception:
            self.icon = None

    def set_title(self, s):
        if self.icon: self.icon.title = s

    def notify(self, title, msg):
        if self.icon:
            try: self.icon.notify(msg, title)
            except Exception: pass

    def stop(self):
        if self.icon:
            try: self.icon.stop()
            except Exception: pass
