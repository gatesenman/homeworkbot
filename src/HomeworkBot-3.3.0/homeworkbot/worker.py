"""作业处理引擎: OneBot 事件 -> 过滤 -> 去重 -> 下载附件 -> AI 整理 -> 存档 -> 预览或推送企业微信."""
import datetime as dt, os, queue, tempfile, threading, time
from .parser import SeenStore, parse_event, accept, Attachment
from .formatter import format_homework, compose_message, render_daily_summary
from .storage import save_result
from .config import parse_webhooks, resolve_dir

KIND_EXT = {"image": ".jpg", "video": ".mp4", "file": ".bin", "record": ".amr"}

def _ext_from_bytes(data, kind):
    if data[:8] == b"\x89PNG\r\n\x1a\n": return ".png"
    if data[:3] == b"\xff\xd8\xff": return ".jpg"
    if data[:4] == b"GIF8": return ".gif"
    if len(data) > 8 and data[4:8] == b"ftyp": return ".mp4"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE": return ".wav"
    return KIND_EXT.get(kind, ".bin")

def download_attachments(atts, folder, session=None, log=print, timeout=60):
    if session is None:
        import requests as session
    os.makedirs(folder, exist_ok=True)
    out = []
    for i, a in enumerate(atts or (), 1):
        if isinstance(a, dict): a = Attachment.from_dict(a)
        if a.path and os.path.exists(a.path):
            a.size = a.size or os.path.getsize(a.path); out.append(a); continue
        if not a.url:
            log(f"附件无下载地址, 跳过: {a.name or a.kind}"); continue
        try:
            r = session.get(a.url, timeout=timeout)
            r.raise_for_status()
            data = r.content
            name = a.name or f"{a.kind}_{i}"
            root, ext = os.path.splitext(name)
            if not ext or ext.lower() in (".bin", ".dat", ".tmp"):
                ext = _ext_from_bytes(data, a.kind)
                name = (root or a.kind) + ext
            name = "".join(c if c.isalnum() or c in "._-()[] " else "_" for c in name)[:80]
            p = os.path.join(folder, f"{int(time.time()*1000)}_{i}_{name}")
            with open(p, "wb") as f: f.write(data)
            a.path, a.size, a.name = p, len(data), name
            out.append(a)
            log(f"已下载附件 [{a.kind}] {name} ({len(data)} bytes)")
        except Exception as e:
            log(f"下载附件失败 [{a.kind}] {a.name or a.url[:40]}: {e}")
    return out

def download_images(urls, folder, session=None, log=print, timeout=20):
    atts = [Attachment("image", u) for u in urls]
    return [a.path for a in download_attachments(atts, folder, session, log, timeout)]

class Engine:
    def __init__(self, cfg, history, log=print, sender=None, seen_path="seen.json", formatter=None,
                 on_event=None, now=None, sleep=time.sleep, downloader=None, connector_factory=None, checklist=None):
        self.cfg, self.history, self.log = cfg, history, log
        self.sender = sender or self._default_sender
        self.formatter = formatter or (lambda t, s: format_homework(t, s, cfg, log=log, sleep=sleep))
        self.downloader = downloader or (lambda atts: download_attachments(
            atts, os.path.join(tempfile.gettempdir(), "HomeworkBot_att"), log=log))
        self.on_ui = on_event or (lambda kind, data: None)
        self.now, self.sleep = now or dt.datetime.now, sleep
        self.seen = SeenStore(seen_path, threshold=cfg.get("dedup_similarity", 0.9))
        self.connector_factory = connector_factory
        self.conn, self.last_event, self.last_error, self.received = None, None, "", 0
        self._q = queue.Queue()
        self._stop = threading.Event()
        self._threads = []
        self._summary_done = ""
        self._send_lock = threading.Lock()
        self.checklist, self.reminders = checklist, None
        if checklist is not None:
            from .reminders import Reminders
            self.reminders = Reminders(cfg, checklist, self.send_text,
                                       notify=lambda t, m: self.on_ui("remind", (t, m)), log=log, now=self.now)

    def _default_sender(self, text, attachments=()):
        from .wecom import WeComSender
        hooks = parse_webhooks(self.cfg.get("wecom_webhooks", []))
        WeComSender(hooks, self.cfg.get("push_format", "markdown"), self.cfg.get("push_images", True),
                    log=self.log).send(text, attachments, retries=self.cfg.get("max_retries", 3), sleep=self.sleep)

    def send_text(self, text, attachments=()):
        with self._send_lock:
            self.sender(text, attachments)

    def send_record(self, hid, text=None, attachments=None):
        rec = self.history.get(hid)
        if text is not None and text != rec["message"]:
            self.history.update_message(hid, text)
        try:
            if attachments is None:
                atts = [a for a in rec.get("attachments") or [] if a.get("path") and os.path.exists(a["path"])]
            else:
                atts = [a if isinstance(a, dict) else a.to_dict() for a in attachments]
                atts = [a for a in atts if a.get("send", True) and a.get("path") and os.path.exists(a["path"])]
            self.send_text(text if text is not None else rec["message"], atts)
            self.history.mark(hid, "sent")
            self.on_ui("sent", hid)
            return True
        except Exception as e:
            self.history.mark(hid, "failed", str(e))
            self.last_error = f"推送失败: {e}"
            self.on_ui("error", f"作业推送到企业微信失败: {e}")
            return False

    def on_onebot_event(self, event):
        self.received += 1
        self.last_event = self.now()
        self._q.put(event)

    def handle_event(self, event):
        m = parse_event(event)
        if not accept(m, self.cfg): return None
        if self.seen.is_dup(m):
            self.log(f"重复消息已跳过: {m.text[:20]}"); return None
        self.seen.add_msg(m)
        kinds = ",".join(a.kind for a in m.attachments) or "text"
        self.log(f"[群{m.group}] 发现作业 [{m.sender}] ({kinds}): {(m.text or '[附件]')[:30]}")
        local = []
        dl_fail = 0
        if m.attachments and self.cfg.get("save_attachments", True):
            wanted = len(m.attachments)
            local = self.downloader(m.attachments)
            dl_fail = max(0, wanted - len(local))
            if dl_fail:
                self.last_error = f"有 {dl_fail} 个附件下载失败"
                self.log(self.last_error)
                self.on_ui("error", f"附件下载失败 {dl_fail} 个(文字仍会保存, 可稍后重试推送)")
        text = m.text or ("(老师发送了附件作业, 请查看)" if local else "(空消息)")
        r = self.formatter(text, m.sender)
        save_dir = resolve_dir(self.cfg["save_dir"])
        path, rel_atts = save_result(r, save_dir, self.cfg.get("save_format", "md"), m.text, local)
        for a, rel in zip(local, rel_atts):
            a.path = os.path.abspath(os.path.join(save_dir, rel))
            a.size = a.size or (os.path.getsize(a.path) if os.path.exists(a.path) else 0)
        msg = compose_message(r, self.cfg)
        hid = self.history.add(r, msg, m.sender, m.group, m.text, [a.to_dict() for a in local], path)
        if self.checklist is not None:
            try: self.checklist.add_from_result(hid, r)
            except Exception as e: self.log(f"写入清单失败: {e}")
        self.log(f"已保存: {os.path.abspath(path)}" + (f" +{len(local)}附件" if local else ""))
        self.on_ui("new", hid)
        if self.cfg.get("send_mode") == "auto":
            self.send_record(hid)
        return hid

    def _worker(self):
        while not self._stop.is_set():
            try: ev = self._q.get(timeout=1)
            except queue.Empty: continue
            try: self.handle_event(ev)
            except Exception as e:
                self.last_error = str(e)
                self.log(f"处理消息出错: {e}")
                self.on_ui("error", f"处理作业消息出错: {e}")

    def check_summary(self):
        if not self.cfg.get("daily_summary"): return False
        now = self.now(); today = now.date().isoformat()
        try: hh, mm = map(int, self.cfg.get("daily_summary_time", "20:30").split(":"))
        except ValueError: return False
        if self._summary_done == today or (now.hour, now.minute) < (hh, mm): return False
        self._summary_done = today
        text = render_daily_summary(self.history.by_date(today), today, self.cfg)
        try:
            self.send_text(text); self.log("已推送每日作业汇总"); self.on_ui("summary", text)
        except Exception as e:
            self.on_ui("error", f"每日汇总推送失败: {e}")
        return True

    def _scheduler(self):
        while not self._stop.wait(20):
            try: self.check_summary()
            except Exception as e: self.log(f"定时任务出错: {e}")
            try:
                if self.reminders: self.reminders.check()
            except Exception as e: self.log(f"定时任务出错: {e}")

    @property
    def running(self):
        return any(t.is_alive() for t in self._threads)

    def start(self):
        if self.running: return
        self._stop.clear()
        try:
            hh, mm = map(int, self.cfg.get("daily_summary_time", "20:30").split(":"))
            now = self.now()
            if (now.hour, now.minute) >= (hh, mm):
                self._summary_done = now.date().isoformat()
        except ValueError: pass
        self._threads = [threading.Thread(target=self._worker, daemon=True, name="engine"),
                         threading.Thread(target=self._scheduler, daemon=True, name="scheduler")]
        for t in self._threads: t.start()
        if self.connector_factory:
            self.conn = self.connector_factory(self.on_onebot_event)
            self.conn.start()
        self.log("开始监听 QQ 群消息")

    def stop(self):
        self._stop.set()
        if self.conn:
            try: self.conn.stop()
            except Exception: pass
        for t in self._threads: t.join(3)
        self._threads = []
        self.log("已停止监听")
