"""富媒体: 附件解析、下载、WeCom 上传/文件发送、视频回退、速率限制、引擎贯通."""
import io, os
from PIL import Image
import pytest
from homeworkbot.parser import parse_event, Attachment, accept
from homeworkbot.config import DEFAULTS
from homeworkbot import wecom
from homeworkbot.worker import Engine, download_attachments
from homeworkbot.history import History
from tests.test_onebot import group_event

NOSLEEP = lambda s: None

def png_bytes(w=10, h=10):
    b = io.BytesIO(); Image.new("RGB", (w, h), (255, 0, 0)).save(b, "PNG"); return b.getvalue()

def big_png():
    import random
    rnd = random.Random(1); side = 1600
    img = Image.frombytes("RGB", (side, side), bytes(rnd.getrandbits(8) for _ in range(side * side * 3)))
    b = io.BytesIO(); img.save(b, "PNG"); return b.getvalue()

class Resp:
    def __init__(self, d=None, content=b"", status=200):
        self._d, self.content, self.status_code = d or {"errcode": 0, "errmsg": "ok"}, content, status
    def raise_for_status(self):
        if self.status_code >= 400: raise IOError(self.status_code)
    def json(self): return self._d

def test_parse_file_video_record_segments():
    ev = group_event(text="看附件")
    ev["message"] = [
        {"type": "text", "data": {"text": "今日作业见附件"}},
        {"type": "image", "data": {"file": "a.jpg", "url": "https://qq/img"}},
        {"type": "file", "data": {"file_name": "练习册.pdf", "url": "https://qq/file"}},
        {"type": "video", "data": {"file": "v.mp4", "url": "https://qq/vid"}},
        {"type": "record", "data": {"file": "r.amr", "url": "https://qq/voice"}},
    ]
    m = parse_event(ev)
    assert m.text == "今日作业见附件"
    assert [a.kind for a in m.attachments] == ["image", "file", "video", "record"]
    assert m.attachments[1].name == "练习册.pdf"
    assert accept(parse_event({**ev, "message": [{"type": "video", "data": {"url": "https://qq/v"}}]}),
                  dict(DEFAULTS, qq_group_ids=[123456], teachers=["王老师"]))

def test_parse_cq_file_and_video():
    ev = group_event()
    ev["message"] = "作业[CQ:file,file=a.pdf,url=https://x/a&#44;b][CQ:video,file=v.mp4,url=https://x/v]"
    m = parse_event(ev)
    assert [a.kind for a in m.attachments] == ["file", "video"]
    assert m.attachments[0].url == "https://x/a,b"

def test_attachment_from_legacy_path():
    a = Attachment.from_dict("/tmp/a.png")
    assert a.kind == "image" and a.path.endswith("a.png")

def test_plan_image_ok_and_oversized(tmp_path):
    small = tmp_path / "s.png"; small.write_bytes(png_bytes())
    assert wecom.plan_attachment({"kind": "image", "path": str(small), "name": "s.png"})[0]["type"] == "image"
    big = tmp_path / "b.png"; data = big_png(); big.write_bytes(data)
    assert len(data) > wecom.IMG_LIMIT
    assert wecom.plan_attachment({"kind": "image", "path": str(big), "name": "b.png"})[0]["type"] in ("image", "file")

def test_plan_video_as_file_or_note(tmp_path):
    v = tmp_path / "a.mp4"; v.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 100)
    acts = wecom.plan_attachment({"kind": "video", "path": str(v), "name": "a.mp4", "size": v.stat().st_size})
    assert acts[0]["type"] == "file" and "视频" in acts[0]["intro"]
    huge = tmp_path / "huge.mp4"; huge.write_bytes(b"x")
    acts = wecom.plan_attachment({"kind": "video", "path": str(huge), "name": "huge.mp4", "size": 25 * 1024 * 1024})
    assert acts[0]["type"] == "note" and "过大" in acts[0]["text"] and str(huge.resolve()) in acts[0]["text"]

def test_plan_skip_unchecked():
    assert wecom.plan_attachment({"kind": "image", "path": "/x", "send": False}) == []

def test_plan_all_merges_notes_into_body(tmp_path):
    v = tmp_path / "a.mp4"; v.write_bytes(b"\x00\x00\x00\x18ftyp" + b"x" * 50)
    acts = wecom.plan_all("作业正文", [{"kind": "video", "path": str(v), "name": "a.mp4"}], "markdown")
    assert acts[0]["type"] == "markdown" and "作业正文" in acts[0]["content"] and "视频" in acts[0]["content"]
    assert any(a["type"] == "file" for a in acts)

def test_upload_media_and_send_file(tmp_path):
    f = tmp_path / "doc.pdf"; f.write_bytes(b"%PDF-1.4 hello world xx")
    uploaded = {}
    class S:
        def post(self, url, **kw):
            if "upload_media" in url:
                assert "type=file" in url and "key=abc" in url
                uploaded["ok"] = True
                return Resp({"errcode": 0, "media_id": "MID123", "type": "file"})
            assert kw["json"] == {"msgtype": "file", "file": {"media_id": "MID123"}}
            return Resp({"errcode": 0, "errmsg": "ok"})
    mid = wecom.upload_media("abc", str(f), "file", session=S())
    assert mid == "MID123" and uploaded["ok"]
    wecom.send_file("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc", mid, session=S())

def test_sender_rich_media_sequence(tmp_path):
    img = tmp_path / "a.png"; img.write_bytes(png_bytes())
    pdf = tmp_path / "hw.pdf"; pdf.write_bytes(b"%PDF homework content!!")
    calls = []
    class S:
        def post(self, url, **kw):
            if "upload_media" in url:
                calls.append(("upload", url)); return Resp({"errcode": 0, "media_id": "M1"})
            calls.append(("send", kw["json"]["msgtype"])); return Resp({"errcode": 0})
    n = wecom.WeComSender([("家", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k1")],
                          session=S(), log=NOSLEEP).send(
        "### 作业", [{"kind": "image", "path": str(img), "name": "a.png"},
                     {"kind": "file", "path": str(pdf), "name": "hw.pdf"}], sleep=NOSLEEP)
    assert [c[1] if c[0] == "send" else c[0] for c in calls] == ["markdown", "image", "upload", "file"]
    assert n == 3

def test_sender_video_large_note_only(tmp_path):
    v = tmp_path / "big.mp4"; v.write_bytes(b"x")
    calls = []
    class S:
        def post(self, url, **kw):
            calls.append(kw["json"]); return Resp({"errcode": 0})
    wecom.WeComSender([("家", "https://h?key=k")], session=S(), log=NOSLEEP).send(
        "正文", [{"kind": "video", "path": str(v), "name": "big.mp4", "size": 30 * 1024 * 1024}], sleep=NOSLEEP)
    assert len(calls) == 1 and "过大无法推送" in calls[0]["markdown"]["content"]

def test_rate_limiter_waits():
    slept = []
    lim = wecom.RateLimiter(limit=2, window=1.0)
    clock = [1000.0]
    def sleep(s): slept.append(s); clock[0] += s
    lim.wait("k", sleep=sleep, now=lambda: clock[0])
    lim.wait("k", sleep=sleep, now=lambda: clock[0])
    lim.wait("k", sleep=sleep, now=lambda: clock[0])
    assert slept and slept[-1] > 0

def test_webhook_key():
    assert wecom.webhook_key("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc-def") == "abc-def"

def test_download_mixed_attachments(tmp_path):
    data = {"https://ok/img": png_bytes(), "https://ok/pdf": b"%PDF-1.4 xxxx",
            "https://ok/vid": b"\x00\x00\x00\x18ftypmp42xxxx"}
    class S:
        def get(self, url, timeout=None):
            if "bad" in url: raise IOError("404")
            return Resp(content=data[url])
    atts = [Attachment("image", "https://ok/img", "a.jpg"),
            Attachment("file", "https://ok/pdf", "作业.pdf"),
            Attachment("video", "https://ok/vid", "讲解.mp4"),
            Attachment("file", "https://bad/x", "x.bin")]
    out = download_attachments(atts, str(tmp_path), session=S(), log=NOSLEEP)
    assert len(out) == 3 and out[1].name.endswith(".pdf") and out[2].kind == "video"

def test_engine_with_file_and_video(tmp_path):
    img = tmp_path / "dl.png"; img.write_bytes(png_bytes())
    pdf = tmp_path / "dl.pdf"; pdf.write_bytes(b"%PDF homework")
    vid = tmp_path / "dl.mp4"; vid.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"z" * 40)
    sent = []
    def sender(text, atts=()): sent.append((text, list(atts)))
    def dl(atts):
        mapping = {"image": img, "file": pdf, "video": vid}
        out = []
        for a in atts:
            a.path = str(mapping[a.kind]); a.size = os.path.getsize(a.path); out.append(a)
        return out
    cfg = dict(DEFAULTS, qq_group_ids=[123456], teachers=["王老师"], save_dir=str(tmp_path / "out"),
               child_name="小明", wecom_webhooks=["家|https://hook/x"], send_mode="preview")
    e = Engine(cfg, History(str(tmp_path / "h.db")), log=NOSLEEP, sender=sender,
               seen_path=str(tmp_path / "seen.json"), downloader=dl, sleep=NOSLEEP)
    ev = group_event(text="今日作业见附件")
    ev["message"] = [
        {"type": "text", "data": {"text": "今日作业见附件和视频讲解"}},
        {"type": "image", "data": {"url": "https://qq/i"}},
        {"type": "file", "data": {"file_name": "练习.pdf", "url": "https://qq/f"}},
        {"type": "video", "data": {"url": "https://qq/v"}},
    ]
    hid = e.handle_event(ev)
    rec = e.history.get(hid)
    assert len(rec["attachments"]) == 3
    assert {a["kind"] for a in rec["attachments"]} == {"image", "file", "video"}
    chosen = [dict(rec["attachments"][0], send=True), dict(rec["attachments"][1], send=False),
              dict(rec["attachments"][2], send=True)]
    assert e.send_record(hid, "编辑后", chosen)
    assert sent[0][0] == "编辑后" and {a["kind"] for a in sent[0][1]} == {"image", "video"}

def test_engine_auto_calls_real_wecom_sender_mock(tmp_path):
    img = tmp_path / "a.png"; img.write_bytes(png_bytes())
    pdf = tmp_path / "a.pdf"; pdf.write_bytes(b"%PDF xx content enough")
    calls = []
    class S:
        def post(self, url, **kw):
            if "upload_media" in url: calls.append("upload"); return Resp({"errcode": 0, "media_id": "M"})
            calls.append(kw["json"]["msgtype"]); return Resp({"errcode": 0})
    def sender(text, atts=()):
        wecom.WeComSender([("家", "https://h?key=k")], session=S(), log=NOSLEEP).send(text, atts, sleep=NOSLEEP)
    def dl(atts):
        for a in atts:
            a.path = str(img if a.kind == "image" else pdf); a.size = os.path.getsize(a.path)
        return list(atts)
    cfg = dict(DEFAULTS, qq_group_ids=[123456], teachers=["王老师"], save_dir=str(tmp_path / "out"),
               send_mode="auto", wecom_webhooks=["家|https://h?key=k"])
    e = Engine(cfg, History(str(tmp_path / "h.db")), log=NOSLEEP, sender=sender,
               seen_path=str(tmp_path / "s.json"), downloader=dl, sleep=NOSLEEP)
    ev = group_event(text="数学作业：练习册")
    ev["message"] = [{"type": "text", "data": {"text": "数学作业：练习册"}},
                     {"type": "image", "data": {"url": "https://i"}},
                     {"type": "file", "data": {"file_name": "a.pdf", "url": "https://f"}}]
    e.handle_event(ev)
    assert calls == ["markdown", "image", "upload", "file"]
