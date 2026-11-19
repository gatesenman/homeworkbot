"""作业清单: 每条作业条目 = 当天一个待办; 进度 / 月历 / 未完成 / 签字带物 / 周报."""
import datetime as dt, re, sqlite3, threading
from collections import Counter, OrderedDict
from .subjects import split_subjects

SCHEMA = """CREATE TABLE IF NOT EXISTS todo(
 id INTEGER PRIMARY KEY AUTOINCREMENT, hid INTEGER, date TEXT, subject TEXT, text TEXT,
 done INTEGER DEFAULT 0, done_at TEXT, UNIQUE(hid, text))"""
SIGN_RE = re.compile(r"签字|签名|带|携带|上交|交回|回执")
KNOWN = ("语文", "数学", "英语", "物理", "化学", "生物", "历史", "地理", "政治", "道法", "科学", "美术", "音乐", "体育")

def guess_subject(text, fallback):
    m = re.match(r"\s*([\u4e00-\u9fa5]{2,4})[:：]", text or "")
    if m and m.group(1) in KNOWN:
        return m.group(1)
    for k in KNOWN:
        if k in (text or ""):
            return k
    parts = split_subjects(fallback)
    return parts[0] if parts else (fallback or "其他")

class Checklist:
    def __init__(self, path):
        self.path, self.lock = path, threading.Lock()
        with self._c() as c:
            c.execute(SCHEMA)

    def _c(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def add_from_result(self, hid, result):
        items = [i for i in (result.get("items") or []) if str(i).strip()]
        date, subj = result.get("date") or dt.date.today().isoformat(), result.get("subject") or ""
        n = 0
        with self.lock, self._c() as c:
            for it in items:
                cur = c.execute("INSERT OR IGNORE INTO todo(hid,date,subject,text) VALUES(?,?,?,?)",
                                (hid, date, guess_subject(it, subj), str(it).strip()))
                n += cur.rowcount
        return n

    def add(self, date, text, subject="其他", hid=0):
        with self.lock, self._c() as c:
            return c.execute("INSERT OR IGNORE INTO todo(hid,date,subject,text) VALUES(?,?,?,?)",
                             (hid, date, subject, text)).lastrowid

    def by_date(self, date):
        with self._c() as c:
            return [dict(r) for r in c.execute("SELECT * FROM todo WHERE date=? ORDER BY subject, id", (date,))]

    def set_done(self, tid, done=True):
        with self.lock, self._c() as c:
            c.execute("UPDATE todo SET done=?, done_at=? WHERE id=?",
                      (int(done), dt.datetime.now().isoformat(timespec="seconds") if done else None, tid))

    def toggle(self, tid):
        with self._c() as c:
            r = c.execute("SELECT done FROM todo WHERE id=?", (tid,)).fetchone()
        if r is not None:
            self.set_done(tid, not r["done"])
            return not r["done"]

    def progress(self, date):
        rows = self.by_date(date)
        done = sum(r["done"] for r in rows)
        return done, len(rows), (done / len(rows) if rows else 0.0)

    def month_days(self, year, month):
        """{day: (done, total)}"""
        pre = f"{year:04d}-{month:02d}-"
        with self._c() as c:
            rows = c.execute("SELECT date, SUM(done) d, COUNT(*) n FROM todo WHERE date LIKE ? GROUP BY date",
                             (pre + "%",)).fetchall()
        return {int(r["date"][8:10]): (r["d"] or 0, r["n"]) for r in rows}

    def unfinished(self, date):
        return [r for r in self.by_date(date) if not r["done"]]

    def sign_items(self, date):
        return [r for r in self.by_date(date) if SIGN_RE.search(r["text"])]

    def weekly(self, end_date):
        """end_date (含) 往前 7 天统计."""
        end = dt.date.fromisoformat(end_date)
        start = end - dt.timedelta(days=6)
        with self._c() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM todo WHERE date>=? AND date<=?",
                                               (start.isoformat(), end.isoformat()))]
        by = OrderedDict()
        for r in sorted(rows, key=lambda r: r["subject"]):
            d, n = by.get(r["subject"], (0, 0))
            by[r["subject"]] = (d + r["done"], n + 1)
        done = sum(r["done"] for r in rows)
        return {"start": start.isoformat(), "end": end.isoformat(), "total": len(rows), "done": done,
                "rate": done / len(rows) if rows else 0.0, "by_subject": by}

# ---------- 文案 (无 emoji) ----------
def render_unfinished(rows, date, child=""):
    if not rows:
        return ""
    who = f"{child}" if child else "孩子"
    lines = [f"### 作业提醒 {date}", f"{who}还有 <font color=\"warning\">{len(rows)}</font> 项作业未完成:"]
    lines += [f"- [{r['subject']}] {r['text']}" for r in rows]
    return "\n".join(lines)

def render_sign(rows, date):
    if not rows:
        return ""
    return "\n".join([f"### 出门前检查 {date}", "今天记得带上 / 已签字:"] + [f"- {r['text']}" for r in rows])

def render_weekly(w, child=""):
    lines = [f"### 本周作业周报 ({w['start']} ~ {w['end']})",
             f"{child + ' ' if child else ''}共 {w['total']} 项, 完成 {w['done']} 项, 完成率 **{w['rate']:.0%}**", ""]
    for s, (d, n) in w["by_subject"].items():
        lines.append(f"- {s}: {d}/{n} ({(d / n if n else 0):.0%})")
    if not w["total"]:
        lines.append("本周没有记录到作业。")
    return "\n".join(lines)
