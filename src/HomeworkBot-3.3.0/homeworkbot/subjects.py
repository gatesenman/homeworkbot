"""科目颜色标签."""
import re

SUBJECT_COLORS = {
    "语文": "#EF4444", "数学": "#3B82F6", "英语": "#8B5CF6", "物理": "#06B6D4",
    "化学": "#F59E0B", "生物": "#22C55E", "历史": "#A855F7", "地理": "#14B8A6",
    "政治": "#EC4899", "道法": "#EC4899", "道德与法治": "#EC4899",
    "体育": "#84CC16", "音乐": "#F97316", "美术": "#E11D48", "科学": "#0EA5E9",
    "信息": "#6366F1", "信息技术": "#6366F1", "综合": "#64748B",
}
DEFAULT_COLOR = "#64748B"

def split_subjects(subject):
    return [s for s in re.split(r"[,，、/;；\s]+", subject or "") if s]

def subject_color(name):
    name = (name or "").strip()
    if name in SUBJECT_COLORS:
        return SUBJECT_COLORS[name]
    for k, c in SUBJECT_COLORS.items():
        if k in name or name in k:
            return c
    return DEFAULT_COLOR

def subject_tags(subject):
    """[(名称, 颜色), ...]"""
    parts = split_subjects(subject)
    if not parts:
        return [("作业", DEFAULT_COLOR)]
    return [(p, subject_color(p)) for p in parts]
