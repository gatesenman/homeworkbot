"""OneBot v11 消息事件解析/过滤/去重. 支持 image/file/video/record 段. 纯函数, 可单测."""
import difflib, hashlib, html, json, os, re
from dataclasses import dataclass, field, asdict

@dataclass
class Attachment:
    kind: str
    url: str = ""
    name: str = ""
    path: str = ""
    size: int = 0
    send: bool = True

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        if isinstance(d, str):
            return cls(kind="image", path=d, name=os.path.basename(d))
        return cls(kind=d.get("kind") or "file", url=d.get("url") or "", name=d.get("name") or "",
                   path=d.get("path") or "", size=int(d.get("size") or 0), send=d.get("send", True))

@dataclass
class Message:
    sender: str
    text: str
    time: str = ""
    group: str = ""
    attachments: list = field(default_factory=list)
    user_id: str = ""
    message_id: str = ""
    nickname: str = ""
    card: str = ""

    @property
    def images(self):
        return [a.path or a.url for a in self.attachments if a.kind == "image"]

    @property
    def key(self):
        if self.message_id:
            return f"mid:{self.group}:{self.message_id}"
        return hashlib.sha1(f"{self.sender}|{norm_text(self.text)}".encode("utf-8")).hexdigest()

def norm_text(t):
    return re.sub(r"[\s，,。.：:；;！!？?、\"\'“”‘’()（）\[\]【】]+", "", t or "")

CQ_RE = re.compile(r"\[CQ:(\w+)((?:,[^\]]*)?)\]")

def _cq_unescape(s):
    return s.replace("&#44;", ",").replace("&#91;", "[").replace("&#93;", "]").replace("&amp;", "&")

def cq_to_segments(s):
    segs, pos = [], 0
    for m in CQ_RE.finditer(s or ""):
        if m.start() > pos:
            segs.append({"type": "text", "data": {"text": _cq_unescape(s[pos:m.start()])}})
        data = {}
        for kv in filter(None, m.group(2).split(",")):
            k, _, v = kv.partition("=")
            data[k] = _cq_unescape(v)
        segs.append({"type": m.group(1), "data": data})
        pos = m.end()
    if pos < len(s or ""):
        segs.append({"type": "text", "data": {"text": _cq_unescape(s[pos:])}})
    return segs

def segments_of(event):
    msg = event.get("message")
    if isinstance(msg, list): return msg
    if isinstance(msg, str): return cq_to_segments(msg)
    return cq_to_segments(event.get("raw_message", ""))

def media_url(seg_data):
    for k in ("url", "file"):
        v = (seg_data or {}).get(k) or ""
        if isinstance(v, str) and v.startswith("http"):
            return html.unescape(v)
    return ""

def _guess_name(d, kind, fallback=""):
    for k in ("file_name", "filename", "name", "file"):
        v = (d or {}).get(k) or ""
        if v and not str(v).startswith("http") and "/" not in str(v) and "\\" not in str(v):
            return str(v)
        if v and ("/" in str(v) or "\\" in str(v)):
            return os.path.basename(str(v).split("?")[0])
    return fallback or {"image": "image.jpg", "video": "video.mp4", "file": "file.bin", "record": "voice.amr"}.get(kind, "file.bin")

def parse_segments(segs):
    texts, atts = [], []
    for seg in segs:
        t, d = seg.get("type"), seg.get("data") or {}
        if t == "text":
            texts.append(d.get("text", ""))
        elif t == "at":
            texts.append("@" + str(d.get("name") or d.get("qq") or "") + " ")
        elif t == "face":
            continue
        elif t == "image":
            u = media_url(d)
            if u: atts.append(Attachment("image", u, _guess_name(d, "image")))
        elif t == "file":
            u = media_url(d)
            if u: atts.append(Attachment("file", u, _guess_name(d, "file")))
        elif t == "video":
            u = media_url(d)
            if u: atts.append(Attachment("video", u, _guess_name(d, "video")))
        elif t in ("record", "voice"):
            u = media_url(d)
            if u: atts.append(Attachment("record", u, _guess_name(d, "record")))
        elif t in ("json", "xml"):
            continue
        else:
            u = media_url(d)
            if u: atts.append(Attachment("file", u, _guess_name(d, "file", t or "file")))
    return "".join(texts).strip(), atts

def parse_event(event):
    if not isinstance(event, dict) or event.get("post_type") not in ("message", "message_sent"):
        return None
    if event.get("message_type") != "group":
        return None
    text, atts = parse_segments(segments_of(event))
    sender = event.get("sender") or {}
    card, nick = (sender.get("card") or "").strip(), (sender.get("nickname") or "").strip()
    uid = str(event.get("user_id") or sender.get("user_id") or "")
    import datetime as dt
    ts = event.get("time")
    when = dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if isinstance(ts, (int, float)) else ""
    return Message(sender=card or nick or uid, text=text, time=when,
                   group=str(event.get("group_id") or ""), attachments=atts, user_id=uid,
                   message_id=str(event.get("message_id") or ""), nickname=nick, card=card)

def normalize_name(n):
    n = re.sub(r"^【[^】]*】", "", n or "")
    return re.sub(r"[\(（]\d+[\)）]", "", n).strip()

def is_teacher(msg, teachers):
    names = [normalize_name(msg.card), normalize_name(msg.nickname), normalize_name(msg.sender)]
    for t in teachers:
        t = str(t).strip()
        if not t: continue
        if t.isdigit() and t == msg.user_id: return True
        if not t.isdigit() and any(n and (t == n or t in n) for n in names): return True
    return False

def is_homework(text, keywords):
    t = text or ""
    return len(t.strip()) >= 4 and any(k in t for k in keywords)

def accept(msg, cfg):
    if msg is None: return False
    groups = [str(g) for g in cfg.get("qq_group_ids", [])]
    if groups and msg.group not in groups: return False
    if not is_teacher(msg, cfg.get("teachers", [])): return False
    if msg.attachments: return True
    return is_homework(msg.text, cfg.get("homework_keywords", [])) if cfg.get("require_keyword", True) \
        else len(msg.text.strip()) >= 2

def similarity(a, b):
    a, b = norm_text(a), norm_text(b)
    if not a or not b: return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()

class SeenStore:
    def __init__(self, path, limit=3000, threshold=0.9, recent=200):
        self.path, self.limit, self.threshold, self.recent = path, limit, threshold, recent
        self.keys, self.texts = [], []
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
                if isinstance(d, list): self.keys = d
                else: self.keys, self.texts = d.get("keys", []), d.get("texts", [])
            except (OSError, ValueError): pass
        self._set = set(self.keys)

    def __contains__(self, key): return key in self._set

    def is_dup(self, msg):
        if msg.key in self._set: return True
        if len(norm_text(msg.text)) < 8: return False
        return any(similarity(msg.text, t) >= self.threshold for t in self.texts[-self.recent:])

    def add_msg(self, msg):
        self.add(msg.key, msg.text if len(norm_text(msg.text)) >= 8 else None)

    def add(self, key, text=None):
        if key not in self._set: self.keys.append(key)
        if text: self.texts.append(norm_text(text)[:500])
        self.keys, self.texts = self.keys[-self.limit:], self.texts[-self.recent:]
        self._set = set(self.keys)
        if self.path:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"keys": self.keys, "texts": self.texts}, f, ensure_ascii=False)
