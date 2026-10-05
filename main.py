"""MoD debarment extraction agent — runs the pipeline end to end.

Usage:
    python main.py              # full run
    python main.py --no-glm     # discover + download only
"""
import argparse
import logging
import os
import sys
from datetime import date

import yaml
from dotenv import load_dotenv

from src import consolidate
from src.downloader import download_pdf
from src.excel_writer import write_excel
from src.glm_ocr import ocr_pdf
from src.glm_structurer import structure
from src.http import make_session
from src.scraper import discover
from src.state import State
from src.validator import validate

ROOT = os.path.dirname(os.path.abspath(__file__))
log = logging.getLogger("debar")


def setup_logging(log_dir):
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(os.path.join(log_dir, f"run_{date.today()}.log"), encoding="utf-8"),
        ],
    )


def pdf_replaced(session, notice, cfg, state) -> bool:
    """Re-download a done notice's PDF and compare fingerprints. Network errors keep it 'done'."""
    try:
        doc = download_pdf(session, notice, cfg, refresh=True)
    except Exception as e:
        log.warning("Could not re-check %s (%s); keeping previous result", notice["notice_id"], e)
        return False
    return state.sha_changed(notice["pdf_url"], doc["sha256"])


def clear_cache(notice_id, cfg):
    """Delete cached OCR/model output for a notice so it is extracted again."""
    paths = cfg["paths"]
    for path in (
        os.path.join(paths["ocr"], f"{notice_id}.md"),
        os.path.join(paths["json"], f"{notice_id}.raw.json"),
    ):
        if os.path.exists(path):
            os.remove(path)


def build_excel(cfg, run_log):
    notices = consolidate.load_clean(cfg["paths"]["json"])
    records = consolidate.to_records(notices)
    write_excel(
        cfg["paths"]["excel"],
        consolidate.current_status(notices, records),
        records,
        consolidate.changes(notices, records),
        run_log,
    )
    return len(notices), len(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-glm", action="store_true", help="discover + download, skip GLM")
    args = parser.parse_args()

    os.chdir(ROOT)
    load_dotenv()
    with open("config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    setup_logging(cfg["paths"]["logs"])
    api_key = os.getenv("GLM_API_KEY") or None

    session = make_session()
    matches, total_rows = discover(session, cfg)
    log.info("Found %d listing rows, %d match '%s'", total_rows, len(matches), cfg["site"]["keyword"])

    state = State(cfg["paths"]["state"])
    run_log, counts = [], {"new": 0, "changed": 0, "extracted": 0, "failed": 0, "needs_review": 0}

    for notice in matches:
        entry = {"notice_id": notice["notice_id"], "listed_date": notice["listed_date"],
                 "pdf_url": notice["pdf_url"], "firms": None, "needs_review": None, "issues": ""}
        if state.is_done(notice["pdf_url"]):
            if not pdf_replaced(session, notice, cfg, state):
                run_log.append({**entry, "status": "skipped (already done)"})
                continue
            log.warning("PDF changed since last run, re-processing: %s", notice["notice_id"])
            clear_cache(notice["notice_id"], cfg)
            counts["changed"] += 1
        counts["new"] += 1
        try:
            doc = download_pdf(session, notice, cfg)
            log.info("Downloaded %s", doc["pdf_path"])
            if args.no_glm:
                run_log.append({**entry, "status": "downloaded"})
                continue
            markdown = ocr_pdf(doc["pdf_path"], doc["notice_id"], cfg, api_key)
            extraction = structure(markdown, doc["notice_id"], cfg, api_key)
            clean = validate(extraction, doc, cfg)
        except Exception as e:  # one bad notice must not stop the run
            log.exception("Failed: %s", notice["notice_id"])
            state.mark(notice["pdf_url"], "failed", error=str(e)[:500])
            counts["failed"] += 1
            run_log.append({**entry, "status": "failed", "issues": str(e)[:500]})
            continue

        firms = [f for s in clean["sections"] for f in s["firms"]]
        review = sum(f["needs_review"] for f in firms)
        counts["extracted"] += 1
        counts["needs_review"] += review
        state.mark(notice["pdf_url"], "done", sha256=clean["sha256"], firms=len(firms))
        run_log.append({**entry, "status": "success", "firms": len(firms),
                        "needs_review": review, "issues": "; ".join(clean["issues"])})
        log.info("Extracted %s: %d firms, %d need review", notice["notice_id"], len(firms), review)

    if not args.no_glm:
        n, r = build_excel(cfg, run_log)
        log.info("Wrote %s (%d notices, %d rows)", cfg["paths"]["excel"], n, r)

    log.info("SUMMARY found=%d matched=%d new=%d changed=%d extracted=%d failed=%d needs_review=%d",
             total_rows, len(matches), counts["new"], counts["changed"], counts["extracted"],
             counts["failed"], counts["needs_review"])
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
