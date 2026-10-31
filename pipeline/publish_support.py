"""Publish-pipeline hardening helpers (2026-10-31).

Kept out of generate_booking_package.py so they can be unit-tested without
Airtable or Asana:

  validate_build()     checks a freshly built booking folder before anything
                       is copied into bookings/ (so a broken build can never
                       replace the page that is live).
  Result file          generate_booking_package.py writes a small JSON result
                       (status, version, page URL, message). The workflow's
                       last step reads it and calls airtable_writeback.py.
  writeback_fields()   the Bookings fields written after every run.
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

# Bookings field IDs (REEF Bookings | PILOT, table tbl9Jb9UVSYLQ1Puc).
F_PUBLISHED_VERSION = "fldMDPd0TI6qANixf"   # Published Proposal Version (number)
F_PUBLISH_RESULT = "fldChCOz6OfKyiag7"      # Last Publish Result (single select)
F_PUBLISHED_AT = "fldRUTE32fRD2eHaH"        # Last Published At (date/time)
F_PUBLISH_MESSAGE = "fldQ4aJnkvowzIUXh"     # Last Publish Message (long text)
F_PUBLISH_REQUESTED = "fldIQQuFZAWjeljTm"   # Publish Requested (checkbox)

RESULT_SUCCESS = "Success"
RESULT_FAILED = "Failed - previous version still live"

RECORD_ID_RE = re.compile(r"^rec[A-Za-z0-9]{14}$")

# A built page must never contain these (a template or number that did not
# resolve). The scan runs over generated files only, never over render.js.
BAD_TEXT_RE = re.compile(r"\bundefined\b|\bNaN\b|\$\{|\{\{")

PROPOSAL_REQUIRED = ("meta", "group", "dates", "roadmap", "cta", "reefContact",
                     "welcome", "glance", "days", "included", "pricing")


def parse_data_js(text):
    """data.js is `/* comment */ window.BOOKING_DATA = {json};` -- return the
    parsed object or raise ValueError."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object found")
    return json.loads(text[start:end + 1])


def validate_build(booking_dir, is_proposal):
    """Problems found in a freshly built booking folder; an empty list means
    it is safe to publish."""
    booking_dir = Path(booking_dir)
    problems = []

    data_js = booking_dir / "data.js"
    index_html = booking_dir / "index.html"
    if not index_html.exists():
        problems.append("index.html was not written")
    if not data_js.exists():
        return problems + ["data.js was not written"]

    text = data_js.read_text()
    try:
        data = parse_data_js(text)
    except ValueError as exc:
        return problems + [f"data.js does not parse: {exc}"]

    if not data.get("docType"):
        problems.append("data.js has no docType")
    body = data.get("proposal") if is_proposal else data
    if is_proposal:
        if not isinstance(body, dict):
            problems.append("proposal data is missing")
        else:
            for key in PROPOSAL_REQUIRED:
                if body.get(key) in (None, "", [], {}):
                    problems.append(f"required section '{key}' is empty or missing")
            if not (body.get("pricing") or {}).get("estimatedTotal"):
                problems.append("pricing.estimatedTotal is missing")
    elif not (data.get("days") or (data.get("proposal") or {}).get("days")):
        problems.append("the page has no days")

    scanned = [index_html, data_js] + sorted((booking_dir / "share").glob("*/data.js")) \
        + sorted((booking_dir / "share").glob("*/index.html"))
    for path in scanned:
        if not path.exists():
            continue
        hit = BAD_TEXT_RE.search(path.read_text())
        if hit:
            problems.append(f"{path.relative_to(booking_dir)} contains {hit.group(0)!r}")
    return problems


def run_url(env=None):
    env = os.environ if env is None else env
    if env.get("GITHUB_RUN_ID") and env.get("GITHUB_REPOSITORY"):
        return f"{env.get('GITHUB_SERVER_URL', 'https://github.com')}/{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}"
    return ""


def write_result(path, **result):
    """Atomic write of the run result the workflow's last step reads."""
    if not path:
        return
    tmp = f"{path}.tmp"
    Path(tmp).write_text(json.dumps(result, indent=2))
    os.replace(tmp, path)


def writeback_fields(result, ok, actions_run_url="", now=None):
    """Bookings fields (by field ID) to write after a run.

    ok       True only when the page was generated, committed AND deployed.
    On success: published version, result, timestamp, message with run + page URLs.
    On failure: result and error text only; the published version and
    timestamp keep pointing at what is still live.
    Publish Requested is cleared either way.
    """
    fields = {F_PUBLISH_REQUESTED: False}
    if ok:
        fields[F_PUBLISH_RESULT] = RESULT_SUCCESS
        fields[F_PUBLISHED_AT] = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        if result.get("proposal_version") is not None:
            fields[F_PUBLISHED_VERSION] = result["proposal_version"]
        fields[F_PUBLISH_MESSAGE] = (
            f"Published. Actions run: {actions_run_url or '(unknown)'}\n"
            f"Live page: {result.get('page_url', '(unknown)')}")
    else:
        fields[F_PUBLISH_RESULT] = RESULT_FAILED
        msg = result.get("message") or "The publish run did not complete; see the Actions run log."
        fields[F_PUBLISH_MESSAGE] = (f"{msg}\nActions run: {actions_run_url}" if actions_run_url else msg)[:4000]
    return fields
