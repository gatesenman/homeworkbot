"""作业历史 (SQLite), 支持按日期/科目/关键词检索, 记录发送状态."""
import datetime as dt, json, os, sqlite3, threading

SCHEMA = """CREATE TABLE IF NOT EXISTS homework(
 id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, date TEXT, subject TEXT, sender TEXT, grp TEXT,
 original TEXT, result TEXT, message TEXT, images TEXT, file TEXT,
 status TEXT DEFAULT 'pending', sent INTEGER DEFAULT 0, sent_at TEXT, error TEXT)"""

class History:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        d = os.path.dirname(path)
        if d: os.makedirs(d, exist_ok=True)
        with self._conn() as c:
            c.execute(SCHEMA)

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def add(self, result, message, sender="", group="", original="", images=(), file="", status="pending"):
        with self.lock, self._conn() as c:
            cur = c.execute("INSERT INTO homework(created,date,subject,sender,grp,original,result,message,images,file,status)"
                            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (dt.datetime.now().isoformat(timespec="seconds"), result["date"], result["subject"],
                             sender, group, original, json.dumps(result, ensure_ascii=False), message,
                             json.dumps(list(images), ensure_ascii=False), file, status))
            return cur.lastrowid

    def _row(self, r):
        d = dict(r)
        d["result"] = json.loads(d["result"])
        raw = json.loads(d["images"] or "[]")
        atts = []
        for x in raw:
            if isinstance(x, str):
                atts.append({"kind": "image", "path": x, "name": os.path.basename(x), "size": 0, "send": True})
            else:
                x.setdefault("send", True); x.setdefault("kind", "image"); atts.append(x)
        d["attachments"] = atts
        d["images"] = [a["path"] for a in atts if a.get("kind") == "image" and a.get("path")]
        d["group"] = d.pop("grp"); d["sent"] = bool(d["sent"])
        return d

    def get(self, id_):
        with self._conn() as c:
            r = c.execute("SELECT * FROM homework WHERE id=?", (id_,)).fetchone()
        return self._row(r) if r else None

    def update_message(self, id_, message):
        with self.lock, self._conn() as c:
            c.execute("UPDATE homework SET message=? WHERE id=?", (message, id_))

    def mark(self, id_, status, error=""):
        sent = status == "sent"
        with self.lock, self._conn() as c:
            c.execute("UPDATE homework SET status=?, sent=MAX(sent,?), sent_at=CASE WHEN ? THEN ? ELSE sent_at END, error=? WHERE id=?",
                      (status, int(sent), int(sent), dt.datetime.now().isoformat(timespec="seconds"), error, id_))

    def search(self, date_from="", date_to="", subject="", keyword="", status="", limit=500):
        q, a = "SELECT * FROM homework WHERE 1=1", []
        if date_from: q += " AND date>=?"; a.append(date_from)
        if date_to: q += " AND date<=?"; a.append(date_to)
        if subject: q += " AND subject LIKE ?"; a.append(f"%{subject}%")
        if keyword: q += " AND (original LIKE ? OR message LIKE ? OR result LIKE ?)"; a += [f"%{keyword}%"] * 3
        if status: q += " AND status=?"; a.append(status)
        q += " ORDER BY date DESC, id DESC LIMIT ?"; a.append(limit)
        with self._conn() as c:
            return [self._row(r) for r in c.execute(q, a).fetchall()]

    def by_date(self, date):
        return list(reversed(self.search(date, date)))

    def pending(self):
        return self.search(status="pending")

    def stats(self, date):
        today = self.by_date(date)
        with self._conn() as c:
            total = c.execute("SELECT COUNT(*) FROM homework").fetchone()[0]
        return {"today": len(today), "today_sent": sum(r["sent"] for r in today),
                "pending": len(self.pending()), "total": total}
