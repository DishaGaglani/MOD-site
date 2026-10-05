"""S3 Dedup: remembers which PDFs are done so re-runs only process new or failed notices."""
import json
import os
from datetime import datetime


class State:
    def __init__(self, path: str):
        self.path = path
        self.data = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.data = json.load(f)

    def is_done(self, pdf_url: str) -> bool:
        return self.data.get(pdf_url, {}).get("status") == "done"

    def sha_changed(self, pdf_url: str, sha256: str) -> bool:
        """True if a done notice's PDF now has a different fingerprint than when it was processed."""
        recorded = self.data.get(pdf_url, {}).get("sha256")
        return recorded is not None and recorded != sha256

    def mark(self, pdf_url: str, status: str, **extra):
        self.data[pdf_url] = {
            "status": status,
            "processed_at": datetime.now().isoformat(timespec="seconds"),
            **extra,
        }
        self.save()

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)
