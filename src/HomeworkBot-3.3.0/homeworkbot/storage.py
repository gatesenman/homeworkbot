"""按日期保存 Markdown/TXT. 附件统一存 attachments/<date>/."""
import datetime as dt, os, shutil
from .formatter import render_markdown, render_text

def _date(r):
    d = r.get("date", "")
    try: dt.date.fromisoformat(d); return d
    except ValueError: return dt.date.today().isoformat()

def _src_of(item):
    if isinstance(item, str): return item, os.path.basename(item)
    if hasattr(item, "path"): return item.path, item.name or os.path.basename(item.path or "")
    return item.get("path") or "", item.get("name") or os.path.basename(item.get("path") or "")

def save_attachments(items, folder, date):
    out = []
    if not items: return out
    d = os.path.join(folder, "attachments", date); os.makedirs(d, exist_ok=True)
    for i, item in enumerate(items, 1):
        src, name = _src_of(item)
        if not src or not os.path.exists(src):
            out.append(""); continue
        ext = os.path.splitext(name or src)[1] or os.path.splitext(src)[1] or ".bin"
        safe = "".join(c if c.isalnum() or c in "._-()[] " else "_" for c in (name or f"att{i}"))[:60]
        if not safe.endswith(ext): safe += ext
        dest_name = f"{dt.datetime.now():%H%M%S}_{i}_{safe}"
        shutil.copy2(src, os.path.join(d, dest_name))
        out.append(f"attachments/{date}/{dest_name}")
    return out

def save_result(r, folder, fmt="md", original="", images=()):
    os.makedirs(folder, exist_ok=True)
    date = _date(r)
    rel = [p for p in save_attachments(images, folder, date) if p]
    path = os.path.join(folder, f"{date}.{'md' if fmt == 'md' else 'txt'}")
    if fmt == "md":
        body = render_markdown(r, original, rel)
    else:
        body = render_text(r) + ("\n附件: " + ", ".join(rel) if rel else "") + "\n\n原文:\n" + original
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if new and fmt == "md": f.write(f"# 作业记录 {date}\n\n")
        elif not new: f.write("\n---\n\n")
        f.write(body + "\n")
    return path, rel

def export_records(records, path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        import csv
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["日期", "科目", "作业内容", "截止时间", "注意事项", "老师", "QQ群", "已发送", "附件数"])
            for rec in records:
                r = rec["result"]
                n = len(rec.get("attachments") or rec.get("images") or [])
                w.writerow([r["date"], r["subject"], "\n".join(r["items"]), r["deadline"],
                            "\n".join(r["notes"]), rec["sender"], rec["group"], "是" if rec["sent"] else "否", n])
    else:
        with open(path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write((render_markdown(rec["result"]) if ext == ".md" else render_text(rec["result"])) + "\n\n")
    return path
