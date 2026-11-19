"""v3.3: 清单 / 提醒 / 周报 / NapCat 管理."""
import datetime as dt, os
from homeworkbot import __version__
from homeworkbot.checklist import Checklist, guess_subject, render_unfinished, render_weekly, render_sign
from homeworkbot.reminders import Reminders
from homeworkbot.napcat import NapCatManager, find_launcher
from homeworkbot.config import DEFAULTS
from homeworkbot.worker import Engine
from homeworkbot.history import History

D = "2026-10-18"  # 周日

def mk(tmp_path):
    cl = Checklist(str(tmp_path / "h.db"))
    cl.add_from_result(1, {"date": D, "subject": "语文、数学",
                           "items": ["语文：抄写生字", "数学：口算本第12页", "试卷请家长签字明天带回"]})
    return cl

def test_version():
    assert __version__ == "3.3.0"

def test_checklist_basic(tmp_path):
    cl = mk(tmp_path)
    rows = cl.by_date(D)
    assert len(rows) == 3 and {r["subject"] for r in rows} >= {"语文", "数学"}
    assert cl.add_from_result(1, {"date": D, "subject": "语文", "items": ["语文：抄写生字"]}) == 0  # 去重
    cl.toggle(rows[0]["id"])
    assert cl.progress(D)[:2] == (1, 3)
    assert cl.month_days(2026, 10) == {18: (1, 3)}
    assert len(cl.unfinished(D)) == 2 and len(cl.sign_items(D)) == 1

def test_guess_subject():
    assert guess_subject("英语：背单词", "语文") == "英语"
    assert guess_subject("背诵古诗", "语文、数学") == "语文"

def test_weekly(tmp_path):
    cl = mk(tmp_path)
    cl.set_done(cl.by_date(D)[0]["id"])
    w = cl.weekly(D)
    assert w["total"] == 3 and w["done"] == 1
    txt = render_weekly(w, "小明")
    assert "33%" in txt and "语文" in txt

def test_renders_empty():
    assert render_unfinished([], D) == "" and render_sign([], D) == ""

class Clock:
    def __init__(self, t): self.t = t
    def __call__(self): return self.t

def test_reminders(tmp_path):
    cl = mk(tmp_path)
    sent, notes = [], []
    clock = Clock(dt.datetime(2026, 10, 18, 19, 0))
    cfg = dict(DEFAULTS, morning_reminder=True)
    r = Reminders(cfg, cl, sent.append, notify=lambda t, m: notes.append(t), log=lambda s: None, now=clock)
    assert r.check() == [] or all(k != "evening" for k, _ in r.check())
    clock.t = dt.datetime(2026, 10, 18, 20, 1)
    kinds = [k for k, _ in r.check()]
    assert "evening" in kinds and "未完成" in sent[0]
    assert r.check() == []   # 当天不重复
    clock.t = dt.datetime(2026, 10, 18, 20, 31)
    assert [k for k, _ in r.check()] == ["weekly"] and "周报" in sent[-1]
    clock.t = dt.datetime(2026, 10, 19, 7, 5)
    assert [k for k, _ in r.check()] == ["morning"] and "签字" in sent[-1]
    assert notes

def test_reminder_no_backfill(tmp_path):
    cl = mk(tmp_path); sent = []
    r = Reminders(dict(DEFAULTS), cl, sent.append, log=lambda s: None, now=Clock(dt.datetime(2026, 10, 18, 22, 0)))
    assert r.check() == [] and not sent

def test_engine_writes_checklist(tmp_path):
    h = History(str(tmp_path / "h.db")); cl = Checklist(str(tmp_path / "h.db"))
    cfg = dict(DEFAULTS, teachers=["王老师"], save_dir=str(tmp_path / "out"), send_mode="preview")
    eng = Engine(cfg, h, log=lambda s: None, seen_path=str(tmp_path / "s.json"), checklist=cl,
                 formatter=lambda t, s: {"date": D, "subject": "数学", "items": ["口算本第3页"], "deadline": "", "notes": []})
    ev = {"post_type": "message", "message_type": "group", "group_id": 1, "user_id": 2, "message_id": 9,
          "sender": {"nickname": "王老师", "card": "王老师"}, "message": [{"type": "text", "data": {"text": "今天作业：口算本第3页"}}]}
    assert eng.handle_event(ev)
    assert [r["text"] for r in cl.by_date(D)] == ["口算本第3页"]

class FakeProc:
    n = 0
    def __init__(self, *a, **k):
        FakeProc.n += 1; self.pid = 100 + FakeProc.n; self.code = None; self.stdout = None
    def poll(self): return self.code
    def terminate(self): self.code = 0

def test_find_launcher(tmp_path):
    assert find_launcher(str(tmp_path)) is None
    sub = tmp_path / "NapCat.44.Shell"; sub.mkdir(); (sub / "napcat.bat").write_text("@echo off")
    assert find_launcher(str(tmp_path)).endswith("napcat.bat")

def test_napcat_watchdog(tmp_path):
    sub = tmp_path / "nc"; sub.mkdir(); (sub / "napcat.bat").write_text("x")
    m = NapCatManager(str(sub), log=lambda s: None, popen=FakeProc, max_restarts=2)
    assert m.start(watchdog=False) and m.running and m.state == "running"
    assert not m.check_once()           # 运行中不重启
    m.proc.code = 1
    assert m.check_once() and m.restarts == 1 and m.running
    m.proc.code = 1; assert m.check_once()
    m.proc.code = 1; assert not m.check_once() and m.state == "crashed"

def test_napcat_missing(tmp_path):
    m = NapCatManager(str(tmp_path), log=lambda s: None, popen=FakeProc)
    assert not m.start(watchdog=False) and m.state == "missing"
