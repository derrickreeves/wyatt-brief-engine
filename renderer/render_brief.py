# -*- coding: utf-8 -*-
"""Wyatt Portfolio Daily Brief renderer, v7 division template.

Data-driven: reads a JSON payload and renders the combined printable PDF.
The agent (nightly shift or interactive session) pulls live numbers per the
wyatt-daily-brief SOP, writes the JSON, then runs:

    python3 render_brief.py brief-data.json out.pdf

The script never fetches data and holds no credentials. Layout is the locked
v7 template extracted from build_coworking_v1.py and the approved KCM v7 /
Ascend v5-final PDFs (2026-08-08). Do not restyle without Derrick's directive.

JSON shape (all colors are token strings: ink muted light green amber black):

{
  "as_of_line": "As of Sunday, August 10, 2026  ·  Yest 8/10  ·  ...",
  "as_of_short": "Aug 10, 2026",
  "brief_foot": "footer line used on the cover page",
  "cover": {
    "title": "Wyatt Portfolio Daily Brief",
    "health": "portfolio-level italic paragraph",
    "included": [["Division title", "one-line status"], ...],
    "coming": ["Division names not yet in the brief", ...],
    "note": "optional small-print line"
  },
  "divisions": [
    {
      "title": "Kaizen Construction Management",
      "foot": "sources footer line for this division's pages",
      "health": "italic health paragraph",
      "blocks": [
        {"kind": "section", "title": "PORTFOLIO SNAPSHOT", "sub": "optional"},
        {"kind": "cards", "items": [[label, value, sub, color] x4, ...]},
        {"kind": "table", "cols": [...], "widths": [...], "rows": [[cell,...]],
         "note": "optional", "left_cols": 2},
        {"kind": "flags", "items": [[title, body], ...]},
        {"kind": "prose", "text": "...", "size": 8.5}
      ]
    }
  ]
}

A table cell is either a string or [text, color, bold].
"""
import json
import sys

from reportlab.pdfgen import canvas
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.utils import simpleSplit

W, H = 612, 792
L, R = 54, 558
TOP = H - 54
BOTTOM = 78  # content floor; footer sits below

COLORS = {
    "ink":   Color(0.102, 0.102, 0.18),
    "muted": Color(0.42, 0.447, 0.502),
    "light": Color(0.612, 0.639, 0.686),
    "green": Color(0.082, 0.502, 0.239),
    "amber": HexColor("#B45309"),
    "black": Color(0, 0, 0),
}
STRIPE = Color(0.953, 0.957, 0.965)
RULE = Color(0.878, 0.894, 0.918)

INK, MUTED, LIGHT = COLORS["ink"], COLORS["muted"], COLORS["light"]


def color(tok, default=INK):
    return COLORS.get(tok, default)


class Doc:
    def __init__(self, path, data):
        self.c = canvas.Canvas(path, pagesize=(W, H))
        self.data = data
        self.y = TOP
        self.page = 1
        self.foot = data.get("brief_foot", "")
        self.foot_label = "Wyatt Portfolio Daily Brief"

    # ---------- page plumbing ----------
    def footer(self):
        c = self.c
        c.setFont("Helvetica", 6.8)
        c.setFillColor(LIGHT)
        for i, ln in enumerate(simpleSplit(self.foot, "Helvetica", 6.8, R - L)):
            c.drawString(L, 52 - i * 8, ln)
        c.setFont("Helvetica", 6.8)
        c.setFillColor(LIGHT)
        c.drawString(L, 32, "%s  ·  As of %s" % (self.foot_label, self.data.get("as_of_short", "")))
        c.drawRightString(R, 32, "Page %d" % self.page)

    def new_page(self):
        self.footer()
        self.c.showPage()
        self.page += 1
        self.y = TOP

    def need(self, h):
        if self.y - h < BOTTOM:
            self.new_page()

    # ---------- v7 primitives ----------
    def title_block(self, title):
        c = self.c
        c.setFont("Helvetica", 7)
        c.setFillColor(LIGHT)
        c.drawString(L, H - 54, "KAIZEN PORTFOLIO  ·  DAILY BRIEF")
        c.setFont("Helvetica-Bold", 22)
        c.setFillColor(INK)
        c.drawString(L, H - 80, title)
        c.setFont("Helvetica", 7.5)
        c.setFillColor(MUTED)
        c.drawString(L, H - 95, self.data.get("as_of_line", ""))
        self.y = H - 118

    def health(self, text):
        c = self.c
        lines = simpleSplit(text, "Helvetica-Oblique", 9.5, R - L)
        self.need(len(lines) * 12.5)
        c.setFont("Helvetica-Oblique", 9.5)
        c.setFillColor(INK)
        for ln in lines:
            c.drawString(L, self.y, ln)
            self.y -= 12.5

    def section(self, title, sub=None, keep=90):
        # keep the header attached to at least ~2 rows of content; a block may ask for more
        # ("keep": points) so a short detail table is never orphaned across a page break.
        self.need(keep)
        c = self.c
        self.y -= 20
        c.setFont("Helvetica-Bold", 10.5)
        c.setFillColor(INK)
        c.drawString(L, self.y, title)
        self.y -= 3
        c.setStrokeColor(RULE)
        c.setLineWidth(0.8)
        c.line(L, self.y, R, self.y)
        if sub:
            self.y -= 10
            c.setFont("Helvetica", 6.8)
            c.setFillColor(LIGHT)
            c.drawString(L, self.y, sub)
        self.y -= 12

    def cards(self, items):
        c = self.c
        for start in range(0, len(items), 4):
            row = items[start:start + 4]
            self.need(48)
            cw = (R - L) / 4.0
            for i, item in enumerate(row):
                label, val, sub = item[0], item[1], item[2]
                col = color(item[3] if len(item) > 3 else "ink")
                x = L + i * cw
                c.setFont("Helvetica", 7.5)
                c.setFillColor(LIGHT)
                c.drawString(x, self.y, label.upper())
                c.setFont("Helvetica-Bold", 15)
                c.setFillColor(col)
                c.drawString(x, self.y - 18, val)
                c.setFont("Helvetica", 6.8)
                c.setFillColor(MUTED)
                c.drawString(x, self.y - 30, sub)
            self.y -= 44

    def _table_header(self, cols, xs, widths, left_cols):
        c = self.c
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(MUTED)
        for i, h in enumerate(cols):
            if i < left_cols:
                c.drawString(xs[i], self.y, h)
            else:
                c.drawRightString(xs[i] + widths[i] - 4, self.y, h)
        self.y -= 4
        c.setStrokeColor(RULE)
        c.setLineWidth(0.6)
        c.line(L, self.y, R, self.y)
        self.y -= 14

    def table(self, cols, widths, rows, note=None, left_cols=2):
        c = self.c
        xs, acc = [], L
        for w in widths:
            xs.append(acc)
            acc += w
        self.need(40)
        self._table_header(cols, xs, widths, left_cols)
        stripe = False
        LINE = 10  # extra height per wrapped line (left-aligned text cells wrap; numbers never do)
        ROW = 16   # base row height (was 18; tightened 2026-10-15 so fewer tables spill a few rows onto a new page)
        # Widow control: never strand a single row on a new page. Pre-measure the rows and, where a page
        # break would fall right before the last row, break one row earlier so two rows travel together.
        def _h(row):
            m = 1
            for i, cell in enumerate(row):
                if i >= left_cols:
                    continue
                txt = cell[0] if isinstance(cell, (list, tuple)) else cell
                bold = bool(cell[2]) if isinstance(cell, (list, tuple)) and len(cell) > 2 else False
                if txt:
                    m = max(m, len(simpleSplit(str(txt), "Helvetica-Bold" if bold else "Helvetica", 8.5, widths[i] - 2) or [""]))
            return ROW + (m - 1) * LINE
        heights = [_h(r) for r in rows]
        force_break = set()
        y = self.y
        for i, h in enumerate(heights):
            if y - h < BOTTOM:
                if i == len(rows) - 1 and i >= 1 and (i - 1) not in force_break:
                    force_break.add(i - 1)
                    break
                y = TOP - 18  # header below the top edge
            y -= h
        for idx, row in enumerate(rows):
            # unpack cells once so the row height can account for wrapped text in the left columns
            cells = []
            for i, cell in enumerate(row):
                if isinstance(cell, (list, tuple)):
                    txt = cell[0]
                    col = color(cell[1] if len(cell) > 1 else "ink")
                    bold = bool(cell[2]) if len(cell) > 2 else False
                else:
                    txt, col, bold = cell, (INK if i < left_cols else COLORS["black"]), False
                font = "Helvetica-Bold" if bold else "Helvetica"
                if i < left_cols and txt:
                    lines = simpleSplit(str(txt), font, 8.5, widths[i] - 2) or [str(txt)]
                else:
                    lines = [str(txt)]
                cells.append((lines, col, font, i))
            nlines = max(len(cl[0]) for cl in cells) if cells else 1
            rh = ROW + (nlines - 1) * LINE
            if self.y - rh < BOTTOM or idx in force_break:
                self.new_page()
                self._table_header(cols, xs, widths, left_cols)
            if stripe:
                c.setFillColor(STRIPE)
                c.rect(L, self.y - 5 - (rh - ROW), R - L, rh, stroke=0, fill=1)
            stripe = not stripe
            for lines, col, font, i in cells:
                c.setFont(font, 8.5)
                c.setFillColor(col)
                if i < left_cols:
                    for k, ln in enumerate(lines):
                        c.drawString(xs[i], self.y - k * LINE, ln)
                else:
                    c.drawRightString(xs[i] + widths[i] - 4, self.y, lines[0])
            self.y -= rh
        if note:
            self.y -= 2
            lines = simpleSplit(note, "Helvetica", 6.8, R - L)
            self.need(len(lines) * 8)
            c.setFont("Helvetica", 6.8)
            c.setFillColor(MUTED)
            for ln in lines:
                c.drawString(L, self.y, ln)
                self.y -= 8

    def flags(self, items):
        c = self.c
        for item in items:
            title, body = item[0], item[1]
            tcol = color(item[2]) if len(item) > 2 and item[2] else INK
            if isinstance(body, (list, tuple)):
                body_lines = []
                for part in body:
                    body_lines += simpleSplit(part, "Helvetica", 8, R - L - 10)
            else:
                body_lines = simpleSplit(body, "Helvetica", 8, R - L - 10)
            self.need(11 + len(body_lines) * 10 + 8)
            c.setFillColor(tcol)
            c.circle(L + 2.5, self.y + 3, 1.6, stroke=0, fill=1)
            c.setFont("Helvetica-Bold", 8.5)
            c.setFillColor(tcol)
            c.drawString(L + 10, self.y, title)
            self.y -= 11
            c.setFont("Helvetica", 8)
            c.setFillColor(MUTED)
            for ln in body_lines:
                c.drawString(L + 10, self.y, ln)
                self.y -= 10
            self.y -= 5

    def report(self, what, missed, tally, weekend=False, window=""):
        """Who did not file yesterday (amber, bold) and the last-5-business-days tally (muted)."""
        c = self.c
        self.y -= 2
        if weekend:
            head, col = "%s: weekend, no filing expected" % what, MUTED
        elif missed:
            head, col = "Did not report yesterday: %s" % ", ".join(missed), color("amber")
        else:
            head, col = "Everyone reported yesterday", color("green")
        lines = simpleSplit(head, "Helvetica-Bold", 8.5, R - L)
        tl = simpleSplit(("Filed, last 5 business days (%s): " % window if window else "Filed, last 5 business days: ") + tally,
                         "Helvetica", 7, R - L)
        self.need(len(lines) * 11 + len(tl) * 9 + 8)
        c.setFont("Helvetica-Bold", 8.5)
        c.setFillColor(col)
        for ln in lines:
            c.drawString(L, self.y, ln)
            self.y -= 11
        c.setFont("Helvetica", 7)
        c.setFillColor(MUTED)
        for ln in tl:
            c.drawString(L, self.y, ln)
            self.y -= 9
        self.y -= 6

    def prose(self, text, size=8.5, bold=False):
        c = self.c
        self.y -= 6
        font = "Helvetica-Bold" if bold else "Helvetica"
        lines = simpleSplit(text, font, size, R - L)
        self.need(len(lines) * (size + 3))
        c.setFont(font, size)
        c.setFillColor(COLORS["black"])
        for ln in lines:
            c.drawString(L, self.y, ln)
            self.y -= size + 3

    # ---------- assembly ----------
    def cover(self):
        cov = self.data.get("cover")
        if not cov:
            return
        c = self.c
        self.foot_label = "Wyatt Portfolio Daily Brief"
        self.title_block(cov.get("title", "Wyatt Portfolio Daily Brief"))
        if cov.get("health"):
            self.health(cov["health"])
        attention = cov.get("attention") or []
        if attention:
            self.section("WHO TO TALK TO TODAY, AND WHY", "what each person needs to do, and where")
            self.flags([[a[0], a[1], "amber"] for a in attention])
        else:
            self.section("WHO TO TALK TO TODAY, AND WHY", "what each person needs to do, and where")
            c.setFont("Helvetica", 8.5)
            c.setFillColor(color("green"))
            self.need(14)
            c.drawString(L, self.y, "Nobody. Every form was filed and nothing required is blank.")
            self.y -= 14
        how = cov.get("how") or []
        if how:
            self.section("WHERE THE NUMBERS GO", "the places named above · each one feeds this report overnight · keeping them current is the whole job")
            self.flags([[w, h] for w, h in how])
        # IN THIS BRIEF retired 2026-10-15: it repeated the opening paragraph and pushed the cover to two pages.
        included = []
        if included:
            self.section("IN THIS BRIEF", "One card per division, in the locked portfolio order  ·  print-ready")
            for name, line in included:
                self.need(24)
                c.setFont("Helvetica-Bold", 9.5)
                c.setFillColor(INK)
                c.drawString(L, self.y, name)
                self.y -= 11
                c.setFont("Helvetica", 8)
                c.setFillColor(MUTED)
                for ln in simpleSplit(line, "Helvetica", 8, R - L - 10):
                    c.drawString(L + 10, self.y, ln)
                    self.y -= 10
                self.y -= 6
        coming = cov.get("coming") or []
        if coming:
            # one compact line, never its own section (a lone "COMING ONLINE" header spilled onto page 2 on 10/15)
            self.y -= 4
            for ln in simpleSplit("Coming online as their cards are verified: " + "  ·  ".join(coming), "Helvetica", 8, R - L):
                self.need(11)
                c.setFont("Helvetica", 8)
                c.setFillColor(MUTED)
                c.drawString(L, self.y, ln)
                self.y -= 10.5
        if cov.get("note"):
            self.y -= 8
            c.setFont("Helvetica", 6.8)
            c.setFillColor(LIGHT)
            for ln in simpleSplit(cov["note"], "Helvetica", 6.8, R - L):
                self.need(9)
                c.drawString(L, self.y, ln)
                self.y -= 8
        self.new_page()

    def division(self, d):
        self.foot = d.get("foot", self.data.get("brief_foot", ""))
        self.foot_label = d.get("title", "")
        self.title_block(d.get("title", ""))
        if d.get("health"):
            self.health(d["health"])
        for b in d.get("blocks", []):
            kind = b.get("kind")
            if kind == "section":
                self.section(b.get("title", ""), b.get("sub"), float(b.get("keep", 90)))
            elif kind == "cards":
                self.cards(b.get("items", []))
            elif kind == "table":
                self.table(b.get("cols", []), b.get("widths", []), b.get("rows", []),
                           b.get("note"), int(b.get("left_cols", 2)))
            elif kind == "flags":
                self.flags(b.get("items", []))
            elif kind == "report":
                self.report(b.get("what", ""), b.get("missed") or [], b.get("tally", ""), b.get("weekend", False), b.get("window", ""))
            elif kind == "prose":
                self.prose(b.get("text", ""), float(b.get("size", 8.5)), bool(b.get("bold", False)))
            else:
                raise ValueError("unknown block kind: %r" % kind)

    def build(self):
        self.cover()
        divisions = self.data.get("divisions", [])
        for i, d in enumerate(divisions):
            self.division(d)
            if i < len(divisions) - 1:
                self.new_page()
        self.footer()
        self.c.save()


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: python3 render_brief.py <data.json> <out.pdf>")
    with open(sys.argv[1], "r") as f:
        data = json.load(f)
    Doc(sys.argv[2], data).build()
    print("built %s" % sys.argv[2])


if __name__ == "__main__":
    main()
