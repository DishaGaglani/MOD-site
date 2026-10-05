# CLAUDE.md — MoD Debarment Extraction Agent

## Goal

Build an agent for L&T PES that:
1. Crawls the Ministry of Defence (MoD) "OMs & Orders" pages.
2. Selects notices whose title contains "debar" (covers debarment/debarred), using a plain substring check, **never regex** (user requirement).
3. Downloads each matching PDF.
4. Extracts the firm list with **GLM** (OCR + structuring).
5. Builds an Excel register: `output/debarment_list.xlsx`.

Architecture write-up for the team: `MoD_Debarment_Agent_Architecture.docx` (this folder), updated to match the build. Its generator script lives outside the repo (session scratchpad), so edit the docx directly or regenerate it if it needs changes.

## Commands

```bash
.venv/bin/pip install -r requirements.txt   # venv already exists in .venv/
.venv/bin/python main.py              # full run
.venv/bin/python main.py --no-glm     # discover + download only
.venv/bin/python -m unittest tests/test_pipeline.py   # 24 offline tests, no network/GLM
```

Secrets go in `.env` as `GLM_API_KEY=...`. Never hardcode keys. All settings live in `config.yaml`.

## Source site facts (verified 2026-10-05)

- The user's original URL `https://www.mod.gov.in/did/en/oms_orders_archive` **404s**. The correct pages are:
  - `https://www.mod.gov.in/dod/en/oms_orders_Archive` (17 pages, `?page=0..16`)
  - `https://www.mod.gov.in/dod/en/oms_orders` (3 pages)
- These are static Drupal tables, so requests + BeautifulSoup is enough; **no Selenium**. Row selectors:
  - `td.views-field-title`: title
  - `<time>`: date
  - `td.views-field-nothing a[href]`: relative PDF link
- Use the `/en/` pages. The non-`/en/` pages show Hindi titles that the keyword would miss.
- A browser User-Agent is required. On macOS, urllib fails SSL verification, so use `requests` + `certifi` (see `src/http.py`).
- 197 rows in total and **6 matching notices** (2023-02-10 → 2025-09-01). All are titled "Details of firms debarred/put on hold/suspended etc. from doing business with MoD".

## PDF facts (these drive the extraction design)

- The PDFs are scanned, 1–2 pages each. They have an existing text layer, but it is **garbage OCR**. Never trust it; always OCR.
- Each PDF is a **cumulative snapshot** ("as on <date>"), not a single order. Most firms repeat across snapshots.
- There are two sections: **Debarred Firms (Total 6)** and **Put on hold/Suspended Firms (Total 15)**. Each section header prints its "Total N".
- Columns: S.No · firm name + location · MoD division · order no. & date.
- **Merged cells**: one order often covers several firms. It must be copied onto each firm.

## Pipeline (as built)

```
S1 Discover  src/scraper.py         crawl ?page=N until empty page; raise LayoutChanged if page 0 has no table
S2 Filter    src/scraper.py         is_match(): "debar" in " ".join(title.split()).casefold()
S3 Dedup     src/state.py           state/processed.json keyed by pdf_url; retry "failed"; "done" PDFs are
                                    re-downloaded and sha256-compared -> changed = clear cache, redo
S4 Download  src/downloader.py      data/pdfs/<notice_id>.pdf, verify %PDF- magic, sha256
S5a OCR      src/glm_ocr.py         GLM-OCR -> Markdown, cached data/ocr/<id>.md
S5b Struct.  src/glm_structurer.py  GLM chat -> Extraction JSON, raw reply cached data/json/<id>.raw.json
S6 Validate  src/validator.py       dates -> ISO, firm_key, category normalize, Total-N check -> <id>.clean.json
S7 Consol.   src/consolidate.py     all clean JSON -> records, current status (latest as_on), changes
S8 Export    src/excel_writer.py    rebuilds Excel each run: Current Status, All Records, Changes, Run Log
Orchestrator main.py                one failed notice never stops the run; exit 1 if any failed
```

`notice_id` is `<listed_date>_<pdf filename stem>` and links every file for a notice.

**JSON shapes.** Each notice passes through four shapes:
1. `Notice`: title, date, URL.
2. `DownloadedDoc`: adds `pdf_path` and `sha256`.
3. `Extraction`: `reference_no` and `as_on_date`, then `sections[]` (`category` and `stated_total`), then `firms[]`.
4. `Record`: one flat row per firm, with `firm_key` and `needs_review`.

**Cost rule:** GLM output is cached on disk, so it is never paid for twice. Keep this when changing the code.

## GLM backends

The switch between backends is config-only. Keep both backends working.

| Step | Now (hosted Z.ai) | Later (user's GPU VM) |
|---|---|---|
| OCR | `ocr.backend: zai`: POST `https://api.z.ai/api/paas/v4/layout_parsing`, `model: glm-ocr`, whole PDF as a `data:application/pdf;base64,…` URI, reads `md_results` | `ocr.backend: ollama`: PyMuPDF renders pages at 300 DPI, POST `<vm>:11434/api/generate`, prompt `Text Recognition:` |
| Structuring | OpenAI-compatible `/chat/completions` at `https://api.z.ai/api/paas/v4`, `model: glm-4.7-flash` (free tier), `temperature 0`, `response_format: json_object` | Same code; set `structurer.base_url: http://<vm>:11434/v1` and pick a chat model pulled on the VM |

GLM-OCR is a 0.9B model; Z.ai lists it at $0.03 per million tokens. It reads text and tables but does not reliably follow custom JSON rules, so structuring is a separate step.

## Status

### Done
- [x] Site investigation; correct URLs; selectors; PDF structure analysis
- [x] Architecture doc (`MoD_Debarment_Agent_Architecture.docx`)
- [x] Full codebase (all stages above), `config.yaml`, `requirements.txt`, `.venv`
- [x] Tested live: discover + download (197 rows, 6 matches, 6 PDFs in `data/pdfs/`)
- [x] Tested offline with a synthetic GLM reply: validate → consolidate → Excel (all 4 sheets, changes detection, Total-N mismatch flag, firm_key matching "M/s R. K." = "Ms R.K.")
- [x] Missing API key fails cleanly per notice (logged, marked `failed`, retried next run)
- [x] Changed-PDF detection (sha256 re-check of done notices); tested live with a faked fingerprint
- [x] Unit tests: `tests/test_pipeline.py` (24 tests, all passing)
- [x] Docx updated to the two-step OCR + structuring design

### To do
- [ ] **Get a Z.ai API key** into `.env`, then run the first real end-to-end pass. `state/processed.json` currently marks all 6 as `failed` from the no-key test; they will retry automatically.
- [ ] **Tune on real output.** Inspect `data/ocr/*.md` and `data/json/*.raw.json`, then adjust `SYSTEM_PROMPT` in `src/glm_structurer.py`. Expect work on merged cells, section totals and location splitting. Check that the Excel "Needs Review" rows are few.
- [ ] Verify that the `data:` URI base64 input is accepted by `layout_parsing`. The docs say URL or base64; the GLM-OCR SDK wraps raw base64 as a data URI.
- [ ] Possibly disable "thinking" on the Z.ai chat call if `glm-4.7-flash` is slow or verbose.
- [ ] Deploy GLM-OCR + a chat model with Ollama on the user's GPU VM, then flip `config.yaml`: `ocr.backend: ollama`, `ocr.ollama_url`, `structurer.base_url: http://<vm-ip>:11434/v1`, `structurer.model`. The Ollama code path in `src/glm_ocr.py` has never been run.
- [ ] Optional: monthly cron schedule; email/alert on new debarments.

### Open decisions (ask the user)
- Which chat model to use on the VM, and the VM's GPU memory.
- Whether to keep all 4 Excel sheets (current assumption: yes).
- One-time run or a monthly schedule.

## Conventions

- Keyword matching uses plain string methods only, with no `re` module. The user explicitly asked for this; it also applies to firm-name and date cleanup in `validator.py`.
- Add or update tests in `tests/test_pipeline.py` when changing a stage; keep them offline (no network/GLM).
- One module per stage. Each stage writes to disk so a crashed run can resume.
- The Excel is always rebuilt from `data/json/*.clean.json`; never append to it.
- Keep the project lean: no extra files, flags, config options or speculative code. `data/`, `state/`, `output/`, `logs/` are runtime output, created on demand, and gitignored along with `.env` and `.venv/`.
