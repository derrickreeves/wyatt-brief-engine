"""payload.json -> markdown. Faithful to the PDF: every section, card, table row, prose line and flag.
Written 2026-09-22 for the n8n rebuild; the markdown copy is what Wyatt's Claude reads."""
import json, sys

def _cell(v):
    if isinstance(v, (list, tuple)):
        return _cell(v[0]) if v else ""
    if v is None:
        return ""
    return str(v).replace("|", "\\|").replace("\n", " ")

def render(p):
    out = []
    cov = p.get("cover", {})
    out.append(f"# {cov.get('title', 'Wyatt Portfolio Daily Brief')}")
    out.append("")
    out.append(p.get("as_of_line", ""))
    out.append("")
    if cov.get("health"):
        out.append(f"**Portfolio health:** {cov['health']}")
        out.append("")
    att = cov.get("attention") or []
    out.append("**Needs attention** (every gap carries the name of the person who enters that data)")
    out.append("")
    if att:
        for it in att:
            it = list(it) + ["", ""]
            out.append(f"- **{_cell(it[0])}** {_cell(it[1])}".rstrip())
    else:
        out.append("- Nothing outstanding: every form was filed and no required field is blank.")
    out.append("")
    inc = cov.get("included") or []
    if inc:
        out.append("**Divisions in this brief**")
        out.append("")
        for row in inc:
            name, sub = (row + ["", ""])[:2] if isinstance(row, list) else (str(row), "")
            out.append(f"- {name}" + (f": {sub}" if sub else ""))
        out.append("")
    com = cov.get("coming") or []
    if com:
        out.append("**Coming:** " + ", ".join(str(c) for c in com))
        out.append("")
    if cov.get("note"):
        out.append(f"_{cov['note']}_")
        out.append("")
    for div in p.get("divisions", []):
        out.append(f"## {div.get('title', '')}")
        out.append("")
        if div.get("health"):
            out.append(f"**Health:** {div['health']}")
            out.append("")
        for b in div.get("blocks", []):
            k = b.get("kind")
            if k == "section":
                out.append(f"### {b.get('title', '')}")
                if b.get("sub"):
                    out.append(f"_{b['sub']}_")
                out.append("")
            elif k == "cards":
                for it in b.get("items", []):
                    it = list(it) + ["", "", "", ""]
                    line = f"- **{_cell(it[0])}:** {_cell(it[1])}"
                    if _cell(it[2]):
                        line += f" ({_cell(it[2])})"
                    out.append(line)
                out.append("")
            elif k == "table":
                cols = [_cell(c) for c in b.get("cols", [])]
                if cols:
                    out.append("| " + " | ".join(cols) + " |")
                    out.append("|" + "---|" * len(cols))
                for r in b.get("rows", []):
                    cells = [_cell(c) for c in r]
                    cells += [""] * (len(cols) - len(cells))
                    out.append("| " + " | ".join(cells) + " |")
                if b.get("note"):
                    out.append("")
                    out.append(f"_{_cell(b['note'])}_")
                out.append("")
            elif k == "prose":
                out.append(_cell(b.get("text", "")))
                out.append("")
            elif k == "report":
                if b.get("weekend"):
                    out.append(f"_{b.get('what', '')}: weekend, no filing expected_")
                elif b.get("missed"):
                    out.append(f"**Did not report yesterday:** {', '.join(b['missed'])}")
                else:
                    out.append("**Everyone reported yesterday**")
                if b.get("tally"):
                    out.append(f"_Filed, last 5 business days ({b.get('window', '')}): {b['tally']}_")
                out.append("")
            elif k == "flags":
                out.append("**Data flags**")
                out.append("")
                for it in b.get("items", []):
                    it = list(it) + ["", ""]
                    out.append(f"- **{_cell(it[0])}** {_cell(it[1])}".rstrip())
                out.append("")
            else:
                out.append(f"<!-- unrendered block kind={k} -->")
                out.append(json.dumps(b)[:500])
                out.append("")
        if div.get("foot"):
            out.append(f"_{div['foot']}_")
            out.append("")
    if p.get("brief_foot"):
        out.append("---")
        out.append(p["brief_foot"])
    return "\n".join(out) + "\n"

if __name__ == "__main__":
    print(render(json.load(open(sys.argv[1]))))
