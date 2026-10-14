#!/usr/bin/env python3
"""
Builds two animated SVG files for a GitHub profile README:
  - contrib-heatmap.svg : your real contribution calendar (refreshed daily)
  - info-card.svg       : a terminal-style info card (text comes from profile.json)

Standard library only: nothing to install.
"""
import json
import os
import re
import sys
import textwrap
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from xml.sax.saxutils import escape

USER = os.environ.get("GH_USER", "safwanov")
ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data" / "contributions.json"
HEATMAP_FILE = ROOT / "contrib-heatmap.svg"
CARD_FILE = ROOT / "info-card.svg"
PROFILE_FILE = ROOT / "profile.json"

FONT = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"
BG = "#0d1117"
BORDER = "#30363d"
TEXT = "#c9d1d9"
MUTED = "#8b949e"
PALETTE = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353", "#69f0a0"]
KEY_COLORS = ["#7ee787", "#79c0ff", "#d2a8ff", "#ffa657", "#ff7b72"]


# --------------------------------------------------------------------------
# 1. Get the contribution calendar (public HTML page, no token needed)
# --------------------------------------------------------------------------
class CalendarParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cells = {}
        self.tips = {}
        self._tip_for = None
        self._tip_text = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("data-date"):
            key = a.get("id") or a["data-date"]
            try:
                level = int(a.get("data-level", 0))
            except ValueError:
                level = 0
            count = None
            if a.get("data-count", "").isdigit():
                count = int(a["data-count"])
            self.cells[key] = {"date": a["data-date"], "level": level, "count": count}
        elif tag == "tool-tip" and a.get("for"):
            self._tip_for = a["for"]
            self._tip_text = []

    def handle_data(self, data):
        if self._tip_for:
            self._tip_text.append(data)

    def handle_endtag(self, tag):
        if tag == "tool-tip" and self._tip_for:
            self.tips[self._tip_for] = "".join(self._tip_text).strip()
            self._tip_for = None


def parse_calendar(html):
    p = CalendarParser()
    p.feed(html)
    days = []
    for key, cell in p.cells.items():
        tip = p.tips.get(key, "")
        if cell["count"] is None and tip:
            if tip.lower().startswith("no contribution"):
                cell["count"] = 0
            else:
                m = re.match(r"\s*([\d,]+)\s+contribution", tip)
                if m:
                    cell["count"] = int(m.group(1).replace(",", ""))
        days.append(cell)
    days.sort(key=lambda d: d["date"])
    return days


def get_days():
    fixture = os.environ.get("CALENDAR_HTML_FILE")  # only used for local tests
    try:
        if fixture:
            html = Path(fixture).read_text(encoding="utf-8")
        else:
            url = f"https://github.com/users/{USER}/contributions"
            req = urllib.request.Request(url, headers={"User-Agent": "profile-readme-builder"})
            with urllib.request.urlopen(req, timeout=30) as r:
                html = r.read().decode("utf-8")
        days = parse_calendar(html)
        if not days:
            raise RuntimeError("no calendar cells found in the page")
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(json.dumps(days, indent=1), encoding="utf-8")
        return days
    except Exception as exc:  # keep the last good data if GitHub is unreachable
        print(f"WARNING: could not fetch contributions: {exc}", file=sys.stderr)
        if DATA_FILE.exists():
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        return None


# --------------------------------------------------------------------------
# 2. Stats
# --------------------------------------------------------------------------
def compute_stats(days):
    has_counts = any(d["count"] is not None for d in days)
    active = [((d["count"] or 0) > 0) if has_counts else d["level"] > 0 for d in days]
    longest = run = 0
    for a in active:
        run = run + 1 if a else 0
        longest = max(longest, run)
    cur, i = 0, len(days) - 1
    if i >= 0 and not active[i]:  # today may not have activity yet
        i -= 1
    while i >= 0 and active[i]:
        cur += 1
        i -= 1
    total = sum(d["count"] or 0 for d in days) if has_counts else None
    max_count = max((d["count"] or 0 for d in days), default=0) if has_counts else 0
    return {
        "total": total,
        "active_days": sum(active),
        "current": cur,
        "longest": longest,
        "max_count": max_count,
    }


# --------------------------------------------------------------------------
# 3. Heatmap SVG
# --------------------------------------------------------------------------
def render_heatmap(days, st):
    W, PITCH, CELL, LEFT, TOP = 860, 15, 12, 34, 50
    first = date.fromisoformat(days[0]["date"])
    offset = (first.weekday() + 1) % 7  # GitHub weeks start on Sunday
    weeks = (offset + len(days) - 1) // 7 + 1
    H = TOP + 7 * PITCH + 58

    rects, labels = [], []
    last_month, last_label_week = None, -10
    for i, d in enumerate(days):
        w, r = divmod(offset + i, 7)
        dt = date.fromisoformat(d["date"])
        if (r == 0 or i == 0) and dt.month != last_month:
            if w - last_label_week >= 3:
                labels.append(
                    f'<text x="{LEFT + w * PITCH}" y="{TOP - 10}" fill="{MUTED}" '
                    f'font-size="10">{dt.strftime("%b")}</text>'
                )
                last_label_week = w
            last_month = dt.month
        lvl = min(d["level"], 4)
        if lvl == 4 and st["max_count"] and (d["count"] or 0) >= st["max_count"] * 0.75:
            lvl = 5
        delay = (w + r) * 0.015
        rects.append(
            f'<rect class="c" x="{LEFT + w * PITCH}" y="{TOP + r * PITCH}" '
            f'width="{CELL}" height="{CELL}" rx="3" fill="{PALETTE[lvl]}" '
            f'style="animation-delay:{delay:.3f}s"/>'
        )

    day_labels = "".join(
        f'<text x="{LEFT - 8}" y="{TOP + r * PITCH + 10}" fill="{MUTED}" font-size="10" '
        f'text-anchor="end">{name}</text>'
        for r, name in ((1, "Mon"), (3, "Wed"), (5, "Fri"))
    )

    if st["total"] is not None:
        summary = f'{st["total"]:,} contributions in the last year'
    else:
        summary = f'{st["active_days"]} active days in the last year'
    summary += f' · current streak {st["current"]}d · longest {st["longest"]}d'

    fy = TOP + 7 * PITCH + 26
    legend_x = W - LEFT - (6 * 15 + 70)
    legend = f'<text x="{legend_x}" y="{fy}" fill="{MUTED}" font-size="10">Less</text>'
    for n, color in enumerate(PALETTE):
        legend += (
            f'<rect x="{legend_x + 30 + n * 15}" y="{fy - 10}" width="{CELL}" '
            f'height="{CELL}" rx="3" fill="{color}"/>'
        )
    legend += f'<text x="{legend_x + 30 + 6 * 15 + 4}" y="{fy}" fill="{MUTED}" font-size="10">More</text>'

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}">
<style>
.c{{animation:pop .45s ease-out both}}
@keyframes pop{{from{{opacity:0;transform:translateY(-8px)}}to{{opacity:1;transform:translateY(0)}}}}
</style>
<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="10" fill="{BG}" stroke="{BORDER}"/>
<text x="{LEFT}" y="26" fill="{TEXT}" font-size="13">{escape(USER)}@github ~ $ ./contributions.sh</text>
{"".join(labels)}
{day_labels}
{"".join(rects)}
<text x="{LEFT}" y="{fy}" fill="{TEXT}" font-size="11">{escape(summary)}</text>
{legend}
</svg>
"""


# --------------------------------------------------------------------------
# 4. Info card SVG (text comes from profile.json)
# --------------------------------------------------------------------------
def render_card():
    profile = {}
    if PROFILE_FILE.exists():
        profile = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    title = profile.get("title", f"{USER}@github: ~")
    rows = profile.get("rows", [])

    W, PAD, LINE, HEAD = 490, 24, 22, 40
    CHAR = 7.8
    key_w = max([len(k) for k, _ in rows] + [4]) + 2
    val_x = PAD + key_w * CHAR
    wrap_at = max(20, int((W - PAD - val_x) / CHAR))

    body, y, n = [], HEAD + 30, 0
    for ki, (key, value) in enumerate(rows):
        color = KEY_COLORS[ki % len(KEY_COLORS)]
        lines = textwrap.wrap(str(value), wrap_at) or [""]
        for li, text in enumerate(lines):
            delay = 0.25 + n * 0.18
            k = f'<text x="{PAD}" y="{y}" fill="{color}" font-weight="bold">{escape(key)}</text>' if li == 0 else ""
            body.append(
                f'<g class="l" style="animation-delay:{delay:.2f}s">{k}'
                f'<text x="{val_x:.1f}" y="{y}" fill="{TEXT}">{escape(text)}</text></g>'
            )
            y += LINE
            n += 1
    H = y + 14

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}" font-size="13">
<style>
.l{{animation:in .5s ease-out both}}
@keyframes in{{from{{opacity:0;transform:translateX(-8px)}}to{{opacity:1;transform:translateX(0)}}}}
</style>
<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="10" fill="{BG}" stroke="{BORDER}"/>
<circle cx="22" cy="20" r="6" fill="#ff5f56"/><circle cx="42" cy="20" r="6" fill="#ffbd2e"/><circle cx="62" cy="20" r="6" fill="#27c93f"/>
<text x="{W / 2}" y="24" fill="{MUTED}" font-size="12" text-anchor="middle">{escape(title)}</text>
<line x1="0" y1="{HEAD}" x2="{W}" y2="{HEAD}" stroke="{BORDER}"/>
{"".join(body)}
</svg>
"""


def main():
    CARD_FILE.write_text(render_card(), encoding="utf-8")
    print(f"wrote {CARD_FILE.name}")
    days = get_days()
    if not days:
        sys.exit("ERROR: no contribution data available, heatmap not built")
    HEATMAP_FILE.write_text(render_heatmap(days, compute_stats(days)), encoding="utf-8")
    print(f"wrote {HEATMAP_FILE.name} ({len(days)} days)")


if __name__ == "__main__":
    main()
