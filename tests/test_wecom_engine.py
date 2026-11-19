"""企业微信推送 (模拟 webhook) 与处理引擎."""
import base64, datetime as dt, hashlib, io, json, os, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from PIL import Image
from homeworkbot import wecom
from homeworkbot.config import DEFAULTS
from homeworkbot.history import History
from homeworkbot.worker import Engine, download_images
from homeworkbot.parser import Attachment
from tests.test_onebot import group_event, wait

NOSLEEP = lambda s: None

class Resp:
    def __init__(self, d, content=b""): self.d, self.content = d, content
    def raise_for_status(self): pass
    def json(self): return self.d

class Hook:
    """模拟企业微信 webhook; fail 为前 N 次返回的错误."""
    def __init__(self, fail=0, errcode=45009):
        self.calls, self.fail, self.errcode = [], fail, errcode
    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json))
        if self.fail > 0:
            self.fail -= 1
            return Resp({"errcode": self.errcode, "errmsg": "api freq out of limit"})
        return Resp({"errcode": 0, "errmsg": "ok"})

def png_bytes(w=10, h=10):
    b = io.BytesIO(); Image.new("RGB", (w, h), (255, 0, 0)).save(b, "PNG"); return b.getvalue()

# ---------- payload ----------
def test_payloads():
    assert wecom.text_payload("hi") == {"msgtype": "text", "text": {"content": "hi"}}
    md = wecom.markdown_payload("中" * 3000)
    assert len(md["markdown"]["content"].encode()) <= 4096 and md["markdown"]["content"].endswith("截断)")
    data = png_bytes()
    p = wecom.image_payload(data)
    assert base64.b64decode(p["image"]["base64"]) == data and p["image"]["md5"] == hashlib.md5(data).hexdigest()

def test_image_compress_over_2mb():
    import random
    rnd = random.Random(1)
    img = Image.frombytes("RGB", (1400, 1400), bytes(rnd.getrandbits(8) for _ in range(1400 * 1400 * 3)))
    b = io.BytesIO(); img.save(b, "PNG"); raw = b.getvalue()
    assert len(raw) > wecom.IMG_LIMIT
    out = wecom.prepare_image(raw)
    assert len(out) <= wecom.IMG_LIMIT and out[:3] == b"\xff\xd8\xff"
    gif = io.BytesIO(); Image.new("RGB", (5, 5)).save(gif, "GIF")
    assert wecom.prepare_image(gif.getvalue())[:3] == b"\xff\xd8\xff"     # GIF 转 JPEG

def test_split_long_text():
    parts = wecom.split_bytes("\n".join(["第%d行作业内容" % i for i in range(600)]), 4096)
    assert len(parts) > 1 and all(len(p.encode()) <= 4096 for p in parts)

# ---------- sender ----------
def test_sender_multi_webhook_with_image(tmp_path):
    img = tmp_path / "a.png"; img.write_bytes(png_bytes())
    s = Hook()
    n = wecom.WeComSender([("A", "https://hook/a"), ("B", "https://hook/b")], session=s, log=NOSLEEP).send(
        "### 作业", [str(img)], sleep=NOSLEEP)
    assert n == 2 and [c[0] for c in s.calls] == ["https://hook/a"] * 2 + ["https://hook/b"] * 2
    assert s.calls[0][1]["msgtype"] == "markdown" and s.calls[1][1]["msgtype"] == "image"

def test_sender_retry_no_duplicates():
    s = Hook(fail=1)
    wecom.WeComSender([("A", "u")], fmt="text", session=s, log=NOSLEEP).send("x", retries=3, sleep=NOSLEEP)
    assert len(s.calls) == 2 and all(c[1]["msgtype"] == "text" for c in s.calls)

def test_sender_errcode_raises():
    s = Hook(fail=5, errcode=93000)
    with pytest.raises(wecom.WeComError, match="93000"):
        wecom.WeComSender([("A", "u")], session=s, log=NOSLEEP).send("x", retries=2, sleep=NOSLEEP)
    with pytest.raises(wecom.WeComError):
        wecom.WeComSender([], log=NOSLEEP).send("x")

def test_sender_real_http_to_local_fake_webhook():
    """真实 HTTP 请求, 但目标是本机模拟服务, 不会发到企业微信."""
    got = []
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            got.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            b = b'{"errcode":0,"errmsg":"ok"}'
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/cgi-bin/webhook/send?key=test"
    wecom.WeComSender([("本地", url)], log=NOSLEEP).send("**测试**")
    srv.shutdown()
    assert got[0][0] == "/cgi-bin/webhook/send?key=test" and got[0][1]["markdown"]["content"] == "**测试**"

def test_mask_url():
    assert wecom.mask_url("https://q/send?key=abcdef123456") == "https://q/send?key=abcdef***"

# ---------- 图片下载 ----------
def test_download_images(tmp_path):
    data = png_bytes()
    class S:
        def get(self, url, timeout=None):
            if "bad" in url: raise IOError("404")
            return Resp({}, data)
    out = download_images(["https://ok/1", "https://bad/2"], str(tmp_path), session=S(), log=NOSLEEP)
    assert len(out) == 1 and out[0].endswith(".png") and open(out[0], "rb").read() == data

# ---------- 引擎 ----------
def make_engine(tmp_path, over=None, sender=None, now=None):
    cfg = dict(DEFAULTS, qq_group_ids=[123456], teachers=["王老师"], save_dir=str(tmp_path / "out"),
               child_name="小明", wecom_webhooks=["家|https://hook/x"])
    cfg.update(over or {})
    events, sent = [], []
    img = tmp_path / "dl.png"; img.write_bytes(png_bytes())
    def dl(atts):
        out = []
        for a in atts:
            a.path = str(img); a.size = img.stat().st_size; out.append(a)
        return out
    e = Engine(cfg, History(str(tmp_path / "h.db")), log=NOSLEEP, sender=sender or (lambda t, i=(): sent.append((t, list(i)))),
               seen_path=str(tmp_path / "seen.json"), on_event=lambda k, d: events.append((k, d)), now=now,
               sleep=NOSLEEP, downloader=dl)
    return e, events, sent

def test_engine_preview_mode(tmp_path):
    e, ev, sent = make_engine(tmp_path)
    hid = e.handle_event(group_event(images=["https://qq/img1"]))
    rec = e.history.get(hid)
    assert rec["status"] == "pending" and not sent and "小明" in rec["message"] and len(rec["attachments"]) == 1
    assert os.path.exists(rec["attachments"][0]["path"]) and ("new", hid) in ev
    assert e.handle_event(group_event()) is None                       # 同 message_id 去重
    assert e.handle_event(group_event(card="小明妈妈")) is None          # 非老师
    assert e.send_record(hid, "编辑后") and sent[0][0] == "编辑后" and len(sent[0][1]) == 1
    assert e.history.get(hid)["status"] == "sent"

def test_engine_auto_mode(tmp_path):
    e, ev, sent = make_engine(tmp_path, {"send_mode": "auto"})
    hid = e.handle_event(group_event())
    assert e.history.get(hid)["status"] == "sent" and "### 作业通知" in sent[0][0]

def test_engine_push_failure_alert(tmp_path):
    def bad(t, i=()): raise wecom.WeComError("[家] 企业微信返回错误 93000: invalid webhook url")
    e, ev, _ = make_engine(tmp_path, {"send_mode": "auto"}, sender=bad)
    hid = e.handle_event(group_event())
    assert e.history.get(hid)["status"] == "failed" and any(k == "error" for k, _ in ev) and "93000" in e.last_error

def test_engine_with_real_wecom_sender_mock_session(tmp_path):
    """引擎 + 真实 WeComSender(注入假 session): 文字 + 图片两条."""
    s = Hook()
    def sender(text, images=()):
        wecom.WeComSender([("家", "https://hook/x")], session=s, log=NOSLEEP).send(text, images, sleep=NOSLEEP)
    e, _, _ = make_engine(tmp_path, {"send_mode": "auto"}, sender=sender)
    e.handle_event(group_event(images=["https://qq/img"]))
    assert [c[1]["msgtype"] for c in s.calls] == ["markdown", "image"]

def test_engine_threaded_queue_and_connector(tmp_path):
    """引擎线程 + 模拟连接器: on_onebot_event 只入队, 后台线程处理."""
    class FakeConn:
        def __init__(self, cb): self.cb, self.state, self.mode = cb, "waiting", "reverse_ws"
        def start(self): self.state = "connected"
        def stop(self): self.state = "stopped"
    e, ev, _ = make_engine(tmp_path)
    e.connector_factory = FakeConn
    e.start()
    assert e.running and e.conn.state == "connected"
    e.conn.cb(group_event(mid=7)); e.conn.cb({"post_type": "notice"})
    assert wait(lambda: any(k == "new" for k, _ in ev))
    e.stop()
    assert not e.running and e.received == 2 and e.conn.state == "stopped"

def test_daily_summary_schedule(tmp_path):
    clock = [dt.datetime(2026, 10, 14, 20, 0)]
    e, _, sent = make_engine(tmp_path, {"daily_summary": True, "daily_summary_time": "20:30"}, now=lambda: clock[0])
    e.handle_event(group_event())
    assert not e.check_summary() and not sent
    clock[0] = dt.datetime(2026, 10, 14, 20, 31)
    assert e.check_summary() and "作业汇总" in sent[0][0]
    assert not e.check_summary()                                       # 每天一次
