"""S5a OCR: GLM-OCR turns a scanned PDF into Markdown.

Two backends, chosen by config `ocr.backend`:
  zai    - hosted Z.ai layout_parsing API; the whole PDF is sent in one request.
  ollama - self-hosted GLM-OCR (e.g. on the GPU VM); pages are rendered to PNG and sent one by one.
"""
import base64
import logging
import os

import requests

log = logging.getLogger(__name__)


class OcrError(RuntimeError):
    pass


def ocr_pdf(pdf_path: str, notice_id: str, cfg, api_key: str | None) -> str:
    """Return OCR Markdown for the PDF. Cached in data/ocr/<id>.md so GLM is never called twice."""
    ocr_dir = cfg["paths"]["ocr"]
    os.makedirs(ocr_dir, exist_ok=True)
    md_path = os.path.join(ocr_dir, f"{notice_id}.md")
    if os.path.exists(md_path):
        log.info("OCR cached: %s", md_path)
        with open(md_path, encoding="utf-8") as f:
            return f.read()

    backend = cfg["ocr"]["backend"]
    if backend == "zai":
        markdown = _ocr_zai(pdf_path, cfg["ocr"], api_key)
    elif backend == "ollama":
        markdown = _ocr_ollama(pdf_path, cfg["ocr"])
    else:
        raise OcrError(f"Unknown ocr.backend: {backend}")

    if not markdown.strip():
        raise OcrError("OCR returned empty text")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    return markdown


def _ocr_zai(pdf_path, ocr_cfg, api_key):
    if not api_key:
        raise OcrError("GLM_API_KEY is not set (needed for ocr.backend=zai)")
    with open(pdf_path, "rb") as f:
        data_uri = "data:application/pdf;base64," + base64.b64encode(f.read()).decode()
    resp = requests.post(
        ocr_cfg["zai_url"],
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": ocr_cfg["model"], "file": data_uri},
        timeout=ocr_cfg["timeout"],
    )
    if resp.status_code != 200:
        raise OcrError(f"GLM-OCR HTTP {resp.status_code}: {resp.text[:500]}")
    return resp.json().get("md_results") or ""


def _ocr_ollama(pdf_path, ocr_cfg):
    import fitz  # PyMuPDF; only needed for the self-hosted backend

    pages = []
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc, start=1):
            png = page.get_pixmap(dpi=ocr_cfg["dpi"]).tobytes("png")
            resp = requests.post(
                ocr_cfg["ollama_url"].rstrip("/") + "/api/generate",
                json={"model": ocr_cfg["model"], "prompt": "Text Recognition:",
                      "images": [base64.b64encode(png).decode()], "stream": False},
                timeout=ocr_cfg["timeout"],
            )
            if resp.status_code != 200:
                raise OcrError(f"Ollama HTTP {resp.status_code} on page {i}: {resp.text[:500]}")
            pages.append(f"<!-- page {i} -->\n{resp.json().get('response', '')}")
    return "\n\n".join(pages)
