"""定时提醒: 晚间未完成 / 早晨签字带物 / 周日周报. 纯逻辑, 便于测试."""
import datetime as dt
from .checklist import render_unfinished, render_sign, render_weekly

def _hm(s, default):
    try:
        h, m = map(int, str(s).split(":")); return h, m
    except ValueError:
        return default

class Reminders:
    def __init__(self, cfg, checklist, send, notify=lambda t, m: None, log=print, now=dt.datetime.now):
        self.cfg, self.cl, self.send, self.notify, self.log, self.now = cfg, checklist, send, notify, log, now
        self.done = {}
        n = now()
        # 启动时已过的时间点当天不补发
        for key, tkey, dflt in (("evening", "evening_reminder_time", (20, 0)),
                                ("morning", "morning_reminder_time", (7, 0)),
                                ("weekly", "weekly_report_time", (20, 30))):
            if (n.hour, n.minute) >= _hm(cfg.get(tkey), dflt):
                self.done[key] = n.date().isoformat()

    def _due(self, key, tkey, dflt):
        n = self.now(); today = n.date().isoformat()
        if self.done.get(key) == today or (n.hour, n.minute) < _hm(self.cfg.get(tkey), dflt):
            return None
        self.done[key] = today
        return n

    def check(self):
        fired = []
        child = self.cfg.get("child_name", "")
        if self.cfg.get("evening_reminder", True) and self._due("evening", "evening_reminder_time", (20, 0)):
            d = self.now().date().isoformat()
            rows = self.cl.unfinished(d)
            if rows:
                text = render_unfinished(rows, d, child)
                self.notify("作业还没做完", f"还有 {len(rows)} 项未完成")
                if self.cfg.get("evening_push", True):
                    self._send(text, "晚间提醒")
                fired.append(("evening", text))
        if self.cfg.get("morning_reminder", False) and self._due("morning", "morning_reminder_time", (7, 0)):
            # 早上检查昨天和今天布置的签字/带物
            n = self.now().date()
            rows = self.cl.sign_items((n - dt.timedelta(days=1)).isoformat()) + self.cl.sign_items(n.isoformat())
            if rows:
                text = render_sign(rows, n.isoformat())
                self.notify("出门前检查", f"{len(rows)} 项需签字/带上")
                self._send(text, "早晨提醒")
                fired.append(("morning", text))
        if self.cfg.get("weekly_report", True) and self.now().weekday() == 6 \
                and self._due("weekly", "weekly_report_time", (20, 30)):
            text = render_weekly(self.cl.weekly(self.now().date().isoformat()), child)
            self._send(text, "周报")
            fired.append(("weekly", text))
        return fired

    def _send(self, text, what):
        try:
            self.send(text); self.log(f"已推送{what}")
        except Exception as e:
            self.log(f"{what}推送失败: {e}"); self.notify(f"{what}推送失败", str(e)[:80])
