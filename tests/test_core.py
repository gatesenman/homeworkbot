"""格式整理 / 存储 / 历史 / 配置 测试."""
import datetime as dt, json, os
import pytest
from homeworkbot.formatter import (rule_based, extract_json, format_homework, render_text, render_markdown,
                                   apply_template, render_daily_summary, with_retry, build_messages,
                                   render_wecom_markdown, compose_message)
from homeworkbot.storage import save_result, export_records
from homeworkbot.config import (DEFAULTS, load_config, save_config, split_names, parse_group_ids,
                                parse_webhooks, resource_dir)
from homeworkbot.history import History

NOSLEEP = lambda s: None
TEXT = "今日作业：\n1. 语文：抄写第5课生字两遍\n2. 数学：口算本第12页\n请家长签字，明天早上交"

def test_rule_based():
    r = rule_based(TEXT, "2026-10-14")
    assert "语文" in r["subject"] and "数学" in r["subject"]
    assert any("口算" in i for i in r["items"]) and r["notes"] and "明天" in r["deadline"]

def test_intro_line_not_note():
    r = rule_based("各位家长好，今天作业：\n1.语文：抄写生字\n请家长检查签字，明天早上交给组长。", "2026-10-15")
    assert r["items"] == ["语文：抄写生字"] and r["notes"] == ["请家长检查签字，明天早上交给组长。"]

def test_extract_json():
    assert extract_json('```json\n{"a":1}\n```') == {"a": 1}

def test_custom_prompt():
    assert build_messages("x", "y", "d", "自定义")[0]["content"] == "自定义"

class FakeResp:
    def __init__(self, c): self.c = c
    def raise_for_status(self): pass
    def json(self): return {"choices": [{"message": {"content": self.c}}]}

class FakeSession:
    def __init__(self, *contents): self.contents, self.calls = list(contents), []
    def post(self, url, **kw):
        self.calls.append((url, kw))
        c = self.contents.pop(0) if len(self.contents) > 1 else self.contents[0]
        if isinstance(c, Exception): raise c
        return FakeResp(c)

GOOD = json.dumps({"date": "2026-10-14", "subject": "数学", "items": ["口算本第12页"],
                   "deadline": "明早", "notes": ["家长签字"]}, ensure_ascii=False)

def test_llm_and_render():
    sess = FakeSession(GOOD)
    r = format_homework("x", "王老师", dict(DEFAULTS, api_key="k", llm_prompt="P"), "2026-10-14", session=sess, sleep=NOSLEEP)
    assert sess.calls[0][0].endswith("/chat/completions") and sess.calls[0][1]["json"]["messages"][0]["content"] == "P"
    assert "1. 口算本第12页" in render_text(r)
    assert "## 2026-10-14 数学" in render_markdown(r, images=["attachments/x.png"])

def test_llm_retry_then_success():
    sess = FakeSession(ConnectionError("net"), GOOD)
    r = format_homework("x", "t", dict(DEFAULTS, api_key="k"), "2026-10-14", log=NOSLEEP, session=sess, sleep=NOSLEEP)
    assert r["subject"] == "数学" and len(sess.calls) == 2

def test_llm_failure_fallback():
    sess = FakeSession("oops")
    r = format_homework("语文作业：背诵古诗", "t", dict(DEFAULTS, api_key="k", max_retries=2), "2026-10-14",
                        log=NOSLEEP, session=sess, sleep=NOSLEEP)
    assert r["subject"] == "语文" and len(sess.calls) == 2

def test_with_retry_raises():
    n = []
    with pytest.raises(ValueError):
        with_retry(lambda: n.append(1) or (_ for _ in ()).throw(ValueError("x")), 3, log=NOSLEEP, sleep=NOSLEEP)
    assert len(n) == 3

def test_template_and_wecom_markdown():
    cfg = dict(DEFAULTS, child_name="小明", greeting="大家好")
    assert apply_template("CONTENT", cfg).startswith("大家好") and "小明" in apply_template("CONTENT", cfg)
    assert apply_template("x", dict(cfg, message_template="{content}|{oops}")) == "x|{oops}"
    r = rule_based(TEXT, "2026-10-14")
    md = render_wecom_markdown(r)
    assert md.startswith("### 作业通知") and '<font color="warning">' in md and "> 请家长签字" in md
    assert "### 作业通知" in compose_message(r, cfg)
    assert "【作业通知】" in compose_message(r, dict(cfg, push_format="text"))

def test_no_emoji_in_messages():
    import re
    r = rule_based(TEXT, "2026-10-14")
    out = compose_message(r, DEFAULTS) + render_daily_summary([{"result": r}], "2026-10-14", DEFAULTS)
    assert not re.search("[\U0001F300-\U0001FAFF]", out)

def test_daily_summary():
    r = rule_based("数学作业：练习册P3", "2026-10-14")
    s = render_daily_summary([{"result": r}], "2026-10-14", dict(DEFAULTS, message_template="{content}"))
    assert "共 1 条" in s and "练习册P3" in s
    assert "还没有" in render_daily_summary([], "2026-10-14", dict(DEFAULTS, message_template="{content}"))

def test_save_with_attachment(tmp_path):
    img = tmp_path / "a.png"; img.write_bytes(b"x")
    r = rule_based("数学作业：练习册P3", "2026-10-14")
    p, rel = save_result(r, str(tmp_path / "out"), "md", "原文", [str(img)]); save_result(r, str(tmp_path / "out"), "md")
    txt = open(p, encoding="utf-8").read()
    assert p.endswith("2026-10-14.md") and txt.count("## ") == 2 and rel[0] in txt
    assert os.path.exists(os.path.join(tmp_path, "out", rel[0]))

def test_history(tmp_path):
    h = History(str(tmp_path / "h.db"))
    a = h.add(rule_based("数学作业：练习册P3", "2026-10-14"), "msgA", "王老师", "123", "orig")
    b = h.add(rule_based("语文作业：背诵", "2026-10-15"), "msgB", "李老师", "456")
    assert len(h.search(subject="数学")) == 1 and len(h.search(date_from="2026-10-15")) == 1
    assert len(h.search(keyword="练习册")) == 1
    h.mark(a, "sent"); h.mark(b, "failed", "err")
    assert h.get(a)["sent"] and h.get(b)["error"] == "err" and len(h.pending()) == 0
    h.update_message(b, "new"); assert h.get(b)["message"] == "new"
    assert h.stats("2026-10-14") == {"today": 1, "today_sent": 1, "pending": 0, "total": 2}

def test_export(tmp_path):
    h = History(str(tmp_path / "h.db")); h.add(rule_based("数学作业：练习册P3", "2026-10-14"), "m", "王老师", "G")
    for ext in ("md", "csv", "txt"):
        p = export_records(h.search(), str(tmp_path / f"e.{ext}"))
        assert "练习册P3" in open(p, encoding="utf-8-sig").read()

def test_config_migration(tmp_path):
    p = str(tmp_path / "c.json")
    with open(p, "w", encoding="utf-8") as f:   # v2 配置: 旧字段丢弃, 通用字段保留
        json.dump({"qq_groups": ["三年二班"], "wechat_group": "家长群", "teachers": "王老师，李老师",
                   "poll_interval": 30, "child_name": "小明", "send_mode": "preview"}, f, ensure_ascii=False)
    c = load_config(p)
    assert c["teachers"] == ["王老师", "李老师"] and c["child_name"] == "小明"
    assert "qq_groups" not in c and "wechat_group" not in c and c["onebot_mode"] == "reverse_ws"
    save_config(c, p); assert load_config(p)["child_name"] == "小明"
    assert split_names("a、b\nc") == ["a", "b", "c"]

def test_parse_group_ids_and_webhooks():
    assert parse_group_ids("123456, 789\n群:555 123456") == [123456, 789, 555]
    hooks = parse_webhooks(["家庭群|https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=a",
                            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=b", "垃圾行"])
    assert hooks[0][0] == "家庭群" and hooks[1][0] == "机器人2" and len(hooks) == 2

def test_resource_dir_frozen(monkeypatch):
    import sys
    assert os.path.exists(os.path.join(resource_dir(), "assets", "icon.png"))
    monkeypatch.setattr(sys, "_MEIPASS", "/x/_internal", raising=False)
    assert resource_dir() == "/x/_internal"

def test_resolve_dir_relative_to_app(tmp_path):
    from homeworkbot.config import resolve_dir, app_dir
    assert resolve_dir("作业记录") == os.path.join(app_dir(), "作业记录")
    assert resolve_dir(str(tmp_path)) == str(tmp_path)
