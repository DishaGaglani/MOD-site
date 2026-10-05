"""S5b Structure: a GLM chat model turns the OCR Markdown into our Extraction JSON.

Uses the OpenAI-compatible /chat/completions API, so the same code works with
Z.ai (https://api.z.ai/api/paas/v4) and Ollama on the VM (http://<vm-ip>:11434/v1).
"""
import json
import logging
import os
import time

import requests

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You convert OCR text of a Government of India, Ministry of Defence notice into JSON.
The notice lists firms debarred / put on hold / suspended from doing business with MoD.

Return ONLY a JSON object, no commentary, matching exactly this schema:
{
  "reference_no": string or null,      // the "No. ..." file reference at the top
  "as_on_date": string or null,        // the "as on DD.MM.YYYY" date in the body, as printed
  "sections": [
    {
      "category": string,              // section heading, e.g. "Debarred" or "Put on hold/Suspended"
      "stated_total": integer or null, // the "Total N" printed in that section heading
      "firms": [
        {
          "s_no": integer or null,
          "firm_name": string,         // e.g. "M/s R. K. Machine Tools Ltd."
          "location": string or null,  // city/country if printed with the name
          "mod_division": string or null,
          "order_ref": string or null, // order / MoD ID number
          "order_date": string or null // as printed, e.g. "01.04.2025"
        }
      ]
    }
  ]
}

Rules:
- One entry per firm. If an order number/date or division applies to several firms
  (a merged cell in the original table), copy it onto EACH of those firms.
- The table may continue across pages; treat it as one table.
- Copy text as printed; fix only obvious OCR spacing. Never invent values: use null if unreadable.
- Ignore Hindi text, stamps, signatures, and page footers."""


class StructureError(RuntimeError):
    pass


def structure(markdown: str, notice_id: str, cfg, api_key: str | None) -> dict:
    """Return the parsed Extraction dict. Raw model reply is cached in data/json/<id>.raw.json."""
    json_dir = cfg["paths"]["json"]
    os.makedirs(json_dir, exist_ok=True)
    raw_path = os.path.join(json_dir, f"{notice_id}.raw.json")

    if os.path.exists(raw_path):
        with open(raw_path, encoding="utf-8") as f:
            reply = json.load(f)["reply"]
        try:
            return parse_reply(reply)
        except StructureError:
            log.warning("Cached reply for %s is not valid JSON; asking the model again", notice_id)

    s_cfg = cfg["structurer"]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "OCR text of the notice:\n\n" + markdown},
    ]
    last_err = None
    for attempt in range(1, s_cfg["retries"] + 2):
        reply = _chat(messages, s_cfg, api_key)
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump({"model": s_cfg["model"], "reply": reply}, f, indent=2, ensure_ascii=False)
        try:
            return parse_reply(reply)
        except StructureError as e:
            last_err = e
            log.warning("Invalid JSON from model (attempt %d): %s", attempt, e)
            messages = messages + [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": "That was not valid JSON. Return ONLY the JSON object."},
            ]
    raise last_err


def _chat(messages, s_cfg, api_key) -> str:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": s_cfg["model"],
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    url = s_cfg["base_url"].rstrip("/") + "/chat/completions"
    for attempt in range(1, s_cfg["retries"] + 2):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=s_cfg["timeout"])
        except requests.RequestException as e:
            err = str(e)
        else:
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"] or ""
            err = f"HTTP {resp.status_code}: {resp.text[:500]}"
            if resp.status_code < 500 and resp.status_code != 429:
                raise StructureError(err)
        wait = 2 ** (attempt + 1)
        log.warning("Structurer call failed (%s), retrying in %ds", err, wait)
        time.sleep(wait)
    raise StructureError(f"Structurer failed after retries: {err}")


def parse_reply(reply: str) -> dict:
    """Pull the JSON object out of the model reply (tolerates ```json fences)."""
    start, end = reply.find("{"), reply.rfind("}")
    if start == -1 or end <= start:
        raise StructureError("no JSON object in reply")
    try:
        data = json.loads(reply[start:end + 1])
    except json.JSONDecodeError as e:
        raise StructureError(str(e)) from e
    if not isinstance(data, dict) or not isinstance(data.get("sections"), list):
        raise StructureError("JSON is missing the 'sections' list")
    return data
