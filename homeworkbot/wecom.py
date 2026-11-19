"""企业微信群机器人 webhook: text / markdown / image / file / voice.
不支持原生视频: ≤20MB 视频改作文件发送(+简短说明); 更大则仅本地保存并在 markdown 中注明路径.
每个机器人限 20 条/分钟, 自动排队."""
import base64, hashlib, io, os, time
from collections import defaultdict, deque
from urllib.parse import parse_qs, urlparse

MD_LIMIT = 4096
TEXT_LIMIT = 2048
IMG_LIMIT = 2 * 1024 * 1024
FILE_LIMIT = 20 * 1024 * 1024
RATE_LIMIT = 20
RATE_WINDOW = 60.0
UPLOAD_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media"
IMG_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".m4v", ".webm", ".3gp"}
VOICE_EXTS = {".amr", ".silk"}

class WeComError(RuntimeError):
    pass

def truncate_bytes(s, limit, suffix="\n...(内容过长已截断)"):
    b = s.encode("utf-8")
    if len(b) <= limit: return s
    return b[:limit - len(suffix.encode())].decode("utf-8", "ignore") + suffix

def split_bytes(s, limit):
    parts, cur = [], ""
    for line in s.split("\n"):
        cand = (cur + "\n" + line) if cur else line
        if len(cand.encode("utf-8")) <= limit:
            cur = cand; continue
        if cur: parts.append(cur)
        while len(line.encode("utf-8")) > limit:
            head = line.encode("utf-8")[:limit].decode("utf-8", "ignore")
            parts.append(head); line = line[len(head):]
        cur = line
    if cur: parts.append(cur)
    return parts

def text_payload(content, mention_all=False):
    p = {"msgtype": "text", "text": {"content": truncate_bytes(content, TEXT_LIMIT)}}
    if mention_all: p["text"]["mentioned_list"] = ["@all"]
    return p

def markdown_payload(content):
    return {"msgtype": "markdown", "markdown": {"content": truncate_bytes(content, MD_LIMIT)}}

def prepare_image(data):
    if len(data) <= IMG_LIMIT and (data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff"):
        return data
    from PIL import Image
    img = Image.open(io.BytesIO(data)).convert("RGB")
    q, scale = 90, 1.0
    while True:
        im = img if scale == 1.0 else img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
        buf = io.BytesIO(); im.save(buf, "JPEG", quality=q, optimize=True)
        out = buf.getvalue()
        if len(out) <= IMG_LIMIT or (q <= 40 and scale <= 0.3): return out
        if q > 50: q -= 15
        else: scale *= 0.75

def image_payload(data):
    data = prepare_image(data)
    return {"msgtype": "image", "image": {"base64": base64.b64encode(data).decode("ascii"),
                                          "md5": hashlib.md5(data).hexdigest()}}

def file_payload(media_id):
    return {"msgtype": "file", "file": {"media_id": media_id}}

def voice_payload(media_id):
    return {"msgtype": "voice", "voice": {"media_id": media_id}}

def is_image_path(path):
    if os.path.splitext(path)[1].lower() in IMG_EXTS: return True
    try:
        with open(path, "rb") as f: h = f.read(8)
        return h[:8] == b"\x89PNG\r\n\x1a\n" or h[:3] == b"\xff\xd8\xff"
    except OSError: return False

def is_video_path(path, kind=""):
    return kind == "video" or os.path.splitext(path)[1].lower() in VIDEO_EXTS

def is_voice_path(path, kind=""):
    return kind == "record" or os.path.splitext(path)[1].lower() in VOICE_EXTS

def webhook_key(url):
    return (parse_qs(urlparse(url).query).get("key") or [""])[0]

def human_size(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB": return f"{n:.0f}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1024

def upload_media(key, path, media_type="file", session=None, timeout=60):
    if session is None:
        import requests as session
    if not key: raise WeComError("webhook 缺少 key, 无法上传素材")
    size = os.path.getsize(path)
    if media_type == "voice" and size > IMG_LIMIT: raise WeComError(f"语音超过 2MB ({size} bytes)")
    if size > FILE_LIMIT: raise WeComError(f"文件超过 20MB ({size} bytes)")
    if size < 5: raise WeComError("文件过小(<5 字节), 企业微信拒绝")
    name = os.path.basename(path)
    with open(path, "rb") as f:
        r = session.post(f"{UPLOAD_URL}?key={key}&type={media_type}", timeout=timeout,
                         files={"media": (name, f, "application/octet-stream")})
    r.raise_for_status()
    d = r.json()
    if d.get("errcode", 0) != 0: raise WeComError(f"上传素材失败 {d.get('errcode')}: {d.get('errmsg')}")
    mid = d.get("media_id")
    if not mid: raise WeComError(f"上传成功但未返回 media_id: {d}")
    return mid

def post(url, payload, session=None, timeout=15):
    if session is None:
        import requests as session
    r = session.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    d = r.json()
    if d.get("errcode", 0) != 0: raise WeComError(f"企业微信返回错误 {d.get('errcode')}: {d.get('errmsg')}")
    return d

def mask_url(url):
    return url.split("key=")[0] + "key=" + url.split("key=")[1][:6] + "***" if "key=" in url else url[:40]

def send_file(webhook, media_id, session=None):
    return post(webhook, file_payload(media_id), session)

def plan_attachment(att, push_images=True):
    if isinstance(att, str):
        att = {"kind": "image", "path": att, "name": os.path.basename(att), "send": True}
    if att.get("send") is False: return []
    path = att.get("path") or ""
    if not path or not os.path.exists(path): return []
    kind = att.get("kind") or "file"
    name = att.get("name") or os.path.basename(path)
    size = att.get("size") or os.path.getsize(path)
    acts = []
    if kind == "image" or (kind not in ("file", "video", "record") and is_image_path(path)):
        if not push_images: return []
        try:
            with open(path, "rb") as f: data = f.read()
            prepared = prepare_image(data)
            if len(prepared) <= IMG_LIMIT:
                acts.append({"type": "image", "data": prepared, "name": name})
            else:
                acts.append({"type": "file", "path": path, "name": name,
                             "intro": f"**图片附件(过大, 以文件发送):** {name} ({human_size(size)})"})
        except OSError as e:
            acts.append({"type": "note", "text": f"**图片读取失败:** {name} ({e})"})
        return acts
    if kind == "video" or is_video_path(path, kind):
        if size <= FILE_LIMIT:
            acts.append({"type": "file", "path": path, "name": name,
                         "intro": f"**视频附件(企业微信无原生视频, 以文件发送):** {name} ({human_size(size)})"})
        else:
            acts.append({"type": "note", "text": (
                f"**视频过大无法推送(>{human_size(FILE_LIMIT)}):** `{name}` ({human_size(size)})\n"
                f"> 已保存在本地: `{os.path.abspath(path)}`")})
        return acts
    if kind == "record" or is_voice_path(path, kind):
        ext = os.path.splitext(path)[1].lower()
        if ext == ".amr" and size <= IMG_LIMIT:
            acts.append({"type": "voice", "path": path, "name": name})
        elif size <= FILE_LIMIT:
            acts.append({"type": "file", "path": path, "name": name,
                         "intro": f"**语音附件(以文件发送):** {name} ({human_size(size)})"})
        else:
            acts.append({"type": "note", "text": f"**语音过大无法推送:** `{name}` ({human_size(size)})\n> `{os.path.abspath(path)}`"})
        return acts
    if size <= FILE_LIMIT:
        acts.append({"type": "file", "path": path, "name": name})
    else:
        acts.append({"type": "note", "text": (
            f"**文件过大无法推送(>{human_size(FILE_LIMIT)}):** `{name}` ({human_size(size)})\n"
            f"> 已保存在本地: `{os.path.abspath(path)}`")})
    return acts

def plan_all(text, attachments=(), fmt="markdown", push_images=True):
    limit = MD_LIMIT if fmt == "markdown" else TEXT_LIMIT
    mk = "markdown" if fmt == "markdown" else "text"
    body_parts = split_bytes(text or "", limit) or [""]
    media_acts, notes = [], []
    for att in attachments or ():
        for a in plan_attachment(att, push_images):
            if a["type"] == "note":
                notes.append(a["text"])
            elif a.get("intro"):
                notes.append(a["intro"])
                media_acts.append({k: v for k, v in a.items() if k != "intro"})
            else:
                media_acts.append(a)
    if notes:
        merged = body_parts[-1] + ("\n\n" if body_parts[-1] else "") + "\n\n".join(notes)
        body_parts = body_parts[:-1] + split_bytes(merged, limit)
    acts = [{"type": mk, "content": p} for p in body_parts if p]
    acts.extend(media_acts)
    return acts

class RateLimiter:
    def __init__(self, limit=RATE_LIMIT, window=RATE_WINDOW):
        self.limit, self.window, self._hits = limit, window, defaultdict(deque)
    def wait(self, key, sleep=time.sleep, now=time.time):
        q = self._hits[key or "_"]
        while True:
            t = now()
            while q and t - q[0] >= self.window: q.popleft()
            if len(q) < self.limit:
                q.append(t); return
            sleep(max(0.05, self.window - (t - q[0]) + 0.05))

class WeComSender:
    def __init__(self, webhooks, fmt="markdown", push_images=True, session=None, log=print,
                 interval=0.05, limiter=None):
        self.webhooks, self.fmt, self.push_images = webhooks, fmt, push_images
        self.session, self.log, self.interval = session, log, interval
        self.limiter = limiter or RateLimiter()

    def _exec_action(self, url, key, act):
        t = act["type"]
        if t == "markdown": return post(url, markdown_payload(act["content"]), self.session)
        if t == "text": return post(url, text_payload(act["content"]), self.session)
        if t == "image": return post(url, image_payload(act["data"]), self.session)
        if t == "file":
            mid = upload_media(key, act["path"], "file", self.session)
            return post(url, file_payload(mid), self.session)
        if t == "voice":
            mid = upload_media(key, act["path"], "voice", self.session)
            return post(url, voice_payload(mid), self.session)
        if t == "note": return post(url, markdown_payload(act["text"]), self.session)
        raise WeComError(f"未知动作类型: {t}")

    def send(self, text, attachments=(), retries=1, sleep=time.sleep, images=None):
        if not self.webhooks: raise WeComError("未配置企业微信机器人 webhook")
        atts = list(attachments or ())
        if images:
            for p in images:
                if isinstance(p, str):
                    atts.append({"kind": "image", "path": p, "name": os.path.basename(p), "send": True})
                elif isinstance(p, dict):
                    atts.append(p)
        acts = plan_all(text, atts, self.fmt, self.push_images)
        if not acts: raise WeComError("没有可推送的内容")
        errors = []
        for name, url in self.webhooks:
            key = webhook_key(url)
            i, attempt = 0, 1
            while i < len(acts):
                try:
                    self.limiter.wait(key, sleep=sleep)
                    if i and self.interval: sleep(self.interval)
                    self._exec_action(url, key, acts[i])
                    i += 1; attempt = 1
                except Exception as e:
                    self.log(f"企业微信 [{name}] 第 {i+1}/{len(acts)} 条失败(第{attempt}次): {e}")
                    if attempt >= max(1, retries):
                        errors.append(f"[{name}] {e}"); break
                    attempt += 1; sleep(2.0 * attempt)
            else:
                self.log(f"已推送到企业微信 [{name}] ({len(acts)} 条)")
        if errors: raise WeComError("; ".join(errors))
        return len(acts)
