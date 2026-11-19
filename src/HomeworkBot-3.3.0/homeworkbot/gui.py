"""customtkinter 现代化界面 (v3): 侧边栏 + 仪表盘 + 作业历史 + QQ/NapCat 连接 + 企业微信推送 + AI + 日志 + 关于.
图标使用 Windows 图标字体 (Segoe Fluent Icons / MDL2), 不用 emoji."""
import datetime as dt, os, queue, subprocess, sys, threading, time, webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk

from . import __version__, APP_NAME
from .config import (load_config, save_config, split_names, split_lines, parse_group_ids, parse_webhooks,
                     app_dir, resource_dir, resolve_dir, find_asset, DEFAULT_PROMPT, DEFAULT_TEMPLATE,
                     is_setup_complete, validate_webhook_url, validate_webhooks, mask_secret,
                     export_config, import_config, SECRET_KEYS)
from .history import History
from .formatter import apply_template, compose_message, format_homework, render_daily_summary
from .storage import export_records
from .icons import icon
from .subjects import subject_tags
from . import system
from .wizard import SetupWizard
from .checklist import Checklist, render_weekly, render_unfinished
from .napcat import NapCatManager
import calendar, json

ACCENT = "#3B82F6"
FONT = "Microsoft YaHei UI"
NAPCAT_RELEASES = "https://github.com/NapNeko/NapCatQQ/releases"
NAPCAT_DOCS = "https://napneko.github.io/guide/boot/Shell"
WECOM_DOC = "https://developer.work.weixin.qq.com/document/path/91770"
NAV = [("dash", "仪表盘", "home"), ("todo", "今日清单", "list"), ("history", "作业历史", "history"), ("qq", "QQ/NapCat 连接", "plug"),
       ("wecom", "企业微信推送", "send"), ("ai", "AI 设置", "robot"), ("log", "日志", "log"), ("about", "关于", "info")]
API_PRESETS = {
    "DeepSeek": ("https://api.deepseek.com/v1", "deepseek-chat"),
    "通义千问": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    "Kimi(月之暗面)": ("https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    "智谱 GLM": ("https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
    "硅基流动": ("https://api.siliconflow.cn/v1", "deepseek-ai/DeepSeek-V3"),
}
MODES = {"反向 WebSocket(推荐)": "reverse_ws", "正向 WebSocket": "forward_ws", "HTTP 上报": "http_post"}
MODE_NAMES = {v: k for k, v in MODES.items()}
STATUS_TXT = {"pending": ("待确认", "#F59E0B"), "sent": ("已推送", "#22C55E"),
              "failed": ("推送失败", "#EF4444"), "ignored": ("已忽略", "#9CA3AF")}
CONN_TXT = {"connected": ("已连接", "#22C55E"), "waiting": ("等待 NapCat", "#F59E0B"),
            "connecting": ("连接中", "#F59E0B"), "error": ("连接异常", "#EF4444"), "stopped": ("未监听", "#9CA3AF")}

NAPCAT_GUIDE = (
    "1. 下载 NapCat: 打开 NapCat 发布页, 下载 NapCat.Shell.Windows.OneKey.zip (一键版, 无需另装 QQ), 解压后运行 NapCatInstaller.exe。\n"
    "2. 登录: 双击 napcat.bat, 用手机 QQ 扫描控制台/WebUI 中的二维码登录。强烈建议用一个专门的小号, 并让小号加入班级群。\n"
    "3. 打开 WebUI (控制台会显示地址和 token, 默认 http://127.0.0.1:6099/webui) → 网络配置 → 新建:\n"
    "   · 反向 WebSocket(推荐): 新建“WebSocket 客户端”, URL 填下方显示的地址, 消息格式 Array, 启用。\n"
    "   · 正向 WebSocket: 新建“WebSocket 服务端”, 端口如 3001, 本程序填 ws://127.0.0.1:3001。\n"
    "   · HTTP 上报: 新建“HTTP 客户端”, URL 填下方地址; 如需测试连接再建一个“HTTP 服务端”(端口 3000)。\n"
    "   如设置了 token, 两边要填一致。\n"
    "4. 回到本页点“测试连接”, 显示登录的 QQ 号即成功。之后 NapCat 与本程序都可以在后台运行。")
WECOM_GUIDE = (
    "1. 在企业微信里建一个群(家人都需要是企业微信成员, 可用免费的企业微信“家庭/班级”团队)。\n"
    "2. 群聊右上角 ··· → 消息推送(旧称“群机器人”) → 添加 → 新建, 复制 Webhook 地址\n"
    "   (形如 https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx)。\n"
    "3. 粘贴到下方, 每行一个, 可写成“名称|地址”。Webhook 地址相当于密码, 不要外传。\n"
    "4. 点“测试推送”确认群里收到测试消息。每个机器人限 20 条/分钟。")

def F(size=13, bold=False):
    return ctk.CTkFont(family=FONT, size=size, weight="bold" if bold else "normal")

def open_path(p):
    if sys.platform == "win32": os.startfile(p)          # noqa
    else: subprocess.Popen(["xdg-open", p])

def I(name, size=18, white=False):
    return icon(name, size, "#FFFFFF", "#FFFFFF") if white else icon(name, size)


class PreviewDialog(ctk.CTkToplevel):
    """推送前确认: 可编辑文本, 附件勾选推送, 一键推送 / 稍后 / 忽略."""
    KIND_LABEL = {"image": "图片", "file": "文件", "video": "视频", "record": "语音"}

    def __init__(self, app, hid):
        super().__init__(app)
        self.app, self.hid = app, hid
        rec = app.history.get(hid)
        self.atts = [dict(a) for a in (rec.get("attachments") or [])]
        for a in self.atts:
            a.setdefault("send", True)
        self.title("新作业 - 确认后推送到企业微信"); self.geometry("620x680"); self.attributes("-topmost", True)
        ctk.CTkLabel(self, text=f" {rec['result']['subject']}  ·  {rec['date']}", image=I("book", 22),
                     compound="left", font=F(18, True)).pack(anchor="w", padx=18, pady=(16, 2))
        hooks = ", ".join(n for n, _ in parse_webhooks(app.cfg["wecom_webhooks"])) or "(未设置机器人)"
        ctk.CTkLabel(self, text=f"来自 QQ群 {rec['group']} / {rec['sender']}   →   企业微信: {hooks}",
                     font=F(12), text_color="gray").pack(anchor="w", padx=18)
        if app.cfg.get("push_format", "markdown") == "markdown":
            ctk.CTkLabel(self, text="以下为 markdown 源码, ** 加粗与 <font> 颜色标记在企业微信中会显示为排版效果",
                         font=F(11), text_color="gray").pack(anchor="w", padx=18, pady=(6, 0))
        self.box = ctk.CTkTextbox(self, font=F(14), wrap="word"); self.box.pack(fill="both", expand=True, padx=18, pady=10)
        self.box.insert("1.0", rec["message"])
        self.att_vars = []
        if self.atts:
            box = ctk.CTkFrame(self, fg_color="transparent"); box.pack(fill="x", padx=18, pady=(0, 6))
            ctk.CTkLabel(box, text=f"附件 ({len(self.atts)}) — 勾选后一并推送", image=I("photo"),
                         compound="left", font=F(13, True)).pack(anchor="w")
            for a in self.atts:
                row = ctk.CTkFrame(box, fg_color="transparent"); row.pack(fill="x", pady=2)
                var = tk.BooleanVar(value=bool(a.get("send", True)))
                self.att_vars.append(var)
                kind = self.KIND_LABEL.get(a.get("kind"), a.get("kind") or "附件")
                size = a.get("size") or (os.path.getsize(a["path"]) if a.get("path") and os.path.exists(a["path"]) else 0)
                from homeworkbot.wecom import human_size
                label = f"[{kind}] {a.get('name') or os.path.basename(a.get('path') or '')}  ({human_size(size)})"
                ctk.CTkCheckBox(row, text=label, variable=var, font=F(12)).pack(side="left")
                if a.get("path") and os.path.exists(a["path"]):
                    ctk.CTkButton(row, text="打开", width=50, height=24, fg_color="transparent", border_width=1,
                                  text_color=("gray10", "gray90"),
                                  command=lambda p=a["path"]: open_path(p)).pack(side="right")
        bar = ctk.CTkFrame(self, fg_color="transparent"); bar.pack(fill="x", padx=18, pady=12)
        ctk.CTkButton(bar, text=" 推送到企业微信", image=I("send", 18, True), font=F(14, True), height=38,
                      command=self.send).pack(side="right")
        ctk.CTkButton(bar, text=" 稍后处理", image=I("clock", 18, True), fg_color="gray", height=38,
                      command=self.destroy).pack(side="right", padx=8)
        ctk.CTkButton(bar, text=" 忽略", image=I("cancel"), fg_color="transparent", border_width=1,
                      text_color=("gray10", "gray90"), height=38, command=self.ignore).pack(side="left")
        self.after(150, self.focus_force)

    def send(self):
        text = self.box.get("1.0", "end").strip()
        atts = []
        for a, var in zip(self.atts, self.att_vars):
            a = dict(a); a["send"] = bool(var.get()); atts.append(a)
        self.destroy(); self.app.send_record(self.hid, text, atts)

    def ignore(self):
        self.app.history.mark(self.hid, "ignored"); self.destroy(); self.app.refresh()


class App(ctk.CTk):
    def __init__(self, minimized=False):
        super().__init__()
        self.base, self.res = app_dir(), resource_dir()
        self.cfg = load_config()
        ctk.set_appearance_mode(self.cfg.get("theme", "system"))
        ctk.set_default_color_theme("blue")
        self.data_dir = os.path.join(self.base, "data"); os.makedirs(self.data_dir, exist_ok=True)
        self.history = History(os.path.join(self.data_dir, "history.db"))
        self.checklist = Checklist(os.path.join(self.data_dir, "history.db"))
        self.todo_date = dt.date.today()
        self.napcat = NapCatManager(self.cfg.get("napcat_dir", ""), self.cfg.get("napcat_args", ""), log=self.log)
        self.log_file = os.path.join(self.data_dir, "homeworkbot.log")
        self.q, self.engine, self.dialogs, self.w = queue.Queue(), None, {}, {}
        self.icon_png = find_asset("assets", "icon.png")
        self.icon_ico = find_asset("assets", "icon.ico")
        self.title(f"{APP_NAME} v{__version__}"); self.geometry("1100x740"); self.minsize(960, 640)
        self._apply_window_icon()
        self.grid_columnconfigure(1, weight=1); self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self.pages = {}
        for key, _, _ in NAV:
            p = ctk.CTkScrollableFrame(self, fg_color="transparent") if key in ("qq", "wecom", "ai", "about") \
                else ctk.CTkFrame(self, fg_color="transparent")
            self.pages[key] = p
            getattr(self, f"_page_{key}")(p)
        self.show("dash")
        self.tray = system.Tray(self.icon_png, {"show": lambda: self.after(0, self.show_window),
                                                "start": lambda: self.after(0, self.start),
                                                "stop": lambda: self.after(0, self.stop),
                                                "quit": lambda: self.after(0, self.quit_app)})
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(200, self.pump); self.after(1000, self.tick)
        self.log(f"{APP_NAME} v{__version__} 已启动, 数据目录: {self.data_dir}")
        if minimized or self.cfg.get("start_minimized"):
            if self.tray.icon:
                self.withdraw()
        if self.cfg.get("auto_listen", True) or minimized:
            self.after(800, lambda: self.start(quiet=True))
        if self.cfg.get("napcat_autostart") and self.cfg.get("napcat_dir"):
            self.after(300, lambda: self.napcat.start(watchdog=self.cfg.get("napcat_watchdog", True)))
        if not is_setup_complete(self.cfg) and not minimized:
            self.after(500, self.open_wizard)

    # ================= 框架 =================
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=210, corner_radius=0); sb.grid(row=0, column=0, sticky="nsw")
        sb.grid_propagate(False)
        try:
            from PIL import Image
            (ctk.CTkLabel(sb, image=ctk.CTkImage(Image.open(self.icon_png), size=(44, 44)), text="") if self.icon_png and os.path.exists(self.icon_png) else ctk.CTkLabel(sb, text="HB", font=ctk.CTkFont(size=18, weight="bold"), text_color="#3B82F6")).pack(pady=(22, 4))
        except Exception:
            pass
        ctk.CTkLabel(sb, text=APP_NAME, font=F(20, True)).pack()
        ctk.CTkLabel(sb, text="QQ 班级群 → 企业微信", font=F(11), text_color="gray").pack(pady=(0, 18))
        self.nav_btns = {}
        for key, text, ic in NAV:
            b = ctk.CTkButton(sb, text="  " + text, image=I(ic), anchor="w", font=F(14), height=40, corner_radius=8,
                              fg_color="transparent", text_color=("gray10", "gray90"),
                              hover_color=("gray80", "gray25"), command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=12, pady=2); self.nav_btns[key] = (b, ic)
        box = ctk.CTkFrame(sb, fg_color="transparent"); box.pack(side="bottom", pady=14)
        self.side_dot = ctk.CTkLabel(box, text="●", font=F(16), text_color="#9CA3AF"); self.side_dot.pack(side="left")
        self.side_status = ctk.CTkLabel(box, text=" 未监听", font=F(13, True)); self.side_status.pack(side="left")
        self.theme_seg = ctk.CTkSegmentedButton(sb, values=["浅色", "深色", "跟随系统"], command=self.set_theme)
        self.theme_seg.set({"light": "浅色", "dark": "深色"}.get(self.cfg["theme"], "跟随系统"))
        self.theme_seg.pack(side="bottom", padx=12, pady=4)

    def _apply_window_icon(self):
        """设置窗口/任务栏图标. 同时用 iconbitmap(.ico) + iconphoto(PNG) + Win32 WM_SETICON, 防止某一路径失败."""
        self._icon_photos = []  # 防止 PhotoImage 被 GC
        ico, png = self.icon_ico, self.icon_png
        if ico and os.path.exists(ico):
            try:
                self.iconbitmap(default=ico)
            except Exception:
                try: self.iconbitmap(ico)
                except Exception as e: self.log(f"iconbitmap 失败: {e}") if hasattr(self, "log") else None
        if png and os.path.exists(png):
            try:
                from PIL import Image, ImageTk
                for s in (16, 32, 48, 64):
                    im = Image.open(png).resize((s, s), Image.Resampling.LANCZOS)
                    ph = ImageTk.PhotoImage(im)
                    self._icon_photos.append(ph)
                if self._icon_photos:
                    self.iconphoto(True, *self._icon_photos)
            except Exception:
                try:
                    ph = tk.PhotoImage(file=png)
                    self._icon_photos.append(ph)
                    self.iconphoto(True, ph)
                except Exception:
                    pass
        # Win32: 强制任务栏/标题栏图标 (customtkinter 有时不刷新)
        if sys.platform == "win32" and ico and os.path.exists(ico):
            try:
                import ctypes
                from ctypes import wintypes
                self.update_idletasks()
                hwnd = self.winfo_id()
                # 若是 Tk 子窗口, 取顶层
                user32 = ctypes.windll.user32
                GA_ROOT = 2
                root = user32.GetAncestor(hwnd, GA_ROOT) or hwnd
                IMAGE_ICON, LR_LOADFROMFILE = 1, 0x0010
                WM_SETICON, ICON_SMALL, ICON_BIG = 0x0080, 0, 1
                hicon_big = user32.LoadImageW(None, ico, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
                hicon_sm = user32.LoadImageW(None, ico, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
                if hicon_big: user32.SendMessageW(root, WM_SETICON, ICON_BIG, hicon_big)
                if hicon_sm: user32.SendMessageW(root, WM_SETICON, ICON_SMALL, hicon_sm)
                self._win_hicons = (hicon_big, hicon_sm)
            except Exception:
                pass


    def show(self, key):
        for k, p in self.pages.items():
            p.grid_forget()
            b, ic = self.nav_btns[k]
            sel = k == key
            b.configure(fg_color=ACCENT if sel else "transparent", text_color="white" if sel else ("gray10", "gray90"),
                        image=I(ic, 18, sel))
        self.pages[key].grid(row=0, column=1, sticky="nsew", padx=20, pady=16)
        if key in ("dash", "history"): self.refresh()
        if key == "todo": self.refresh_todo()

    def set_theme(self, v):
        mode = {"浅色": "light", "深色": "dark"}.get(v, "system")
        ctk.set_appearance_mode(mode); self.cfg["theme"] = mode; save_config(self.cfg)

    def header(self, parent, title, sub=""):
        ctk.CTkLabel(parent, text=title, font=F(24, True)).pack(anchor="w")
        if sub: ctk.CTkLabel(parent, text=sub, font=F(12), text_color="gray").pack(anchor="w", pady=(0, 10))

    def card(self, parent, title=None, ic=None):
        c = ctk.CTkFrame(parent, corner_radius=12); c.pack(fill="x", pady=8)
        if title:
            ctk.CTkLabel(c, text=" " + title, image=I(ic) if ic else None, compound="left",
                         font=F(15, True)).pack(anchor="w", padx=16, pady=(12, 4))
        return c

    def field(self, parent, key, label, hint="", show="", width=420):
        row = ctk.CTkFrame(parent, fg_color="transparent"); row.pack(fill="x", padx=16, pady=5)
        ctk.CTkLabel(row, text=label, font=F(13), width=140, anchor="w").pack(side="left")
        var = tk.StringVar(value=str(self.cfg.get(key, "")))
        ctk.CTkEntry(row, textvariable=var, width=width, show=show, font=F(13), placeholder_text=hint).pack(side="left")
        self.w[key] = var
        return row

    def textfield(self, parent, key, label, hint="", height=80):
        ctk.CTkLabel(parent, text=label, font=F(13)).pack(anchor="w", padx=16, pady=(6, 0))
        if hint: ctk.CTkLabel(parent, text=hint, font=F(11), text_color="gray", justify="left").pack(anchor="w", padx=16)
        t = ctk.CTkTextbox(parent, height=height, font=F(13)); t.pack(fill="x", padx=16, pady=4)
        v = self.cfg.get(key, "")
        t.insert("1.0", "\n".join(map(str, v)) if isinstance(v, list) else v); self.w[key] = t
        return t

    def switch(self, parent, key, label):
        v = tk.BooleanVar(value=bool(self.cfg.get(key)))
        ctk.CTkSwitch(parent, text=label, variable=v, font=F(13)).pack(anchor="w", padx=16, pady=5)
        self.w[key] = v

    def button(self, parent, text, ic, cmd, primary=True, **kw):
        if primary:
            return ctk.CTkButton(parent, text=" " + text, image=I(ic, 18, True), command=cmd, font=F(13), **kw)
        return ctk.CTkButton(parent, text=" " + text, image=I(ic), command=cmd, font=F(13), fg_color="transparent",
                             border_width=1, text_color=("gray10", "gray90"), **kw)

    def guide(self, parent, title, text, links):
        c = self.card(parent, title, "help")
        ctk.CTkLabel(c, text=text, font=F(12), justify="left", anchor="w", wraplength=760).pack(anchor="w", padx=16, pady=(0, 6))
        bar = ctk.CTkFrame(c, fg_color="transparent"); bar.pack(fill="x", padx=16, pady=(0, 12))
        for t, url in links:
            self.button(bar, t, "globe", lambda u=url: webbrowser.open(u), False).pack(side="left", padx=(0, 8))

    def save_btn(self, parent):
        self.button(parent, "保存设置", "save", self.save, height=38).pack(anchor="e", pady=12, side="right")

    # ================= 仪表盘 =================
    def _page_dash(self, p):
        top = ctk.CTkFrame(p, fg_color="transparent"); top.pack(fill="x")
        self.header(top, "仪表盘", "后台监听 QQ 班级群, 老师发布作业后自动整理并推送企业微信")
        self.run_btn = self.button(top, "开始监听", "play", self.toggle, width=150, height=42)
        self.run_btn.place(relx=1.0, y=4, anchor="ne")
        self.offline_banner = ctk.CTkFrame(p, fg_color="#FEF2F2", corner_radius=10, border_width=1, border_color="#FECACA")
        self.offline_banner.pack(fill="x", pady=(0, 6))
        self.offline_lbl = ctk.CTkLabel(self.offline_banner, text="", font=F(13, True), text_color="#B91C1C",
                                        image=I("warning", 18), compound="left", anchor="w")
        self.offline_lbl.pack(side="left", padx=12, pady=8)
        self.reconnect_btn = self.button(self.offline_banner, "重新连接", "refresh", self.reconnect, width=110, height=32)
        self.reconnect_btn.pack(side="right", padx=10, pady=6)
        self.offline_banner.pack_forget()
        stats = ctk.CTkFrame(p, fg_color="transparent"); stats.pack(fill="x", pady=6)
        self.stat = {}
        for i, (k, t, c, ic) in enumerate([("conn", "NapCat 连接", "#3B82F6", "plug"), ("last", "最近消息", "#8B5CF6", "chat"),
                                           ("today", "今日作业", "#22C55E", "book"), ("pending", "待确认", "#F59E0B", "clock"),
                                           ("total", "累计记录", "#06B6D4", "history")]):
            stats.grid_columnconfigure(i, weight=1)
            c_ = ctk.CTkFrame(stats, corner_radius=12, border_width=2, border_color=c)
            c_.grid(row=0, column=i, sticky="nsew", padx=5)
            ctk.CTkLabel(c_, text=" " + t, image=I(ic, 16), compound="left", font=F(12), text_color="gray").pack(pady=(12, 0))
            self.stat[k] = ctk.CTkLabel(c_, text="-", font=F(19, True), text_color=c); self.stat[k].pack(pady=(2, 12))
        self.conn_lbl = ctk.CTkLabel(p, text="", font=F(12), text_color="gray", anchor="w"); self.conn_lbl.pack(fill="x")
        self.err_lbl = ctk.CTkLabel(p, text="", font=F(12), text_color="#EF4444", anchor="w"); self.err_lbl.pack(fill="x")
        bar = ctk.CTkFrame(p, fg_color="transparent"); bar.pack(fill="x", pady=(6, 0))
        ctk.CTkLabel(bar, text="今日作业", font=F(17, True)).pack(side="left")
        self.button(bar, "推送今日汇总", "send", self.push_summary, False, width=120).pack(side="right")
        self.button(bar, "重新连接", "refresh", self.reconnect, False, width=100).pack(side="right", padx=6)
        self.button(bar, "测试连接", "plug", self.test_conn, False, width=100).pack(side="right", padx=6)
        self.today_box = ctk.CTkScrollableFrame(p, fg_color="transparent"); self.today_box.pack(fill="both", expand=True)

    def hw_card(self, parent, rec):
        r = rec["result"]; st, color = STATUS_TXT.get(rec["status"], (rec["status"], "gray"))
        c = ctk.CTkFrame(parent, corner_radius=12); c.pack(fill="x", pady=6, padx=2)
        head = ctk.CTkFrame(c, fg_color="transparent"); head.pack(fill="x", padx=14, pady=(10, 0))
        tags = ctk.CTkFrame(head, fg_color="transparent"); tags.pack(side="left")
        for name, col in subject_tags(r.get("subject")):
            ctk.CTkLabel(tags, text=f"  {name}  ", font=F(12, True), fg_color=col, text_color="white",
                         corner_radius=8).pack(side="left", padx=(0, 4))
        ctk.CTkLabel(head, text=f"  {st}  ", font=F(11, True), fg_color=color, text_color="white",
                     corner_radius=8).pack(side="left", padx=6)
        ctk.CTkLabel(head, text=f"{rec['sender']} · 群{rec['group']} · {rec['created'][11:16]}",
                     font=F(11), text_color="gray").pack(side="right")
        items = "\n".join(f"{i}. {x}" for i, x in enumerate(r["items"], 1)) or "(无条目)"
        ctk.CTkLabel(c, text=items, font=F(13), justify="left", anchor="w", wraplength=640).pack(fill="x", padx=18, pady=4)
        atts = rec.get("attachments") or []
        if atts:
            chips = ctk.CTkFrame(c, fg_color="transparent"); chips.pack(fill="x", padx=14, pady=(0, 2))
            KIND = {"image": "图片", "file": "文件", "video": "视频", "record": "语音"}
            for a in atts[:8]:
                lab = KIND.get(a.get("kind"), "附件")
                nm = (a.get("name") or "")[:18]
                ctk.CTkLabel(chips, text=f"  {lab}:{nm}  " if nm else f"  {lab}  ", font=F(11),
                             fg_color=("gray85", "gray25"), corner_radius=6).pack(side="left", padx=3, pady=2)
            if len(atts) > 8:
                ctk.CTkLabel(chips, text=f" +{len(atts)-8} ", font=F(11), text_color="gray").pack(side="left")
        if rec.get("error") and rec["status"] == "failed":
            ctk.CTkLabel(c, text="失败: " + (rec["error"] or "")[:120], font=F(11), text_color="#EF4444",
                         anchor="w", wraplength=640).pack(fill="x", padx=18, pady=(0, 2))
        foot = ctk.CTkFrame(c, fg_color="transparent"); foot.pack(fill="x", padx=14, pady=(0, 10))
        if r.get("deadline"):
            ctk.CTkLabel(foot, text=" 截止: " + r["deadline"], image=I("clock", 16), compound="left",
                         font=F(12), text_color="#F59E0B").pack(side="left")
        self.button(foot, "复制", "copy", lambda m=rec.get("message",""): self.copy_text(m), False, width=70).pack(side="right", padx=(6, 0))
        if rec["status"] == "failed":
            self.button(foot, "重试", "refresh", lambda: self.retry_record(rec["id"]), width=80).pack(side="right")
        else:
            self.button(foot, "推送" if rec["status"] != "sent" else "重新推送", "send",
                        lambda: self.open_preview(rec["id"]), width=90).pack(side="right")


    # ================= 今日清单 =================
    def _page_todo(self, p):
        top = ctk.CTkFrame(p, fg_color="transparent"); top.pack(fill="x")
        self.header(top, "今日清单", "老师布置的每条作业自动变成当天待办; 完成后打勾, 晚上自动提醒未完成项")
        self.button(top, "推送本周周报", "send", self.push_weekly, False, width=130).place(relx=1.0, y=4, anchor="ne")
        body = ctk.CTkFrame(p, fg_color="transparent"); body.pack(fill="both", expand=True, pady=6)
        body.grid_columnconfigure(1, weight=1); body.grid_rowconfigure(0, weight=1)
        cal = ctk.CTkFrame(body, corner_radius=12, width=330); cal.grid(row=0, column=0, sticky="nsw")
        nav = ctk.CTkFrame(cal, fg_color="transparent"); nav.pack(fill="x", padx=10, pady=(10, 4))
        ctk.CTkButton(nav, text="", image=I("chevl"), width=32, fg_color="transparent", hover_color=("gray80", "gray25"),
                      command=lambda: self.shift_month(-1)).pack(side="left")
        self.cal_title = ctk.CTkLabel(nav, text="", font=F(15, True)); self.cal_title.pack(side="left", expand=True)
        ctk.CTkButton(nav, text="", image=I("chevr"), width=32, fg_color="transparent", hover_color=("gray80", "gray25"),
                      command=lambda: self.shift_month(1)).pack(side="right")
        self.cal_grid = ctk.CTkFrame(cal, fg_color="transparent"); self.cal_grid.pack(padx=10, pady=4)
        ctk.CTkLabel(cal, text="圆点: 绿=全部完成  橙=未完成", font=F(11), text_color="gray").pack(pady=(2, 4))
        self.button(cal, "回到今天", "calendar", lambda: self.pick_day(dt.date.today()), False, width=110).pack(pady=(0, 12))
        self.cal_month = (self.todo_date.year, self.todo_date.month)
        right = ctk.CTkFrame(body, corner_radius=12); right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.todo_title = ctk.CTkLabel(right, text="", font=F(17, True)); self.todo_title.pack(anchor="w", padx=16, pady=(12, 2))
        pr = ctk.CTkFrame(right, fg_color="transparent"); pr.pack(fill="x", padx=16)
        self.todo_bar = ctk.CTkProgressBar(pr, height=14, progress_color="#22C55E"); self.todo_bar.pack(side="left", fill="x", expand=True)
        self.todo_pct = ctk.CTkLabel(pr, text="", font=F(13, True), width=90); self.todo_pct.pack(side="left", padx=8)
        self.todo_list = ctk.CTkScrollableFrame(right, fg_color="transparent"); self.todo_list.pack(fill="both", expand=True, padx=10, pady=8)
        add = ctk.CTkFrame(right, fg_color="transparent"); add.pack(fill="x", padx=16, pady=(0, 12))
        self.todo_new = ctk.CTkEntry(add, placeholder_text="手动添加一项, 如: 数学: 订正试卷", font=F(13))
        self.todo_new.pack(side="left", fill="x", expand=True)
        self.todo_new.bind("<Return>", lambda e: self.add_todo())
        self.button(add, "添加", "add", self.add_todo, width=80).pack(side="left", padx=6)
        self.button(add, "提醒未完成", "bell", self.remind_now, False, width=110).pack(side="left")

    def shift_month(self, d):
        y, m = self.cal_month; m += d
        if m < 1: y, m = y - 1, 12
        if m > 12: y, m = y + 1, 1
        self.cal_month = (y, m); self.render_calendar()

    def pick_day(self, day):
        self.todo_date = day; self.cal_month = (day.year, day.month); self.refresh_todo()

    def render_calendar(self):
        for c in self.cal_grid.winfo_children(): c.destroy()
        y, m = self.cal_month
        self.cal_title.configure(text=f"{y} 年 {m} 月")
        marks = self.checklist.month_days(y, m)
        for i, wd in enumerate("一二三四五六日"):
            ctk.CTkLabel(self.cal_grid, text=wd, font=F(11), text_color="gray", width=40).grid(row=0, column=i)
        today = dt.date.today()
        for r, week in enumerate(calendar.Calendar().monthdayscalendar(y, m), 1):
            for col, d in enumerate(week):
                if not d: continue
                day = dt.date(y, m, d)
                done, tot = marks.get(d, (0, 0))
                dot = "\n●" if tot else "\n "
                sel = day == self.todo_date
                color = "#22C55E" if tot and done >= tot else ("#F59E0B" if tot else ("gray10", "gray90"))
                ctk.CTkButton(self.cal_grid, text=f"{d}{dot}", width=40, height=40, font=F(12, day == today),
                              corner_radius=8, fg_color=ACCENT if sel else "transparent",
                              text_color="white" if sel else color, hover_color=("gray80", "gray25"),
                              border_width=1 if day == today else 0, border_color=ACCENT,
                              command=lambda dd=day: self.pick_day(dd)).grid(row=r, column=col, padx=1, pady=1)

    def refresh_todo(self):
        if not hasattr(self, "todo_list"): return
        self.render_calendar()
        d = self.todo_date.isoformat()
        rows = self.checklist.by_date(d)
        done, tot, pct = self.checklist.progress(d)
        wk = "一二三四五六日"[self.todo_date.weekday()]
        self.todo_title.configure(text=f"{d}  星期{wk}" + ("  (今天)" if self.todo_date == dt.date.today() else ""))
        self.todo_bar.set(pct); self.todo_pct.configure(text=f"{done}/{tot}  {pct:.0%}" if tot else "无作业")
        for c in self.todo_list.winfo_children(): c.destroy()
        if not rows:
            ctk.CTkLabel(self.todo_list, text="这一天没有作业", font=F(14), text_color="gray").pack(pady=40)
        for r in rows:
            row = ctk.CTkFrame(self.todo_list, corner_radius=8); row.pack(fill="x", pady=3)
            col = subject_tags(r["subject"])[0][1]
            ctk.CTkLabel(row, text=f" {r['subject']} ", font=F(11, True), fg_color=col, text_color="white",
                         corner_radius=6).pack(side="left", padx=8, pady=8)
            v = tk.BooleanVar(value=bool(r["done"]))
            ctk.CTkCheckBox(row, text=r["text"], variable=v, font=F(13), checkbox_width=22, checkbox_height=22,
                            text_color=("gray50", "gray55") if r["done"] else ("gray10", "gray90"),
                            command=lambda t=r["id"], vv=v: self.tick_todo(t, vv.get())).pack(side="left", fill="x", expand=True)

    def tick_todo(self, tid, done):
        self.checklist.set_done(tid, done); self.refresh_todo()
        _, tot, pct = self.checklist.progress(self.todo_date.isoformat())
        if done and tot and pct >= 1: self.toast_ui("今天的作业全部完成, 真棒")

    def add_todo(self):
        t = self.todo_new.get().strip()
        if not t: return
        from .checklist import guess_subject
        self.checklist.add(self.todo_date.isoformat(), t, guess_subject(t, "其他"))
        self.todo_new.delete(0, "end"); self.refresh_todo()

    def _engine_for_send(self):
        if not parse_webhooks(self.cfg.get("wecom_webhooks", [])):
            messagebox.showwarning("提示", "请先在[企业微信推送]里填写 Webhook 地址"); return None
        return self.engine or self.make_engine()

    def remind_now(self):
        d = self.todo_date.isoformat()
        text = render_unfinished(self.checklist.unfinished(d), d, self.cfg.get("child_name", ""))
        if not text: self.toast_ui("这一天没有未完成项"); return
        if messagebox.askyesno("推送未完成提醒", text + "\n\n确认推送到企业微信?"):
            eng = self._engine_for_send()
            if eng: self.bg(lambda: (eng.send_text(text), self.log("已手动推送未完成提醒")))

    def push_weekly(self):
        text = render_weekly(self.checklist.weekly(dt.date.today().isoformat()), self.cfg.get("child_name", ""))
        if messagebox.askyesno("本周周报", text + "\n\n确认推送到企业微信?"):
            eng = self._engine_for_send()
            if eng: self.bg(lambda: (eng.send_text(text), self.log("已手动推送周报")))

    # ================= NapCat 管理 =================
    def _napcat_card(self, p):
        c = self.card(p, "NapCat 管理(可选: 由本程序启动并守护 NapCat)", "settings")
        row = self.field(c, "napcat_dir", "NapCat 目录", "如 D:\\NapCat.Shell", width=330)
        self.button(row, "浏览", "folder", self.pick_napcat, False, width=80).pack(side="left", padx=6)
        self.field(c, "napcat_args", "启动参数", "可填小号 QQ 号以快速登录", width=200)
        self.field(c, "napcat_webui", "WebUI 地址", width=300)
        self.switch(c, "napcat_autostart", "随本程序自动启动 NapCat")
        self.switch(c, "napcat_watchdog", "NapCat 意外退出时自动重启(看门狗)")
        bar = ctk.CTkFrame(c, fg_color="transparent"); bar.pack(fill="x", padx=16, pady=6)
        self.nc_dot = ctk.CTkLabel(bar, text="●", font=F(16), text_color="#9CA3AF"); self.nc_dot.pack(side="left")
        self.nc_state = ctk.CTkLabel(bar, text=" 未启动", font=F(13, True)); self.nc_state.pack(side="left")
        self.button(bar, "打开 WebUI", "globe", lambda: webbrowser.open(self.w["napcat_webui"].get().strip() or "http://127.0.0.1:6099/webui"),
                    False, width=110).pack(side="right")
        self.button(bar, "停止", "stop", self.napcat_stop, False, width=80).pack(side="right", padx=6)
        self.button(bar, "启动 NapCat", "play", self.napcat_start, width=120).pack(side="right")
        ctk.CTkLabel(c, text="NapCat 日志(最近)", font=F(12), text_color="gray").pack(anchor="w", padx=16)
        self.nc_log = ctk.CTkTextbox(c, height=110, font=ctk.CTkFont(family="Consolas", size=11)); self.nc_log.pack(fill="x", padx=16, pady=(2, 12))
        self._nc_tail_len = -1

    def pick_napcat(self):
        d = filedialog.askdirectory()
        if d: self.w["napcat_dir"].set(d)

    def napcat_start(self):
        self.collect(); save_config(self.cfg)
        self.napcat.folder, self.napcat.args = self.cfg["napcat_dir"], self.cfg["napcat_args"]
        if not self.napcat.launcher:
            messagebox.showwarning("NapCat", "在该目录没找到 napcat.bat / launcher.bat, 请选择 NapCat.Shell 解压目录"); return
        self.napcat.start(watchdog=self.cfg.get("napcat_watchdog", True))

    def napcat_stop(self):
        threading.Thread(target=self.napcat.stop, daemon=True).start()

    def update_napcat(self):
        if not hasattr(self, "nc_state"): return
        st = self.napcat.state
        color = {"running": "#22C55E", "restarting": "#F59E0B", "crashed": "#EF4444", "error": "#EF4444",
                 "missing": "#EF4444"}.get(st, "#9CA3AF")
        extra = f"  (已自动重启 {self.napcat.restarts} 次)" if self.napcat.restarts else ""
        self.nc_dot.configure(text_color=color); self.nc_state.configure(text=" " + self.napcat.status_text() + extra)
        n = len(self.napcat.tail)
        if n != self._nc_tail_len:
            self._nc_tail_len = n
            self.nc_log.delete("1.0", "end"); self.nc_log.insert("1.0", "\n".join(list(self.napcat.tail)[-40:])); self.nc_log.see("end")

    # ================= 提醒设置 =================
    def _remind_card(self, p):
        c = self.card(p, "作业提醒与周报", "bell")
        self._remind_anchor = c
        self.switch(c, "evening_reminder", "晚间提醒: 到点仍有未完成的作业时弹通知")
        self.field(c, "evening_reminder_time", "晚间提醒时间", "20:00", width=100)
        self.switch(c, "evening_push", "晚间提醒同时推送到企业微信")
        self.switch(c, "morning_reminder", "早晨提醒: 含“签字/带”的作业, 出门前推送检查清单")
        self.field(c, "morning_reminder_time", "早晨提醒时间", "07:00", width=100)
        self.switch(c, "weekly_report", "每周日晚推送本周周报(按科目统计, 完成率)")
        self.field(c, "weekly_report_time", "周报时间", "20:30", width=100)
        ctk.CTkLabel(c, text="提醒在“开始监听”后由后台定时执行。", font=F(11), text_color="gray").pack(anchor="w", padx=16, pady=(0, 12))

    # ================= 历史 =================
    def _page_history(self, p):
        self.header(p, "作业历史", "按日期、科目、关键词检索; 可重新推送或导出")
        f = ctk.CTkFrame(p, corner_radius=12); f.pack(fill="x", pady=6)
        self.hf = {}
        for k, ph, w in [("from", "开始日期 2026-09-01", 150), ("to", "结束日期", 140), ("subject", "科目", 90), ("kw", "关键词", 140)]:
            e = ctk.CTkEntry(f, placeholder_text=ph, width=w); e.pack(side="left", padx=6, pady=10); self.hf[k] = e
        self.hf["status"] = ctk.CTkOptionMenu(f, values=["全部", "待确认", "已推送", "推送失败", "已忽略"], width=100)
        self.hf["status"].pack(side="left", padx=6)
        self.button(f, "搜索", "search", self.refresh_history, width=80).pack(side="left", padx=6)
        body = ctk.CTkFrame(p, fg_color="transparent"); body.pack(fill="both", expand=True)
        body.grid_columnconfigure(1, weight=1); body.grid_rowconfigure(0, weight=1)
        self.hlist = ctk.CTkScrollableFrame(body, width=320); self.hlist.grid(row=0, column=0, sticky="nsew")
        right = ctk.CTkFrame(body, corner_radius=12); right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.h_title = ctk.CTkLabel(right, text="选择左侧记录查看详情", font=F(15, True)); self.h_title.pack(anchor="w", padx=14, pady=10)
        self.h_text = ctk.CTkTextbox(right, font=F(13), wrap="word"); self.h_text.pack(fill="both", expand=True, padx=14)
        bar = ctk.CTkFrame(right, fg_color="transparent"); bar.pack(fill="x", padx=14, pady=10)
        self.button(bar, "重新推送", "send", self.resend_selected, width=100).pack(side="left")
        self.button(bar, "一键重试", "refresh", self.retry_selected, width=100).pack(side="left", padx=6)
        self.button(bar, "复制正文", "copy", self.copy_selected, False, width=90).pack(side="left")
        self.button(bar, "原文", "eye", self.show_original, False, width=70).pack(side="left", padx=6)
        self.button(bar, "图片", "photo", self.show_images, False, width=70).pack(side="left")
        self.button(bar, "存档文件夹", "folder", lambda: open_path(self._save_dir()), False,
                    width=110).pack(side="left", padx=6)
        self.button(bar, "导出", "download", self.export, width=80, fg_color="#22C55E").pack(side="right")
        self.h_sel, self.h_rows = None, []

    def refresh_history(self):
        st = {"待确认": "pending", "已推送": "sent", "推送失败": "failed", "已忽略": "ignored"}.get(self.hf["status"].get(), "")
        self.h_rows = self.history.search(self.hf["from"].get().strip(), self.hf["to"].get().strip(),
                                          self.hf["subject"].get().strip(), self.hf["kw"].get().strip(), st)
        for c in self.hlist.winfo_children(): c.destroy()
        if not self.h_rows:
            ctk.CTkLabel(self.hlist, text="没有记录", text_color="gray").pack(pady=20)
        for rec in self.h_rows[:300]:
            st_t, _ = STATUS_TXT.get(rec["status"], ("", "gray"))
            ctk.CTkButton(self.hlist, text=f"{rec['date']}  {rec['result']['subject']}\n{st_t} · {rec['sender']}"
                          + (f" · {len(rec.get('attachments') or [])}附件" if rec.get("attachments") else ""),
                          anchor="w", height=48, font=F(12), fg_color=("gray85", "gray20"), text_color=("gray10", "gray90"),
                          hover_color=("gray75", "gray30"), command=lambda r=rec: self.select_history(r)).pack(fill="x", pady=3)

    def select_history(self, rec):
        self.h_sel = rec["id"]
        st_t, _ = STATUS_TXT.get(rec["status"], ("", ""))
        self.h_title.configure(text=f"{rec['date']} {rec['result']['subject']}  [{st_t}]" + (f"  {rec['error'][:50]}" if rec.get("error") else ""))
        self.h_text.delete("1.0", "end"); self.h_text.insert("1.0", rec["message"])

    def show_original(self):
        if self.h_sel:
            messagebox.showinfo("原始消息", self.history.get(self.h_sel)["original"] or "(无文字, 仅图片)")

    def show_images(self):
        if self.h_sel:
            atts = self.history.get(self.h_sel).get("attachments") or []
            paths = [a["path"] for a in atts if a.get("path") and os.path.exists(a["path"])]
            if not paths: messagebox.showinfo("提示", "这条记录没有附件")
            for p in paths: open_path(p)

    def resend_selected(self):
        if self.h_sel:
            self.send_record(self.h_sel, self.h_text.get("1.0", "end").strip())

    def export(self):
        if not self.h_rows: messagebox.showinfo("提示", "当前没有可导出的记录"); return
        p = filedialog.asksaveasfilename(defaultextension=".md", initialfile=f"作业导出_{dt.date.today()}.md",
                                         filetypes=[("Markdown", "*.md"), ("Excel 可打开的 CSV", "*.csv"), ("文本", "*.txt")])
        if p:
            export_records(list(reversed(self.h_rows)), p); self.log(f"已导出 {len(self.h_rows)} 条到 {p}")

    # ================= QQ / NapCat =================
    def _page_qq(self, p):
        self.header(p, "QQ / NapCat 连接", "通过 NapCat(OneBot v11) 在后台接收 QQ 群消息, 无需打开 QQ 窗口")
        c = self.card(p, "连接状态", "plug")
        row = ctk.CTkFrame(c, fg_color="transparent"); row.pack(fill="x", padx=16, pady=(0, 12))
        self.qq_dot = ctk.CTkLabel(row, text="●", font=F(18), text_color="#9CA3AF"); self.qq_dot.pack(side="left")
        self.qq_state = ctk.CTkLabel(row, text=" 未监听", font=F(14, True)); self.qq_state.pack(side="left")
        self.button(row, "测试连接", "plug", self.test_conn, width=110).pack(side="right")
        self.button(row, "复制地址", "copy", self.copy_addr, False, width=100).pack(side="right", padx=6)
        self.qq_detail = ctk.CTkLabel(c, text="", font=F(12), text_color="gray", anchor="w", justify="left")
        self.qq_detail.pack(fill="x", padx=16, pady=(0, 12))

        c = self.card(p, "连接方式", "settings")
        row = ctk.CTkFrame(c, fg_color="transparent"); row.pack(fill="x", padx=16, pady=5)
        ctk.CTkLabel(row, text="方式", width=140, anchor="w").pack(side="left")
        self.mode_var = tk.StringVar(value=MODE_NAMES.get(self.cfg["onebot_mode"], list(MODES)[0]))
        ctk.CTkSegmentedButton(row, values=list(MODES), variable=self.mode_var).pack(side="left")
        ctk.CTkLabel(c, text="反向 WS: 本程序监听端口, NapCat 主动连接 (NapCat 端新建“WebSocket 客户端”)", font=F(11),
                     text_color="gray").pack(anchor="w", padx=16)
        self.field(c, "reverse_ws_host", "反向WS 监听地址", width=160)
        self.field(c, "reverse_ws_port", "反向WS 端口", width=100)
        ctk.CTkLabel(c, text="正向 WS: 本程序连接 NapCat 的“WebSocket 服务端”, 断线自动重连", font=F(11),
                     text_color="gray").pack(anchor="w", padx=16, pady=(8, 0))
        self.field(c, "forward_ws_url", "NapCat WS 地址", "ws://127.0.0.1:3001")
        ctk.CTkLabel(c, text="HTTP 上报: NapCat “HTTP 客户端”把消息 POST 到本程序", font=F(11),
                     text_color="gray").pack(anchor="w", padx=16, pady=(8, 0))
        self.field(c, "http_post_host", "HTTP 监听地址", width=160)
        self.field(c, "http_post_port", "HTTP 端口", width=100)
        self.field(c, "napcat_http_api", "NapCat HTTP 接口", "http://127.0.0.1:3000 (测试连接用)")
        self._secret_field(c, "http_secret", "上报签名密钥", "可选", width=260)
        self._secret_field(c, "access_token", "access_token", "与 NapCat 中 token 一致, 可留空", width=260)
        ctk.CTkLabel(c, text="", height=4).pack()

        c = self.card(p, "监听对象", "people")
        self.textfield(c, "qq_group_ids", "QQ 群号(每行一个)", "在 QQ 群资料里查看群号; 留空 = 所有群(不推荐)", 60)
        self.textfield(c, "teachers", "老师(每行一个)", "可填 QQ 号(最准确)、昵称或群名片; 名称包含即匹配, 如“王老师”", 70)
        self.textfield(c, "homework_keywords", "作业关键词(逗号或换行分隔)", "", 50)
        self.switch(c, "require_keyword", "文字消息必须包含作业关键词(老师发的图片总会保留)")
        row = ctk.CTkFrame(c, fg_color="transparent"); row.pack(fill="x", padx=16, pady=(4, 12))
        ctk.CTkLabel(row, text="相似消息去重", width=140, anchor="w").pack(side="left")
        self.w["dedup_similarity"] = tk.DoubleVar(value=self.cfg["dedup_similarity"])
        lbl = ctk.CTkLabel(row, text=f"{self.cfg['dedup_similarity']:.0%}", width=50)
        ctk.CTkSlider(row, from_=0.7, to=1.0, variable=self.w["dedup_similarity"], width=260,
                      command=lambda v: lbl.configure(text=f"{v:.0%}")).pack(side="left"); lbl.pack(side="left")

        c = self.card(p, "保存", "folder")
        row = self.field(c, "save_dir", "保存文件夹", width=330)
        self.button(row, "浏览", "folder", self.pick_dir, False, width=80).pack(side="left", padx=6)
        row = ctk.CTkFrame(c, fg_color="transparent"); row.pack(fill="x", padx=16, pady=5)
        ctk.CTkLabel(row, text="保存格式", width=140, anchor="w").pack(side="left")
        self.w["save_format"] = tk.StringVar(value=self.cfg["save_format"])
        ctk.CTkSegmentedButton(row, values=["md", "txt"], variable=self.w["save_format"]).pack(side="left")
        self.switch(c, "save_attachments", "下载并保存老师发的原图/文件/视频/语音")
        self._napcat_card(p)
        self.guide(p, "NapCat 配置向导", NAPCAT_GUIDE, [("NapCat 下载", NAPCAT_RELEASES), ("NapCat 文档", NAPCAT_DOCS)])
        self.save_btn(p)

    # ================= 企业微信 =================
    def _page_wecom(self, p):
        self.header(p, "企业微信推送", "通过企业微信群“消息推送”(群机器人) Webhook 发送, 无需打开微信")
        c = self.card(p, "机器人", "link")
        self.textfield(c, "wecom_webhooks", "Webhook 地址(每行一个, 可写“名称|地址”)",
                       "例: 家庭群|https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx  (保存时自动校验格式)", 80)
        self.webhook_hint = ctk.CTkLabel(c, text="", font=F(11), text_color="#EF4444", anchor="w")
        self.webhook_hint.pack(fill="x", padx=16)
        row = ctk.CTkFrame(c, fg_color="transparent"); row.pack(fill="x", padx=16, pady=5)
        ctk.CTkLabel(row, text="消息格式", width=140, anchor="w").pack(side="left")
        self.w["push_format"] = tk.StringVar(value=self.cfg["push_format"])
        ctk.CTkSegmentedButton(row, values=["markdown", "text"], variable=self.w["push_format"]).pack(side="left")
        self.switch(c, "push_images", "同时推送老师发的附件(图片/文件/视频/语音; 图片≤2MB, 文件/视频≤20MB)")
        row = ctk.CTkFrame(c, fg_color="transparent"); row.pack(fill="x", padx=16, pady=(5, 12))
        ctk.CTkLabel(row, text="推送模式", width=140, anchor="w").pack(side="left")
        self.send_mode_var = tk.StringVar(value="推送前确认" if self.cfg["send_mode"] == "preview" else "全自动推送")
        ctk.CTkSegmentedButton(row, values=["推送前确认", "全自动推送"], variable=self.send_mode_var).pack(side="left")
        c = self.card(p, "消息模板", "edit")
        self.field(c, "child_name", "孩子名字", "如: 小明")
        self.field(c, "greeting", "问候语")
        self.textfield(c, "message_template", "模板", "可用变量: {greeting} {child} {content} {date} {subject}", 100)
        bar = ctk.CTkFrame(c, fg_color="transparent"); bar.pack(fill="x", padx=16, pady=(0, 12))
        self.button(bar, "预览效果", "eye", self.preview_template, False, width=100).pack(side="left")
        self.button(bar, "恢复默认", "refresh", lambda: self._set_text("message_template", DEFAULT_TEMPLATE), False,
                    width=100).pack(side="left", padx=6)
        c = self.card(p, "每日汇总", "calendar")
        self.switch(c, "daily_summary", "每天定时把当天所有作业汇总推送到企业微信")
        self.field(c, "daily_summary_time", "推送时间(HH:MM)", width=100)
        ctk.CTkLabel(c, text="", height=4).pack()
        self._remind_card(p)
        self.guide(p, "如何获取 Webhook", WECOM_GUIDE, [("企业微信官方说明", WECOM_DOC)])
        bar = ctk.CTkFrame(p, fg_color="transparent"); bar.pack(fill="x")
        self.button(bar, "测试推送", "send", self.test_push, False, height=38).pack(side="left", pady=12)
        self.save_btn(bar)

    # ================= AI =================
    def _page_ai(self, p):
        self.header(p, "AI 设置", "支持任何 OpenAI 兼容接口, 推荐 DeepSeek / 通义千问 (中文效果好、便宜)")
        c = self.card(p, "接口", "robot")
        row = ctk.CTkFrame(c, fg_color="transparent"); row.pack(fill="x", padx=16, pady=5)
        ctk.CTkLabel(row, text="快速选择", width=140, anchor="w").pack(side="left")
        ctk.CTkOptionMenu(row, values=list(API_PRESETS), command=self.apply_preset).pack(side="left")
        self.field(c, "api_base_url", "base_url")
        self._secret_field(c, "api_key", "API Key")
        self.field(c, "model", "模型")
        self.field(c, "max_retries", "失败重试次数", width=80)
        ctk.CTkLabel(c, text="未填写 Key 时使用内置规则整理(效果较弱)。", font=F(11), text_color="gray").pack(anchor="w", padx=16, pady=(0, 10))
        c = self.card(p, "提示词", "edit")
        self.textfield(c, "llm_prompt", "系统提示词(需返回 date/subject/items/deadline/notes 的 JSON)", "", 120)
        self.button(c, "恢复默认提示词", "refresh", lambda: self._set_text("llm_prompt", DEFAULT_PROMPT), False,
                    width=140).pack(anchor="w", padx=16, pady=(0, 12))
        c = self.card(p, "测试 AI", "test")
        self.ai_in = ctk.CTkTextbox(c, height=90, font=F(13)); self.ai_in.pack(fill="x", padx=16, pady=4)
        self.ai_in.insert("1.0", "各位家长好，今天作业：\n1.语文：抄写第5课生字两遍，背诵古诗《山行》\n2.数学：口算本第12页\n请家长检查签字，明早交给组长。")
        self.button(c, "测试 AI 整理", "robot", self.test_ai, width=140).pack(anchor="w", padx=16, pady=4)
        self.ai_out = ctk.CTkTextbox(c, height=170, font=F(13)); self.ai_out.pack(fill="x", padx=16, pady=(4, 14))
        self.save_btn(p)

    # ================= 日志 / 关于 =================
    def _page_log(self, p):
        top = ctk.CTkFrame(p, fg_color="transparent"); top.pack(fill="x")
        self.header(top, "日志")
        self.button(top, "清空", "cancel", lambda: self.logbox.delete("1.0", "end"), False, width=80).place(relx=1, y=0, anchor="ne")
        self.button(top, "日志文件", "folder", lambda: open_path(self.log_file), False, width=100).place(relx=1, x=-90, y=0, anchor="ne")
        self.logbox = ctk.CTkTextbox(p, font=ctk.CTkFont(family="Consolas", size=12)); self.logbox.pack(fill="both", expand=True, pady=8)

    def _page_about(self, p):
        self.header(p, "关于 / 系统")
        c = self.card(p, "后台运行", "settings")
        self.w["autostart"] = tk.BooleanVar(value=system.get_autostart() or self.cfg.get("autostart"))
        ctk.CTkSwitch(c, text="开机自动启动", variable=self.w["autostart"], font=F(13)).pack(anchor="w", padx=16, pady=5)
        self.switch(c, "start_minimized", "启动时最小化到托盘(后台运行)")
        self.switch(c, "auto_listen", "启动后自动开始监听")
        self.switch(c, "minimize_to_tray", "关闭窗口时最小化到托盘(不退出)")
        self.switch(c, "notify", "新作业/推送失败/连接断开时弹出 Windows 通知")
        self.button(c, "测试通知", "bell", lambda: self.notify("作业小助手", "这是一条测试通知"), False,
                    width=110).pack(anchor="w", padx=16, pady=(4, 12))
        c = self.card(p, "配置备份", "save")
        bar = ctk.CTkFrame(c, fg_color="transparent"); bar.pack(fill="x", padx=16, pady=(4, 12))
        self.button(bar, "导出配置", "download", self.export_cfg, False, width=110).pack(side="left")
        self.button(bar, "导入配置", "folder", self.import_cfg, False, width=110).pack(side="left", padx=8)
        self.button(bar, "打开首次向导", "help", self.open_wizard, False, width=130).pack(side="left")
        ctk.CTkLabel(c, text="导出时可选择是否包含 API Key / token / Webhook 密钥。不含密钥的文件适合分享给别人对照设置。",
                     font=F(11), text_color="gray", wraplength=700, justify="left").pack(anchor="w", padx=16, pady=(0, 12))
        self.save_btn(p)
        c = self.card(p, f"{APP_NAME} v{__version__}", "info")
        ctk.CTkLabel(c, justify="left", font=F(13), anchor="w", text=(
            "通过 NapCat 在后台接收 QQ 班级群消息, AI 整理老师发布的作业, 按日期存档, 并推送到企业微信群。\n\n"
            "v3.3: NapCat 管理与看门狗 / 今日清单与月历 / 晚间与早晨提醒 / 周报 / 安装包\n"
            "v3.2: 首次配置向导 / 连接健康与离线横幅 / 失败一键重试 / 科目色标与附件芯片 / 密钥脱敏与配置导入导出\n"
            "v3.1: 富媒体推送(图片/文件/视频/语音) / 速率限制\n"
            "v3.0: NapCat(OneBot v11) / 企业微信机器人 / 后台运行 / 图标字体界面\n\n"
            f"数据目录: {self.data_dir}\n配置文件: {os.path.join(self.base, 'config.json')}")).pack(anchor="w", padx=16, pady=(0, 14))

    # ================= 设置读写 =================
    def _set_text(self, key, text):
        self.w[key].delete("1.0", "end"); self.w[key].insert("1.0", text)

    def collect(self):
        c = self.cfg
        for k, v in self.w.items():
            val = v.get("1.0", "end").strip() if isinstance(v, ctk.CTkTextbox) else v.get()
            if k in ("teachers", "homework_keywords"): val = split_names(val)
            elif k == "qq_group_ids": val = parse_group_ids(val)
            elif k == "wecom_webhooks": val = split_lines(val)
            elif k in ("reverse_ws_port", "http_post_port", "max_retries"):
                try: val = int(val)
                except ValueError: val = c[k]
            elif k == "dedup_similarity": val = round(float(val), 2)
            elif isinstance(val, str): val = val.strip()
            if k in SECRET_KEYS and isinstance(val, str) and val.startswith("•"):
                val = getattr(self, "_secret_real", {}).get(k, self.cfg.get(k, ""))
            c[k] = val
        c["onebot_mode"] = MODES.get(self.mode_var.get(), "reverse_ws")
        c["send_mode"] = "preview" if self.send_mode_var.get() == "推送前确认" else "auto"
        for k, d in (("daily_summary_time", "20:30"), ("evening_reminder_time", "20:00"),
                     ("morning_reminder_time", "07:00"), ("weekly_report_time", "20:30")):
            try: time.strptime(str(c.get(k, d)), "%H:%M")
            except ValueError: c[k] = d
        return c

    CONN_KEYS = ("onebot_mode", "reverse_ws_host", "reverse_ws_port", "forward_ws_url", "http_post_host",
                 "http_post_port", "access_token", "http_secret", "napcat_http_api")

    def save(self):
        before = {k: self.cfg.get(k) for k in self.CONN_KEYS}
        self.collect()
        ok, errs = validate_webhooks(self.cfg.get("wecom_webhooks") or [])
        if errs:
            if hasattr(self, "webhook_hint"):
                self.webhook_hint.configure(text=" / ".join(errs[:3]))
            if not messagebox.askyesno("Webhook 格式告警", "以下地址可能不正确:\n" + "\n".join(errs) + "\n\n仍要保存?"):
                return
        elif hasattr(self, "webhook_hint"):
            self.webhook_hint.configure(text="")
        # 密钥字段: 若 UI 仍是掩码且未改, 保留原值
        for k in SECRET_KEYS:
            if k in self.w and k in getattr(self, "_secret_real", {}):
                shown = self.w[k].get() if not isinstance(self.w[k], ctk.CTkTextbox) else ""
                if shown == mask_secret(self._secret_real.get(k, "")) or (shown.startswith("•") and shown.endswith((self._secret_real.get(k) or "")[-4:] or "____")):
                    self.cfg[k] = self._secret_real.get(k, self.cfg.get(k, ""))
                else:
                    self._secret_real[k] = self.cfg.get(k, "")
        self.cfg["setup_done"] = True
        save_config(self.cfg)
        try: system.set_autostart(self.cfg["autostart"])
        except Exception as e: self.log(f"设置开机启动失败: {e}")
        if self.engine:
            self.engine.seen.threshold = self.cfg["dedup_similarity"]
            if self.engine.running and before != {k: self.cfg.get(k) for k in self.CONN_KEYS}:
                self.log("连接设置已变更, 重新启动监听")
                eng = self.engine
                threading.Thread(target=lambda: (eng.stop(), self.q.put(("call", self.start))), daemon=True).start()
        self.log("设置已保存"); self.toast_ui("设置已保存")

    def toast_ui(self, text, color="#22C55E"):
        lbl = ctk.CTkLabel(self, text=f"  {text}  ", fg_color=color, text_color="white", corner_radius=8, font=F(13, True))
        lbl.place(relx=0.5, rely=0.96, anchor="s"); self.after(2200, lbl.destroy)

    def _save_dir(self):
        d = resolve_dir(self.cfg["save_dir"]); os.makedirs(d, exist_ok=True); return d

    def pick_dir(self):
        d = filedialog.askdirectory()
        if d: self.w["save_dir"].set(d)

    def apply_preset(self, name):
        url, model = API_PRESETS[name]; self.w["api_base_url"].set(url); self.w["model"].set(model)

    def conn_address(self):
        c = self.cfg
        return {"reverse_ws": f"ws://{c['reverse_ws_host']}:{c['reverse_ws_port']}/onebot/v11/ws",
                "forward_ws": c["forward_ws_url"],
                "http_post": f"http://{c['http_post_host']}:{c['http_post_port']}/"}[c["onebot_mode"]]

    def copy_addr(self):
        self.collect(); self.clipboard_clear(); self.clipboard_append(self.conn_address())
        self.toast_ui("已复制: " + self.conn_address())


    # ================= v3.2 helpers =================
    def _secret_field(self, parent, key, label, hint="", width=420):
        """密钥输入: 默认显示末 4 位掩码, 聚焦时清空以便重填."""
        if not hasattr(self, "_secret_real"):
            self._secret_real = {}
        real = str(self.cfg.get(key, "") or "")
        self._secret_real[key] = real
        row = ctk.CTkFrame(parent, fg_color="transparent"); row.pack(fill="x", padx=16, pady=5)
        ctk.CTkLabel(row, text=label, font=F(13), width=140, anchor="w").pack(side="left")
        var = tk.StringVar(value=mask_secret(real) if real else "")
        entry = ctk.CTkEntry(row, textvariable=var, width=width, show="", font=F(13), placeholder_text=hint or "未设置")
        entry.pack(side="left")
        def on_focus(_e=None, k=key, v=var, e=entry):
            cur = v.get()
            if cur.startswith("•") or cur == mask_secret(self._secret_real.get(k, "")):
                v.set(""); e.configure(show="•")
        def on_leave(_e=None, k=key, v=var, e=entry):
            typed = v.get()
            if not typed:
                real = self._secret_real.get(k, "")
                v.set(mask_secret(real) if real else ""); e.configure(show="")
            else:
                self._secret_real[k] = typed; e.configure(show="•")
        entry.bind("<FocusIn>", on_focus)
        entry.bind("<FocusOut>", on_leave)
        self.w[key] = var
        tip = ctk.CTkLabel(row, text=f"已保存 ···{real[-4:]}" if real else "未设置", font=F(11), text_color="gray")
        tip.pack(side="left", padx=8)
        return row

    def open_wizard(self):
        d = getattr(self, "_wizard", None)
        if d and d.winfo_exists():
            d.lift(); return
        self._wizard = SetupWizard(self)

    def copy_text(self, text):
        text = text or ""
        self.clipboard_clear(); self.clipboard_append(text)
        self.toast_ui("已复制到剪贴板")

    def copy_selected(self):
        if self.h_sel:
            self.copy_text(self.h_text.get("1.0", "end").strip())

    def retry_record(self, hid):
        rec = self.history.get(hid)
        if not rec:
            return
        self.log(f"一键重试推送 #{hid} ({rec['result'].get('subject')})")
        self.notify("作业小助手", f"正在重试推送: {rec['result'].get('subject')}")
        self.send_record(hid, rec.get("message"), rec.get("attachments"))

    def retry_selected(self):
        if self.h_sel:
            self.retry_record(self.h_sel)

    def reconnect(self):
        self.log("手动重新连接 NapCat…")
        self.toast_ui("正在重新连接…", "#F59E0B")
        def run():
            if self.engine and self.engine.running:
                eng = self.engine
                eng.stop()
            self.q.put(("call", lambda: self.start(quiet=True)))
        threading.Thread(target=run, daemon=True).start()

    def export_cfg(self):
        include = messagebox.askyesno("导出配置", "是否包含 API Key / token / Webhook 密钥?\n\n选「否」导出脱敏配置(可分享)。")
        data = export_config(self.collect(), include_secrets=bool(include))
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="homeworkbot-config.json",
                                            filetypes=[("JSON", "*.json")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.log(f"已导出配置到 {path} (secrets={'yes' if include else 'no'})")
        self.toast_ui("配置已导出")

    def import_cfg(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.cfg = import_config(raw, merge=True)
            save_config(self.cfg)
            self._reload_settings_widgets()
            self.log(f"已导入配置: {path}")
            self.toast_ui("配置已导入, 请检查各页设置")
            messagebox.showinfo("导入成功", "配置已合并导入。密钥若导出时被脱敏则保留原值。请到各设置页确认后点保存。")
        except Exception as e:
            messagebox.showerror("导入失败", str(e))

    def _reload_settings_widgets(self):
        """向导/导入后把 cfg 写回已有 StringVar/Textbox."""
        for k, w in list(self.w.items()):
            if k not in self.cfg:
                continue
            val = self.cfg[k]
            if isinstance(w, ctk.CTkTextbox):
                w.delete("1.0", "end")
                w.insert("1.0", "\n".join(map(str, val)) if isinstance(val, list) else str(val or ""))
            else:
                try:
                    if k in SECRET_KEYS:
                        self._secret_real[k] = str(val or "")
                        w.set(mask_secret(val) if val else "")
                    elif isinstance(val, list):
                        w.set("\n".join(map(str, val)))
                    else:
                        w.set(val)
                except Exception:
                    pass
        if hasattr(self, "mode_var"):
            self.mode_var.set(MODE_NAMES.get(self.cfg.get("onebot_mode"), list(MODES)[0]))
        if hasattr(self, "send_mode_var"):
            self.send_mode_var.set("推送前确认" if self.cfg.get("send_mode") == "preview" else "全自动推送")

    # ================= 运行控制 =================
    def make_engine(self):
        from .worker import Engine
        from .onebot import make_connector
        return Engine(self.cfg, self.history, log=self.log, checklist=self.checklist, seen_path=os.path.join(self.data_dir, "seen.json"),
                      on_event=lambda k, d: self.q.put(("event", k, d)),
                      connector_factory=lambda cb: make_connector(
                          self.cfg, cb, lambda s, d="": self.q.put(("event", "conn", (s, d))), self.log))

    def toggle(self):
        self.stop() if (self.engine and self.engine.running) else self.start()

    def start(self, quiet=False):
        self.collect()
        if not quiet: save_config(self.cfg)
        if not self.cfg["teachers"]:
            if not quiet:
                self.show("qq"); messagebox.showwarning("提示", "请先填写老师(QQ号/昵称/群名片)")
            else:
                self.log("尚未配置老师, 暂不开始监听")
            return
        if self.engine and self.engine.running: return
        self.engine = self.make_engine(); self.engine.start()
        self.after(300, self.refresh)

    def stop(self):
        if self.engine:
            eng = self.engine
            threading.Thread(target=eng.stop, daemon=True).start()
        self.after(600, self.refresh)

    def push_summary(self):
        today = dt.date.today().isoformat()
        text = render_daily_summary(self.history.by_date(today), today, self.collect())
        if messagebox.askyesno("推送今日汇总", text[:800] + "\n\n确认推送到企业微信?"):
            eng = self.engine or self.make_engine()
            self.bg(lambda: (eng.send_text(text), self.log("今日汇总已推送")))

    def send_record(self, hid, text=None, attachments=None):
        if not parse_webhooks(self.cfg.get("wecom_webhooks", [])):
            messagebox.showwarning("提示", "请先在[企业微信推送]里填写 Webhook 地址"); self.show("wecom"); return
        eng = self.engine or self.make_engine()
        self.bg(lambda: eng.send_record(hid, text, attachments))

    def open_preview(self, hid):
        d = self.dialogs.get(hid)
        if d and d.winfo_exists(): d.lift(); return
        self.dialogs[hid] = PreviewDialog(self, hid)

    def bg(self, fn):
        def run():
            try: fn()
            except Exception as e: self.log(f"出错: {e}"); self.q.put(("toast", f"出错: {e}"))
            self.q.put(("event", "status", None))
        threading.Thread(target=run, daemon=True).start()

    # ================= 测试按钮 =================
    def test_conn(self):
        self.collect()
        def run():
            from .onebot import test_connection
            if not (self.engine and self.engine.running):
                self.q.put(("call", self.start))
                for _ in range(30):
                    time.sleep(0.2)
                    if self.engine and self.engine.conn: break
            eng = self.engine
            if not eng or not eng.conn:
                self.q.put(("msg", ("测试连接", "监听未启动, 请先填写老师并开始监听"))); return
            for _ in range(25):                     # 反向 WS 给 NapCat 几秒钟连上
                if eng.conn.connected or eng.conn.mode == "http_post": break
                time.sleep(0.2)
            ok, info = test_connection(eng.conn)
            self.log(("[成功] " if ok else "[失败] ") + info)
            self.q.put(("msg", ("测试连接", info)))
        threading.Thread(target=run, daemon=True).start()

    def test_push(self):
        c = self.collect()
        hooks = parse_webhooks(c["wecom_webhooks"])
        if not hooks: messagebox.showwarning("提示", "请先填写 Webhook 地址"); return
        if not messagebox.askyesno("测试推送", f"将向 {len(hooks)} 个企业微信机器人各发送一条测试消息, 继续?"): return
        from .wecom import WeComSender
        text = apply_template(f"【作业小助手】测试消息 {dt.datetime.now():%H:%M:%S}, 收到说明配置成功, 请忽略。", c)
        def run():
            WeComSender(hooks, c["push_format"], False, log=self.log).send(text)
            self.q.put(("msg", ("测试推送", f"已成功推送到 {len(hooks)} 个机器人")))
        self.bg(run)

    def test_ai(self):
        c = self.collect(); text = self.ai_in.get("1.0", "end").strip()
        self.ai_out.delete("1.0", "end"); self.ai_out.insert("1.0", "整理中…")
        def run():
            t0 = time.time()
            r = format_homework(text, "测试老师", c, log=self.log)
            out = compose_message(r, c) + f"\n\n(耗时 {time.time()-t0:.1f}s, {'AI' if c.get('api_key') else '规则'})"
            self.q.put(("ai", out))
        self.bg(run)

    def preview_template(self):
        c = self.collect()
        sample = {"date": dt.date.today().isoformat(), "subject": "语文、数学", "items": ["抄写第5课生字两遍", "口算本第12页"],
                  "deadline": "明早", "notes": ["家长签字"], "sender": "王老师"}
        messagebox.showinfo("模板预览", compose_message(sample, c))

    # ================= 事件循环 =================
    def log(self, s):
        line = time.strftime("[%m-%d %H:%M:%S] ") + str(s)
        self.q.put(("log", line))
        try:
            with open(self.log_file, "a", encoding="utf-8") as f: f.write(line + "\n")
        except OSError:
            pass

    def notify(self, title, msg):
        if self.cfg.get("notify", True):
            system.toast(title, msg, self.icon_ico)

    def pump(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "log":
                    self.logbox.insert("end", item[1] + "\n"); self.logbox.see("end")
                elif kind == "ai":
                    self.ai_out.delete("1.0", "end"); self.ai_out.insert("1.0", item[1])
                elif kind == "msg":
                    messagebox.showinfo(*item[1])
                elif kind == "toast":
                    self.toast_ui(item[1], "#EF4444")
                elif kind == "call":
                    item[1]()
                elif kind == "event":
                    self.on_event(item[1], item[2])
        except queue.Empty:
            pass
        self.after(200, self.pump)

    def on_event(self, kind, data):
        if kind == "new":
            self.after(100, self.refresh_todo)
            rec = self.history.get(data)
            self.notify(f"新作业: {rec['result']['subject']}", "\n".join(rec["result"]["items"][:3]) or "老师发了图片作业")
            if self.cfg["send_mode"] == "preview":
                self.show_window(); self.open_preview(data)
        elif kind == "remind":
            self.notify(*data); self.toast_ui(data[0], "#F59E0B"); self.refresh_todo()
        elif kind == "sent":
            self.toast_ui("已推送到企业微信")
        elif kind == "error":
            self.notify("作业小助手 - 出错了", str(data)); self.log(f"[警告] {data}")
            self.toast_ui(str(data)[:40], "#EF4444")
        elif kind == "conn":
            state, detail = data
            prev = getattr(self, "_conn_state", None)
            self._conn_state = state
            if prev == "connected" and state != "connected" and state != "stopped":
                self.notify("NapCat 连接断开", detail or "正在等待重新连接")
            return self.update_conn()
        self.refresh()

    def update_conn(self):
        eng = self.engine
        state = eng.conn.state if (eng and eng.running and eng.conn) else "stopped"
        detail = eng.conn.detail if (eng and eng.conn) else ""
        txt, color = CONN_TXT.get(state, (state, "gray"))
        self.side_dot.configure(text_color=color); self.side_status.configure(text=" " + txt)
        self.qq_dot.configure(text_color=color); self.qq_state.configure(text=" " + txt)
        le = eng.last_event if eng else None
        last_s = le.strftime("%Y-%m-%d %H:%M:%S") if le else "尚无消息"
        recv = eng.received if eng else 0
        self.qq_detail.configure(
            text=(detail + "\n" if detail else "")
            + f"最近消息: {last_s}  ·  本会话收到事件 {recv} 条\n"
            + "NapCat 需要配置的地址: " + self.conn_address())
        self.stat["conn"].configure(text=txt, text_color=color)
        self.conn_lbl.configure(text=detail or ("监听中" if state == "connected" else ""))
        # 离线横幅
        if hasattr(self, "offline_banner"):
            show = bool(eng and eng.running and state in ("error", "waiting", "connecting"))
            if show:
                msg = {"error": "NapCat 连接异常", "waiting": "等待 NapCat 连入",
                       "connecting": "正在连接 NapCat"}.get(state, "连接未就绪")
                self.offline_lbl.configure(text=f"  {msg} — {detail or '可点右侧重新连接'}")
                if not self.offline_banner.winfo_manager():
                    # 插在统计卡片之前
                    self.offline_banner.pack(fill="x", pady=(0, 6), before=self.stat["conn"].master)
            else:
                self.offline_banner.pack_forget()

    def tick(self):
        running = bool(self.engine and self.engine.running)
        self.run_btn.configure(text=" 停止监听" if running else " 开始监听", image=I("stop" if running else "play", 18, True),
                               fg_color="#EF4444" if running else ACCENT)
        self.update_conn(); self.update_napcat()
        le = self.engine.last_event if self.engine else None
        if le:
            ago = (dt.datetime.now() - le).total_seconds()
            if ago < 60: last_txt = f"{int(ago)}秒前"
            elif ago < 3600: last_txt = f"{int(ago//60)}分钟前"
            else: last_txt = le.strftime("%H:%M")
        else:
            last_txt = "-"
        self.stat["last"].configure(text=last_txt)
        self.err_lbl.configure(text=f"最近错误: {self.engine.last_error}" if self.engine and self.engine.last_error else "")
        st = self.engine.conn.state if (running and self.engine.conn) else "stopped"
        self.tray.set_title(f"作业小助手 - {CONN_TXT.get(st, ('',))[0]}")
        self.after(1000, self.tick)

    def refresh(self):
        s = self.history.stats(dt.date.today().isoformat())
        self.stat["today"].configure(text=str(s["today"])); self.stat["pending"].configure(text=str(s["pending"]))
        self.stat["total"].configure(text=str(s["total"]))
        for c in self.today_box.winfo_children(): c.destroy()
        recs = list(reversed(self.history.by_date(dt.date.today().isoformat())))
        if not recs:
            ctk.CTkLabel(self.today_box, text="今天还没有收到作业", font=F(14), text_color="gray").pack(pady=40)
        for rec in recs: self.hw_card(self.today_box, rec)
        self.refresh_history()

    # ================= 窗口/托盘 =================
    def show_window(self):
        self.deiconify(); self.lift(); self.focus_force()

    def on_close(self):
        if self.cfg.get("minimize_to_tray", True) and self.tray.icon:
            self.withdraw(); self.notify("作业小助手", "已最小化到托盘, 后台继续运行")
        else:
            self.quit_app()

    def quit_app(self):
        if self.engine: self.engine.stop()
        try: self.napcat.stop()
        except Exception: pass
        self.tray.stop(); self.destroy()


    # ================= 截图自检 (--shots DIR) =================
    def run_shots(self, out_dir, prefix="v33_"):
        """依次切换页面并用 ImageGrab 截取本窗口(不操作鼠标键盘), 完成后退出."""
        os.makedirs(out_dir, exist_ok=True)
        self.deiconify()
        self.geometry("1100x740")
        plan = [("dash", None, "dash"), ("todo", None, "todo"), ("qq", "nc_state", "napcat"),
                ("wecom", "_remind_anchor", "remind"), ("about", None, "about")]
        def grab(name):
            """PrintWindow 只截本程序窗口内容, 不截屏幕上其他窗口."""
            self.update()
            path = os.path.join(out_dir, f"{prefix}{name}.png")
            import ctypes
            from ctypes import wintypes
            from PIL import Image
            u, g = ctypes.windll.user32, ctypes.windll.gdi32
            H = ctypes.c_void_p
            u.GetWindowDC.restype = H; u.GetAncestor.restype = H; g.CreateCompatibleDC.restype = H
            g.CreateCompatibleBitmap.restype = H; g.SelectObject.restype = H
            g.CreateCompatibleDC.argtypes = [H]; g.CreateCompatibleBitmap.argtypes = [H, ctypes.c_int, ctypes.c_int]
            g.SelectObject.argtypes = [H, H]; u.PrintWindow.argtypes = [H, H, ctypes.c_uint]
            g.GetDIBits.argtypes = [H, H, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
            u.ReleaseDC.argtypes = [H, H]; g.DeleteObject.argtypes = [H]; g.DeleteDC.argtypes = [H]
            u.GetWindowRect.argtypes = [H, ctypes.c_void_p]; u.GetWindowDC.argtypes = [H]
            hwnd = H(int(self.wm_frame(), 16))
            r = wintypes.RECT(); u.GetWindowRect(hwnd, ctypes.byref(r))
            w, h = r.right - r.left, r.bottom - r.top
            hdc = u.GetWindowDC(hwnd); mdc = g.CreateCompatibleDC(hdc)
            bmp = g.CreateCompatibleBitmap(hdc, w, h); old = g.SelectObject(mdc, bmp)
            u.PrintWindow(hwnd, mdc, 2); g.SelectObject(mdc, old)
            class BIH(ctypes.Structure):
                _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                            ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                            ("biSizeImage", ctypes.c_uint32), ("a", ctypes.c_int32), ("b", ctypes.c_int32),
                            ("c", ctypes.c_uint32), ("d", ctypes.c_uint32)]
            bih = BIH(ctypes.sizeof(BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
            buf = ctypes.create_string_buffer(w * h * 4)
            g.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bih), 0)
            Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB").save(path)
            g.DeleteObject(bmp); g.DeleteDC(mdc); u.ReleaseDC(hwnd, hdc)
        def step(i=0):
            if i >= len(plan):
                self.after(300, self.quit_app); return
            key, anchor, name = plan[i]
            self.show(key); self.update()
            w = getattr(self, anchor, None) if anchor else None
            if w is not None:
                page = self.pages[key]
                try:
                    card = w
                    while card.master is not None and card.master.master is not page and card.master is not page:
                        card = card.master
                    inner = card.master
                    page._parent_canvas.yview_moveto(max(0.0, card.winfo_y() / max(1, inner.winfo_height())))
                except Exception as e:
                    self.log(f"shots scroll: {e}")
            self.after(900, lambda: (grab(name), step(i + 1)))
        self.after(1500, step)


def main():
    minimized = "--minimized" in sys.argv
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
    app = App(minimized and "--shots" not in sys.argv)
    if "--shots" in sys.argv:
        i = sys.argv.index("--shots")
        app.run_shots(sys.argv[i + 1] if len(sys.argv) > i + 1 else os.path.join(app.base, "e2e_shots"))
    app.mainloop()
