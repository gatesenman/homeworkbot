"""首次运行 3 步向导: NapCat 连接 → QQ 群/老师 → 企业微信 Webhook."""
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk

from .config import (save_config, split_names, parse_group_ids, split_lines,
                     validate_webhook_url, parse_webhooks)
from .icons import icon

FONT = "Microsoft YaHei UI"
ACCENT = "#3B82F6"

def F(size=13, bold=False):
    return ctk.CTkFont(family=FONT, size=size, weight="bold" if bold else "normal")

def I(name, size=18, white=False):
    return icon(name, size, "#FFFFFF", "#FFFFFF") if white else icon(name, size)


class SetupWizard(ctk.CTkToplevel):
    """3 步首次配置; 完成后写回 app.cfg 并可选开始监听."""

    STEPS = ("NapCat 连接", "群与老师", "企业微信")

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.cfg = dict(app.cfg)
        self.step = 0
        self.title(f"欢迎使用 · 首次配置")
        self.geometry("640x520")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._skip)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(16, 8))
        ctk.CTkLabel(top, text="欢迎使用作业小助手", font=F(22, True)).pack(anchor="w")
        ctk.CTkLabel(top, text="三步完成配置, 之后即可后台自动转发班级作业",
                     font=F(12), text_color="gray").pack(anchor="w")

        self.step_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.step_bar.pack(fill="x", padx=20, pady=4)
        self.step_labels = []
        for i, name in enumerate(self.STEPS):
            lbl = ctk.CTkLabel(self.step_bar, text=f" {i+1}. {name} ", font=F(12, True),
                               corner_radius=8, fg_color=("gray80", "gray30"))
            lbl.pack(side="left", padx=4)
            self.step_labels.append(lbl)

        self.body = ctk.CTkFrame(self, corner_radius=12)
        self.body.pack(fill="both", expand=True, padx=20, pady=8)

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=20, pady=(0, 16))
        ctk.CTkButton(bar, text=" 跳过向导", image=I("cancel"), fg_color="transparent",
                      border_width=1, text_color=("gray10", "gray90"), width=110,
                      command=self._skip).pack(side="left")
        self.next_btn = ctk.CTkButton(bar, text="下一步", image=I("play", 18, True),
                                      font=F(13, True), width=120, command=self._next)
        self.next_btn.pack(side="right")
        self.back_btn = ctk.CTkButton(bar, text="上一步", image=I("refresh"), fg_color="transparent",
                                      border_width=1, text_color=("gray10", "gray90"), width=100,
                                      command=self._back)
        self.back_btn.pack(side="right", padx=8)

        self.vars = {}
        self._render()

    def _clear_body(self):
        for w in self.body.winfo_children():
            w.destroy()

    def _render(self):
        self._clear_body()
        for i, lbl in enumerate(self.step_labels):
            on = i == self.step
            lbl.configure(fg_color=ACCENT if on else ("gray80", "gray30"),
                          text_color="white" if on else ("gray10", "gray90"))
        self.back_btn.configure(state="normal" if self.step > 0 else "disabled")
        self.next_btn.configure(text="完成并开始" if self.step == 2 else "下一步")
        [self._step0, self._step1, self._step2][self.step]()

    def _row(self, label, key, hint="", show="", width=360, default=None):
        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(row, text=label, font=F(13), width=130, anchor="w").pack(side="left")
        val = default if default is not None else str(self.cfg.get(key, ""))
        var = tk.StringVar(value=val)
        ctk.CTkEntry(row, textvariable=var, width=width, show=show, font=F(13),
                     placeholder_text=hint).pack(side="left")
        self.vars[key] = var
        return row

    def _text(self, label, key, hint="", height=70, default=None):
        ctk.CTkLabel(self.body, text=label, font=F(13, True)).pack(anchor="w", padx=16, pady=(10, 0))
        if hint:
            ctk.CTkLabel(self.body, text=hint, font=F(11), text_color="gray",
                         justify="left", wraplength=560).pack(anchor="w", padx=16)
        t = ctk.CTkTextbox(self.body, height=height, font=F(13))
        t.pack(fill="x", padx=16, pady=4)
        v = default if default is not None else self.cfg.get(key, "")
        if isinstance(v, list):
            v = "\n".join(map(str, v))
        t.insert("1.0", v or "")
        self.vars[key] = t
        return t

    def _step0(self):
        ctk.CTkLabel(self.body, text="连接 NapCat (OneBot)", image=I("plug", 22),
                     compound="left", font=F(16, True)).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(self.body, text="推荐用反向 WebSocket: 本程序监听端口, NapCat 主动连过来。"
                     "请先安装并登录 NapCat 小号。",
                     font=F(12), text_color="gray", wraplength=560, justify="left").pack(anchor="w", padx=16)
        modes = {"反向 WebSocket(推荐)": "reverse_ws", "正向 WebSocket": "forward_ws", "HTTP 上报": "http_post"}
        inv = {v: k for k, v in modes.items()}
        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=8)
        ctk.CTkLabel(row, text="连接方式", width=130, anchor="w", font=F(13)).pack(side="left")
        self.mode_var = tk.StringVar(value=inv.get(self.cfg.get("onebot_mode"), list(modes)[0]))
        ctk.CTkOptionMenu(row, values=list(modes), variable=self.mode_var, width=260).pack(side="left")
        self._modes = modes
        self._row("反向WS 端口", "reverse_ws_port", "8095", width=120)
        self._row("正向WS 地址", "forward_ws_url", "ws://127.0.0.1:3001", width=300)
        self._row("access_token", "access_token", "与 NapCat 一致, 可留空", show="•", width=260)
        tip = (f"NapCat 里新建「WebSocket 客户端」, URL 填:\n"
               f"ws://{self.cfg.get('reverse_ws_host','127.0.0.1')}:{self.cfg.get('reverse_ws_port',8095)}/onebot/v11/ws")
        ctk.CTkLabel(self.body, text=tip, font=F(11), text_color="#3B82F6",
                     justify="left").pack(anchor="w", padx=16, pady=8)

    def _step1(self):
        ctk.CTkLabel(self.body, text="监听哪些群、哪位老师", image=I("people", 22),
                     compound="left", font=F(16, True)).pack(anchor="w", padx=16, pady=(14, 4))
        self._text("QQ 群号(每行一个)", "qq_group_ids",
                   "在 QQ 群资料里查看群号; 可先填一个班级群", 50,
                   "\n".join(map(str, self.cfg.get("qq_group_ids") or [])))
        self._text("老师(每行一个, 必填)", "teachers",
                   "填 QQ 号最准确; 也可填昵称/群名片, 如「王老师」", 70,
                   "\n".join(self.cfg.get("teachers") or []))
        ctk.CTkLabel(self.body, text="也可用小号自己的 QQ 号做测试(发一条带「作业」的消息)。",
                     font=F(11), text_color="gray").pack(anchor="w", padx=16, pady=6)

    def _step2(self):
        ctk.CTkLabel(self.body, text="企业微信群机器人", image=I("send", 22),
                     compound="left", font=F(16, True)).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(self.body, text="群聊 ··· → 消息推送 → 添加机器人 → 复制 Webhook。"
                     "形如 https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx",
                     font=F(12), text_color="gray", wraplength=560, justify="left").pack(anchor="w", padx=16)
        self._text("Webhook 地址(每行一个, 可写 名称|地址)", "wecom_webhooks",
                   "例: 家庭群|https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx", 90,
                   "\n".join(self.cfg.get("wecom_webhooks") or []))
        self._row("孩子名字(可选)", "child_name", "如: 小明", width=200)
        ctk.CTkLabel(self.body, text="完成后可在「企业微信推送」页点测试推送(请自行确认, 本向导不会自动发消息)。",
                     font=F(11), text_color="gray").pack(anchor="w", padx=16, pady=8)

    def _read(self):
        def get(k):
            v = self.vars.get(k)
            if v is None:
                return None
            if isinstance(v, ctk.CTkTextbox):
                return v.get("1.0", "end").strip()
            return v.get()
        if self.step == 0:
            self.cfg["onebot_mode"] = self._modes.get(self.mode_var.get(), "reverse_ws")
            try:
                self.cfg["reverse_ws_port"] = int(get("reverse_ws_port") or 8095)
            except ValueError:
                self.cfg["reverse_ws_port"] = 8095
            self.cfg["forward_ws_url"] = (get("forward_ws_url") or "").strip()
            self.cfg["access_token"] = get("access_token") or ""
        elif self.step == 1:
            self.cfg["qq_group_ids"] = parse_group_ids(get("qq_group_ids") or "")
            self.cfg["teachers"] = split_names(get("teachers") or "")
        elif self.step == 2:
            self.cfg["wecom_webhooks"] = split_lines(get("wecom_webhooks") or "")
            self.cfg["child_name"] = (get("child_name") or "").strip()

    def _validate(self):
        self._read()
        if self.step == 1:
            if not self.cfg["teachers"]:
                messagebox.showwarning("提示", "请至少填写一位老师(QQ号或昵称)", parent=self)
                return False
        if self.step == 2:
            lines = self.cfg["wecom_webhooks"]
            if not lines:
                messagebox.showwarning("提示", "请填写至少一个企业微信 Webhook 地址", parent=self)
                return False
            for ln in lines:
                ok, reason = validate_webhook_url(ln)
                if not ok:
                    messagebox.showwarning("Webhook 格式有误", reason + "\n\n" + ln[:80], parent=self)
                    return False
            if not parse_webhooks(lines):
                messagebox.showwarning("提示", "未能解析出有效 Webhook", parent=self)
                return False
        return True

    def _next(self):
        if not self._validate():
            return
        if self.step < 2:
            self.step += 1
            self._render()
            return
        self.cfg["setup_done"] = True
        self.app.cfg.update(self.cfg)
        save_config(self.app.cfg)
        self.app.log("首次配置向导已完成")
        self.app._reload_settings_widgets()
        self.grab_release()
        self.destroy()
        self.app.toast_ui("配置完成, 可以开始监听了")
        self.app.show("dash")
        self.app.after(400, lambda: self.app.start(quiet=False))

    def _back(self):
        self._read()
        if self.step > 0:
            self.step -= 1
            self._render()

    def _skip(self):
        if messagebox.askyesno("跳过向导", "稍后可在设置页自行配置。确定跳过?", parent=self):
            self.app.cfg["setup_done"] = True  # 不再反复弹出
            save_config(self.app.cfg)
            self.grab_release()
            self.destroy()
