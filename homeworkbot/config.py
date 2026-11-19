"""配置读写 (config.json), 兼容 v1/v2 配置."""
import json, os, re, sys

DEFAULT_PROMPT = (
    "你是小学/初中家长的作业整理助手。把老师在群里发的作业消息整理成 JSON, 只输出 JSON, 不要其他文字。"
    "字段: date(作业布置日期, YYYY-MM-DD), subject(科目, 多科用顿号分隔), "
    "items(作业条目字符串数组, 每条一项, 去掉序号), deadline(截止时间, 没有写则为空字符串), "
    "notes(注意事项/需家长配合的事项, 字符串数组)。不要编造原文没有的内容。"
)
DEFAULT_TEMPLATE = "{greeting}\n{child}今天的作业来啦\n\n{content}\n\n—— 作业小助手自动整理"

DEFAULTS = {
    # ---- QQ / NapCat (OneBot v11) ----
    "onebot_mode": "reverse_ws",        # reverse_ws / forward_ws / http_post
    "reverse_ws_host": "127.0.0.1",
    "reverse_ws_port": 8095,            # NapCat 反向 WS 连接 ws://127.0.0.1:8095/onebot/v11/ws
    "forward_ws_url": "ws://127.0.0.1:3001",
    "http_post_host": "127.0.0.1",
    "http_post_port": 8096,             # NapCat HTTP 客户端上报到 http://127.0.0.1:8096/
    "napcat_http_api": "http://127.0.0.1:3000",   # 仅 HTTP 上报模式下“测试连接”用
    "access_token": "",
    "http_secret": "",                  # HTTP 上报签名密钥(可选)
    "qq_group_ids": [],                 # 监听的群号
    "teachers": [],                     # 老师 QQ 号 / 昵称 / 群名片, 任一匹配即可
    "homework_keywords": ["作业", "预习", "复习", "背诵", "默写", "抄写", "练习", "试卷",
                          "订正", "阅读", "完成", "听写", "口算", "打卡", "家长签字"],
    "require_keyword": True,            # 是否必须含作业关键词(带图片的老师消息总是保留)
    "save_dir": "作业记录",
    "save_format": "md",
    "save_attachments": True,
    # ---- 企业微信 ----
    "wecom_webhooks": [],               # 每行 "名称|URL" 或直接 URL
    "push_format": "markdown",          # markdown / text
    "push_images": True,
    "send_mode": "preview",             # preview / auto
    "child_name": "",
    "greeting": "各位家人好~",
    "message_template": DEFAULT_TEMPLATE,
    "daily_summary": False,
    "daily_summary_time": "20:30",
    # ---- AI ----
    "api_base_url": "https://api.deepseek.com/v1",
    "api_key": "",
    "model": "deepseek-chat",
    "llm_prompt": DEFAULT_PROMPT,
    "max_retries": 3,
    "dedup_similarity": 0.9,
    # ---- 系统 ----
    "autostart": False,
    "start_minimized": True,
    "auto_listen": True,
    "minimize_to_tray": True,
    "notify": True,
    "theme": "system",
    "setup_done": False,
    # ---- v3.3 NapCat 管理 ----
    "napcat_dir": "",
    "napcat_args": "",
    "napcat_autostart": False,
    "napcat_watchdog": True,
    "napcat_webui": "http://127.0.0.1:6099/webui",
    # ---- v3.3 提醒 / 周报 ----
    "evening_reminder": True,
    "evening_reminder_time": "20:00",
    "evening_push": True,
    "morning_reminder": False,
    "morning_reminder_time": "07:00",
    "weekly_report": True,
    "weekly_report_time": "20:30",
}
OBSOLETE = ("qq_group", "qq_groups", "wechat_group", "poll_interval", "use_ocr_fallback",
            "skip_existing_on_start", "send_to_wechat")
SECRET_KEYS = ("api_key", "access_token", "http_secret")
WECOM_URL_RE = re.compile(r"^https://qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key=[A-Za-z0-9_-]+$", re.I)


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def resource_dir():
    """只读资源目录: PyInstaller 6 onedir 会把 --add-data 放进 _internal (sys._MEIPASS)."""
    return getattr(sys, "_MEIPASS", None) or app_dir()

def find_asset(*parts):
    """在 resource_dir(_internal) 与 app_dir(exe旁) 中查找资源文件."""
    candidates = []
    for base in (resource_dir(), app_dir()):
        candidates.append(os.path.join(base, *parts))
        # PyInstaller 有时把 assets 直接铺在 _MEIPASS 根下
        if parts and parts[0] == "assets" and len(parts) > 1:
            candidates.append(os.path.join(base, *parts[1:]))
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return candidates[0] if candidates else ""


def resolve_dir(path):
    """相对路径一律相对程序目录 (开机自启时工作目录可能是 System32)."""
    path = os.path.expanduser(path or "作业记录")
    return path if os.path.isabs(path) else os.path.join(app_dir(), path)

def config_path(base=None):
    return os.path.join(base or app_dir(), "config.json")

def split_names(s):
    if isinstance(s, list):
        return [str(x).strip() for x in s if str(x).strip()]
    return [x.strip() for x in re.split(r"[,，;；、\n]+", s or "") if x.strip()]

def split_lines(s):
    if isinstance(s, list):
        return [str(x).strip() for x in s if str(x).strip()]
    return [x.strip() for x in (s or "").splitlines() if x.strip()]

def parse_group_ids(v):
    out = []
    for x in re.findall(r"\d+", " ".join(map(str, v)) if isinstance(v, list) else str(v or "")):
        if int(x) not in out:
            out.append(int(x))
    return out

def parse_webhooks(lines):
    """'名称|URL' 或 URL -> [(名称, URL)]; 只接受企业微信 webhook 地址."""
    out = []
    for i, ln in enumerate(split_lines(lines), 1):
        name, _, url = ln.rpartition("|") if "|" in ln else ("", "", ln)
        url = url.strip()
        if url.startswith("http"):
            out.append(((name or f"机器人{i}").strip(), url))
    return out

def load_config(path=None):
    path = path or config_path()
    cfg = json.loads(json.dumps(DEFAULTS))
    raw = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = {}
    cfg.update({k: v for k, v in raw.items() if k not in OBSOLETE})
    cfg["teachers"] = split_names(cfg["teachers"])
    cfg["qq_group_ids"] = parse_group_ids(cfg["qq_group_ids"])
    cfg["wecom_webhooks"] = split_lines(cfg["wecom_webhooks"])
    if cfg.get("send_mode") not in ("preview", "auto"):
        cfg["send_mode"] = "preview"
    return cfg

def save_config(cfg, path=None):
    path = path or config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def is_setup_complete(cfg):
    """是否已完成首次配置: 至少有老师 + 至少一个合法 Webhook."""
    if cfg.get("setup_done"):
        return True
    teachers = split_names(cfg.get("teachers") or [])
    hooks = parse_webhooks(cfg.get("wecom_webhooks") or [])
    return bool(teachers) and bool(hooks)

def validate_webhook_url(url):
    """校验企业微信 webhook; 返回 (ok, reason)."""
    url = (url or "").strip()
    if not url:
        return False, "地址为空"
    if "|" in url:
        _, _, url = url.rpartition("|")
        url = url.strip()
    if not url.startswith("https://"):
        return False, "必须以 https:// 开头"
    if "qyapi.weixin.qq.com" not in url:
        return False, "必须是 qyapi.weixin.qq.com 企业微信地址"
    if "/cgi-bin/webhook/send" not in url or "key=" not in url:
        return False, "缺少 /cgi-bin/webhook/send?key=..."
    if not WECOM_URL_RE.match(url.split()[0]):
        # 宽松: key 含特殊字符也接受, 只要结构对
        if not re.search(r"key=[A-Za-z0-9_-]+", url):
            return False, "key 参数格式不正确"
    return True, "OK"

def validate_webhooks(lines):
    """校验多行 webhook; 返回 (ok_list, errors)."""
    ok, errs = [], []
    for i, ln in enumerate(split_lines(lines), 1):
        name, _, url = ln.rpartition("|") if "|" in ln else ("", "", ln)
        good, reason = validate_webhook_url(url.strip() or ln)
        if good:
            ok.append(ln)
        else:
            errs.append(f"第{i}行: {reason}")
    return ok, errs

def mask_secret(value, keep=4):
    """UI 展示用: 保留末尾 keep 位, 其余用 •."""
    s = str(value or "")
    if not s:
        return ""
    if len(s) <= keep:
        return "•" * len(s)
    return "•" * max(4, len(s) - keep) + s[-keep:]

def export_config(cfg, include_secrets=False):
    """导出配置字典; include_secrets=False 时清空密钥字段."""
    out = {k: cfg.get(k, DEFAULTS.get(k)) for k in DEFAULTS}
    out["setup_done"] = bool(cfg.get("setup_done") or is_setup_complete(cfg))
    if not include_secrets:
        for k in SECRET_KEYS:
            out[k] = ""
        # webhook 只保留名称占位, 去掉 key
        masked = []
        for ln in split_lines(out.get("wecom_webhooks") or []):
            name, _, url = ln.rpartition("|") if "|" in ln else ("", "", ln)
            if "key=" in url:
                url = re.sub(r"(key=)[^&\s]+", r"\1***", url, flags=re.I)
            masked.append(f"{name}|{url}" if name else url)
        out["wecom_webhooks"] = masked
    return out

def import_config(raw, merge=True, base=None):
    """导入配置; merge=True 时空密钥不覆盖已有密钥."""
    cur = load_config(base) if merge else json.loads(json.dumps(DEFAULTS))
    if not isinstance(raw, dict):
        raise ValueError("配置必须是 JSON 对象")
    for k, v in raw.items():
        if k in OBSOLETE:
            continue
        if k not in DEFAULTS and k != "setup_done":
            continue
        if merge and k in SECRET_KEYS and not v and cur.get(k):
            continue
        if merge and k == "wecom_webhooks":
            # 跳过含 *** 的占位行
            lines = split_lines(v)
            if lines and all("***" in ln for ln in lines):
                continue
            cleaned = [ln for ln in lines if "***" not in ln]
            if cleaned:
                cur[k] = cleaned
            continue
        cur[k] = v
    cur["teachers"] = split_names(cur.get("teachers"))
    cur["qq_group_ids"] = parse_group_ids(cur.get("qq_group_ids"))
    cur["wecom_webhooks"] = split_lines(cur.get("wecom_webhooks"))
    return cur

