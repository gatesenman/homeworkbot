"""调用 OpenAI 兼容接口整理作业; 支持自定义提示词、重试和规则兜底."""
import datetime as dt, json, re, time
from .config import DEFAULT_PROMPT, DEFAULT_TEMPLATE

SUBJECTS = ["语文", "数学", "英语", "物理", "化学", "生物", "历史", "地理", "政治", "道德与法治",
            "科学", "音乐", "美术", "体育", "信息", "书法"]

def build_messages(text, sender, today, prompt=None):
    return [
        {"role": "system", "content": prompt or DEFAULT_PROMPT},
        {"role": "user", "content": f"今天是 {today}。发送者: {sender}\n消息原文:\n{text}"},
    ]

def extract_json(s):
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", (s or "").strip())
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        raise ValueError("LLM 返回中没有 JSON")
    return json.loads(m.group(0))

def _as_list(v):
    if v is None: return []
    if isinstance(v, str): return [x for x in (i.strip() for i in v.splitlines()) if x]
    return [str(x).strip() for x in v if str(x).strip()]

def normalize_result(d, today, sender=""):
    return {
        "date": str(d.get("date") or today),
        "subject": str(d.get("subject") or "未注明"),
        "items": _as_list(d.get("items")),
        "deadline": str(d.get("deadline") or ""),
        "notes": _as_list(d.get("notes")),
        "sender": sender,
    }

INTRO_RE = re.compile(r"^(?:各位)?(?:家长|同学|小朋友|家人)(?:们)?(?:好|晚上好|下午好|中午好)?[，,！!。\s]*"
                      r"(?:(?:今天|今日|本周|明天)?的?(?:家庭)?作业(?:如下|是)?)?[：:，,。!！\s]*$")

def is_intro_line(line):
    """问候/标题行(如 '各位家长好，今天作业：') 不算作业也不算注意事项."""
    s = line.strip()
    if INTRO_RE.match(s):
        return True
    return bool(re.match(r"^(?:今天|今日|本周|明天)?的?(?:家庭)?作业(?:如下|是)?[：:]?$", s))

def rule_based(text, today, sender=""):
    subjects = [s for s in SUBJECTS if s in text]
    items, notes, deadline = [], [], ""
    for line in re.split(r"[\n；;]", text):
        line = line.strip()
        if not line: continue
        clean = re.sub(r"^\s*(?:\d+|[一二三四五六七八九十]+)[\.、．)）]\s*", "", line)
        if is_intro_line(clean):
            continue
        dm = re.search(r"((?:明天|后天|今晚|本周[一二三四五六日天]|周[一二三四五六日天]|\d{1,2}月\d{1,2}[日号])[^，,。]*?(?:前|之前|交|提交|完成))", clean)
        if dm and not deadline:
            deadline = dm.group(1)
        if re.search(r"注意|提醒|家长|签字|请各位|务必", clean):
            notes.append(clean)
        else:
            items.append(clean)
    return normalize_result({"date": today, "subject": "、".join(subjects) or "未注明",
                             "items": items, "deadline": deadline, "notes": notes}, today, sender)

def call_llm(text, sender, cfg, today=None, session=None):
    today = today or dt.date.today().isoformat()
    if session is None:
        import requests as session
    url = cfg["api_base_url"].rstrip("/") + "/chat/completions"
    r = session.post(url, timeout=60,
                     headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
                     json={"model": cfg["model"], "temperature": 0.1,
                           "messages": build_messages(text, sender, today, cfg.get("llm_prompt"))})
    r.raise_for_status()
    return normalize_result(extract_json(r.json()["choices"][0]["message"]["content"]), today, sender)

def with_retry(fn, retries=3, delay=2.0, log=print, what="操作", sleep=time.sleep):
    last = None
    for i in range(1, max(1, retries) + 1):
        try:
            return fn()
        except Exception as e:  # noqa
            last = e
            log(f"{what}失败(第{i}次): {e}")
            if i < retries:
                sleep(delay * i)
    raise last

def format_homework(text, sender, cfg, today=None, log=print, session=None, sleep=time.sleep):
    """返回 (结果, 是否用了AI). AI 多次失败则规则兜底."""
    today = today or dt.date.today().isoformat()
    if cfg.get("api_key"):
        try:
            r = with_retry(lambda: call_llm(text, sender, cfg, today, session),
                           cfg.get("max_retries", 3), log=log, what="AI 整理", sleep=sleep)
            return r
        except Exception as e:  # noqa
            log(f"AI 整理最终失败, 使用规则兜底: {e}")
    return rule_based(text, today, sender)

def render_text(r):
    lines = [f"【作业通知】{r['date']}", f"科目: {r['subject']}", "作业内容:"]
    lines += [f"  {i}. {x}" for i, x in enumerate(r["items"], 1)] or ["  (无)"]
    lines.append(f"截止时间: {r['deadline'] or '未注明'}")
    if r["notes"]:
        lines.append("注意事项:")
        lines += [f"  - {n}" for n in r["notes"]]
    if r.get("sender"):
        lines.append(f"(来源: {r['sender']})")
    return "\n".join(lines)

class _SafeDict(dict):
    def __missing__(self, k):
        return "{" + k + "}"

def apply_template(content, cfg, r=None):
    tpl = cfg.get("message_template") or DEFAULT_TEMPLATE
    child = cfg.get("child_name") or ""
    vals = _SafeDict(greeting=cfg.get("greeting", ""), child=child, child_name=child, content=content,
                     date=(r or {}).get("date", ""), subject=(r or {}).get("subject", ""))
    out = tpl.format_map(vals)
    return re.sub(r"\n{3,}", "\n\n", out).strip()

def render_daily_summary(records, date, cfg):
    if not records:
        body = f"【{date} 作业汇总】\n今天还没有收到老师布置的作业。"
    else:
        parts = [f"【{date} 作业汇总】共 {len(records)} 条"]
        for rec in records:
            r = rec["result"]
            parts.append(f"\n【{r['subject']}】" + (f" 截止: {r['deadline']}" if r["deadline"] else ""))
            parts += [f"  {i}. {x}" for i, x in enumerate(r["items"], 1)]
        body = "\n".join(parts)
    return apply_template(body, cfg)

def render_markdown(r, original="", images=()):
    md = [f"## {r['date']} {r['subject']}", "", "**作业内容:**", ""]
    md += [f"{i}. {x}" for i, x in enumerate(r["items"], 1)] or ["(无)"]
    md += ["", f"**截止时间:** {r['deadline'] or '未注明'}", ""]
    if r["notes"]:
        md += ["**注意事项:**", ""] + [f"- {n}" for n in r["notes"]] + [""]
    for p in images or ():
        md += [f"![附件]({p})", ""]
    if original:
        md += ["<details><summary>原始消息</summary>", "", "```", original, "```", "</details>", ""]
    return "\n".join(md)


# ---------------- 企业微信 markdown ----------------
def render_wecom_markdown(r):
    md = [f"### 作业通知 {r['date']}", f"**科目:** <font color=\"info\">{r['subject']}</font>", "**作业内容:**"]
    md += [f"{i}. {x}" for i, x in enumerate(r["items"], 1)] or ["(无)"]
    md.append(f"**截止时间:** <font color=\"warning\">{r['deadline'] or '未注明'}</font>")
    if r["notes"]:
        md.append("**注意事项:**")
        md += [f"> {n}" for n in r["notes"]]
    if r.get("sender"):
        md.append(f"<font color=\"comment\">来源: {r['sender']}</font>")
    return "\n".join(md)

def compose_message(r, cfg):
    """按推送格式生成最终消息 (模板套在内容外层)."""
    body = render_wecom_markdown(r) if cfg.get("push_format", "markdown") == "markdown" else render_text(r)
    return apply_template(body, cfg, r)
