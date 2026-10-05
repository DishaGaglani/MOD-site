"""S6 Validate & normalize: check GLM's JSON against the PDF's own totals, clean dates and names."""
import json
import os

PUNCTUATION = ".,;:()[]{}'\"/\\-_&|"
FIRM_PREFIXES = ("m/s.", "m/s", "m/ s", "ms.", "ms ", "mis ")


def normalize_date(value):
    """'01.09.2025' / '1/9/25' / '01-09-2025' -> '2025-09-01'. Returns (iso_or_original, ok)."""
    if not value:
        return None, False
    text = str(value).strip()
    for sep in ("/", "-", " "):
        text = text.replace(sep, ".")
    parts = [p for p in text.split(".") if p]
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        d, m, y = (int(p) for p in parts)
        if len(parts[0]) == 4:  # already year-first
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        if y < 100:
            y += 2000
        if 1 <= d <= 31 and 1 <= m <= 12 and 1990 <= y <= 2100:
            return f"{y:04d}-{m:02d}-{d:02d}", True
    return str(value).strip(), False


def firm_key(name: str) -> str:
    """Comparable firm name: lowercase, no 'M/s' prefix, no punctuation, single spaces."""
    key = " ".join((name or "").split()).casefold()
    for prefix in FIRM_PREFIXES:
        if key.startswith(prefix):
            key = key[len(prefix):]
            break
    for ch in PUNCTUATION:
        key = key.replace(ch, " ")
    return " ".join(key.split())


def normalize_category(category: str) -> str:
    c = (category or "").casefold()
    if "debar" in c:
        return "Debarred"
    if "hold" in c or "suspend" in c:
        return "Put on hold/Suspended"
    return (category or "Unknown").strip()


def validate(extraction: dict, doc: dict, cfg) -> dict:
    """Return the clean extraction (also written to data/json/<id>.clean.json)."""
    issues = []
    as_on, ok = normalize_date(extraction.get("as_on_date"))
    if not ok:
        issues.append(f"as_on_date unreadable ({extraction.get('as_on_date')!r}); using listed date")
        as_on = doc["listed_date"]

    sections = []
    for sec in extraction.get("sections") or []:
        category = normalize_category(sec.get("category"))
        firms_in = [f for f in (sec.get("firms") or []) if isinstance(f, dict)]
        stated = sec.get("stated_total")
        count_ok = stated is None or stated == len(firms_in)
        if not count_ok:
            issues.append(f"{category}: PDF says Total {stated}, extracted {len(firms_in)}")

        firms = []
        for f in firms_in:
            order_date, date_ok = normalize_date(f.get("order_date"))
            name = " ".join((f.get("firm_name") or "").split())
            problems = []
            if not name:
                problems.append("no firm name")
            if not f.get("order_ref"):
                problems.append("no order ref")
            if f.get("order_date") and not date_ok:
                problems.append("order date unreadable")
            if not count_ok:
                problems.append("section total mismatch")
            firms.append({
                "s_no": f.get("s_no"),
                "firm_name": name,
                "firm_key": firm_key(name),
                "location": f.get("location"),
                "mod_division": f.get("mod_division"),
                "order_ref": f.get("order_ref"),
                "order_date": order_date,
                "needs_review": bool(problems),
                "review_reason": "; ".join(problems),
            })
        sections.append({"category": category, "stated_total": stated, "firms": firms})

    if not sections or not any(s["firms"] for s in sections):
        issues.append("no firms extracted")

    clean = {
        "notice_id": doc["notice_id"],
        "title": doc["title"],
        "listed_date": doc["listed_date"],
        "pdf_url": doc["pdf_url"],
        "sha256": doc["sha256"],
        "reference_no": extraction.get("reference_no"),
        "as_on_date": as_on,
        "sections": sections,
        "issues": issues,
    }
    path = os.path.join(cfg["paths"]["json"], f"{doc['notice_id']}.clean.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2, ensure_ascii=False)
    return clean
