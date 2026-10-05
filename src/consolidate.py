"""S7 Consolidate: flatten every clean notice into rows, find the current list and snapshot changes."""
import glob
import json
import os


def load_clean(json_dir: str) -> list[dict]:
    notices = []
    for path in sorted(glob.glob(os.path.join(json_dir, "*.clean.json"))):
        with open(path, encoding="utf-8") as f:
            notices.append(json.load(f))
    notices.sort(key=lambda n: (n["as_on_date"] or "", n["listed_date"] or ""))
    return notices


def to_records(notices: list[dict]) -> list[dict]:
    """One row per firm per notice."""
    rows = []
    for n in notices:
        for sec in n["sections"]:
            for f in sec["firms"]:
                rows.append({
                    "notice_id": n["notice_id"],
                    "listed_date": n["listed_date"],
                    "as_on_date": n["as_on_date"],
                    "reference_no": n["reference_no"],
                    "category": sec["category"],
                    "s_no": f["s_no"],
                    "firm_name": f["firm_name"],
                    "firm_key": f["firm_key"],
                    "location": f["location"],
                    "mod_division": f["mod_division"],
                    "order_ref": f["order_ref"],
                    "order_date": f["order_date"],
                    "pdf_url": n["pdf_url"],
                    "needs_review": f["needs_review"],
                    "review_reason": f["review_reason"],
                })
    return rows


def current_status(notices: list[dict], records: list[dict]) -> list[dict]:
    if not notices:
        return []
    latest = notices[-1]["notice_id"]
    return [r for r in records if r["notice_id"] == latest]


def changes(notices: list[dict], records: list[dict]) -> list[dict]:
    """Compare each snapshot with the previous one by firm_key."""
    by_notice = {}
    for r in records:
        by_notice.setdefault(r["notice_id"], {})[r["firm_key"]] = r

    out = []
    for prev, curr in zip(notices, notices[1:]):
        old = by_notice.get(prev["notice_id"], {})
        new = by_notice.get(curr["notice_id"], {})
        for key, r in new.items():
            if key not in old:
                out.append(_change(prev, curr, r, "Added", "", r["category"]))
            elif old[key]["category"] != r["category"]:
                out.append(_change(prev, curr, r, "Category changed", old[key]["category"], r["category"]))
        for key, r in old.items():
            if key not in new:
                out.append(_change(prev, curr, r, "Removed", r["category"], ""))
    out.sort(key=lambda c: (c["as_on_date"] or ""), reverse=True)
    return out


def _change(prev, notice, r, kind, frm, to):
    return {
        "as_on_date": notice["as_on_date"],
        "previous_as_on_date": prev["as_on_date"],
        "firm_name": r["firm_name"],
        "change": kind,
        "from": frm,
        "to": to,
        "pdf_url": notice["pdf_url"],
    }
