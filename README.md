# MOD-site

Builds an Excel register of firms debarred, put on hold or suspended by India's Ministry of Defence.

It scrapes the [MoD OMs & Orders](https://www.mod.gov.in/dod/en/oms_orders_Archive) pages for notices with "debar" in the title, downloads their scanned PDFs, reads them with GLM-OCR, structures the firm lists with a GLM chat model, and writes `output/debarment_list.xlsx`.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
echo "GLM_API_KEY=<your Z.ai key>" > .env
```

## Run

```bash
.venv/bin/python main.py            # full run
.venv/bin/python main.py --no-glm   # scrape + download only
.venv/bin/python -m unittest tests/test_pipeline.py
```

Re-runs only process new, failed or replaced PDFs; GLM output is cached so nothing is paid for twice.

## Output

| Sheet | Contents |
|---|---|
| Current Status | Firms in the latest notice |
| All Records | Every firm in every notice |
| Changes | Firms added, removed or moved between categories |
| Run Log | Result of each notice in the last run |

Rows highlighted yellow need a manual check (e.g. extracted firm count doesn't match the PDF's total).

## Self-hosted GLM

To use Ollama on a GPU machine instead of the Z.ai API, edit `config.yaml`:

```yaml
ocr:
  backend: ollama
  ollama_url: http://<vm-ip>:11434
structurer:
  base_url: http://<vm-ip>:11434/v1
  model: <chat model on the VM>
```

See `CLAUDE.md` for design details and project status.
