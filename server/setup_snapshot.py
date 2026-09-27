"""Generic setup snapshot helpers for ZRE Setup Engineer.

The module is intentionally independent from the iRacing polling loop. It
normalizes already-available setup data, supports lightweight HTML imports and
creates stable fingerprints so a stint can be tied to one exact setup.
"""
from html.parser import HTMLParser
from hashlib import sha256
import json
import re


def _clean_text(value):
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def flatten_parameters(value, prefix=""):
    """Flatten arbitrary nested setup structures without assuming a car schema."""
    out = {}
    if isinstance(value, dict):
        for key in sorted(value, key=lambda item: str(item).lower()):
            path = f"{prefix}.{key}" if prefix else str(key)
            out.update(flatten_parameters(value[key], path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            path = f"{prefix}[{index}]"
            out.update(flatten_parameters(item, path))
    elif prefix:
        out[prefix] = _json_safe(value)
    return out


def setup_fingerprint(parameters):
    flat = flatten_parameters(parameters)
    payload = json.dumps(flat, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()[:16]


def snapshot_from_sdk(car_setup, driver_info=None):
    params = _json_safe(car_setup or {})
    driver_info = driver_info or {}
    meta = {
        "setupName": _clean_text(driver_info.get("DriverSetupName")),
        "setupModified": driver_info.get("DriverSetupIsModified"),
        "setupLoadType": _clean_text(driver_info.get("DriverSetupLoadTypeName")),
        "setupPassedTech": driver_info.get("DriverSetupPassedTech"),
    }
    return {
        "source": "SDK",
        "fingerprint": setup_fingerprint(params),
        "metadata": meta,
        "parameters": params,
        "flatParameters": flatten_parameters(params),
    }


class _SetupHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self._row = None
        self._cell = None
        self._heading = None
        self.section = "General"

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag in ("h1", "h2", "h3", "h4"):
            self._heading = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
        if self._heading is not None:
            self._heading.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th") and self._cell is not None:
            text = _clean_text("".join(self._cell))
            if self._row is not None and text:
                self._row.append(text)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if len(self._row) >= 2:
                self.rows.append((self.section, self._row[0], " | ".join(self._row[1:])))
            self._row = None
        elif tag in ("h1", "h2", "h3", "h4") and self._heading is not None:
            text = _clean_text("".join(self._heading))
            if text:
                self.section = text
            self._heading = None


def snapshot_from_html(html_text, filename=None):
    parser = _SetupHTMLParser()
    parser.feed(html_text or "")
    parameters = {}
    for section, key, value in parser.rows:
        section_map = parameters.setdefault(section or "General", {})
        final_key = key
        suffix = 2
        while final_key in section_map:
            final_key = f"{key} [{suffix}]"
            suffix += 1
        section_map[final_key] = value
    return {
        "source": "IRACING_HTML",
        "fingerprint": setup_fingerprint(parameters),
        "metadata": {"filename": _clean_text(filename)},
        "parameters": parameters,
        "flatParameters": flatten_parameters(parameters),
    }


def compare_setups(previous, current):
    before = (previous or {}).get("flatParameters") or flatten_parameters((previous or {}).get("parameters") or {})
    after = (current or {}).get("flatParameters") or flatten_parameters((current or {}).get("parameters") or {})
    changes = []
    for key in sorted(set(before) | set(after), key=str.lower):
        old = before.get(key)
        new = after.get(key)
        if old != new:
            changes.append({"parameter": key, "before": old, "after": new})
    return changes
