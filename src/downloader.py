"""S4 Download: fetch a notice's PDF, verify it really is a PDF, record its SHA-256."""
import hashlib
import os

from .http import get_with_retry


class NotAPdf(RuntimeError):
    pass


def download_pdf(session, notice: dict, cfg, refresh: bool = False) -> dict:
    """refresh=True re-downloads even if the file exists (used to detect a replaced PDF)."""
    site = cfg["site"]
    out_dir = cfg["paths"]["pdfs"]
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{notice['notice_id']}.pdf")

    if refresh or not os.path.exists(path):
        resp = get_with_retry(session, notice["pdf_url"], timeout=site["timeout"],
                              retries=site["retries"], stream=True)
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
        with open(tmp, "rb") as f:
            if f.read(5) != b"%PDF-":
                os.remove(tmp)
                raise NotAPdf(f"{notice['pdf_url']} did not return a PDF")
        os.replace(tmp, path)

    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return {**notice, "pdf_path": path, "sha256": sha.hexdigest()}
