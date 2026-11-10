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

# Customer-facing copy must never mention seine netting / seining (Martha, 2026-11-05),
# even when a school asked for it. Case-insensitive; also catches "Seine".
FORBIDDEN_COPY_RE = re.compile(r"(?i)\bsein(?:e|es|ed|ing)\b")


class ForbiddenCopy(Exception):
    """Generated customer-facing output contains copy REEF never publishes."""


def assert_no_forbidden_copy(payload, where):
    """Fails the run (nothing published) if `payload` (a str or any JSON-able
    structure) mentions seine netting. Applied to the page data, the audience views,
    INTERNAL-PREVIEW.html and, in validate_build, every generated file."""
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    hit = FORBIDDEN_COPY_RE.search(text)
    if hit:
        ctx = text[max(0, hit.start() - 40):hit.end() + 40].replace("\n", " ")
        raise ForbiddenCopy(
            f"{where} mentions {hit.group(0)!r} ({ctx!r}). REEF does not offer seine netting, so it "
            "must not appear anywhere customer-facing. Remove it from the booking's Airtable fields "
            "(Optional Add-Ons, What's Included, Schedule items) or the itinerary file; nothing was published.")


# Draft / internal-review wording must never reach a school (Martha, 2026-11-06). It is shown
# only in the INTERNAL-PREVIEW build. A page published for a booking that is Approved to Share
# is scanned for these words; any hit fails the publish and nothing is written to bookings/.
INTERNAL_WORDING_RE = re.compile(
    r"(?i)\b(draft|outstanding|tbd|to be confirmed|to be determined|pending|finaliz\w*|rose|martha"
    # "review" only in its internal-review sense: educational use ("Fish ID Review & Exam",
    # "students review...") is legitimate and not flagged; the school-facing Next Steps line
    # "Review each section of this proposal with your team" is allowed below.
    r"|(?:under|for|pending|awaiting|internal|staff|design|pre-?approval)\s+review\w*"
    r"|review(?:ed)?\s+(?:by|task|gate|notes?|comments?)|reviewer)\b")
# The one school-facing sentence that may say "review" (Next Steps).
ALLOWED_PHRASES = ("Review each section of this proposal with your team",)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+")


class InternalWording(Exception):
    """A school-facing page contains draft / internal-review wording."""


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():        # values only: JSON keys are not shown to anyone
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def internal_wording_hits(payload, contact_names=()):
    """Every internal-wording match in the visible strings of `payload` (a str or a
    JSON-able structure). The booking's own REEF contact (e.g. "Rose Kelly") may be named,
    since the school is told to call that person; any other staff name may not."""
    allowed = {n.lower() for name in contact_names if name for n in [name] + name.split()}
    hits = []
    for text in _strings(payload):
        for phrase in ALLOWED_PHRASES:
            text = text.replace(phrase, "")
        text = EMAIL_RE.sub("", text)
        for m in INTERNAL_WORDING_RE.finditer(text):
            if m.group(0).lower() in allowed:
                continue
            hits.append(f"{m.group(0)!r} in {text[max(0, m.start() - 40):m.end() + 40]!r}")
    return hits


def assert_school_facing_clean(payload, where, contact_names=()):
    hits = internal_wording_hits(payload, contact_names)
    if hits:
        raise InternalWording(
            f"{where} contains draft / internal-review wording, which is shown only in the internal "
            "preview: " + "; ".join(hits[:8]) + (f" (+{len(hits) - 8} more)" if len(hits) > 8 else "")
            + ". Fix the source (Airtable field, itinerary file or template); nothing was published.")


PROPOSAL_REQUIRED = ("meta", "group", "dates", "roadmap", "cta", "reefContact",
                     "welcome", "glance", "days", "included", "pricing")


def parse_data_js(text):
    """data.js is `/* comment */ window.BOOKING_DATA = {json};` -- return the
    parsed object or raise ValueError."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object found")
    return json.loads(text[start:end + 1])


def validate_build(booking_dir, is_proposal, contact_names=None):
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
        seine = FORBIDDEN_COPY_RE.search(path.read_text())
        if seine:
            problems.append(f"{path.relative_to(booking_dir)} mentions {seine.group(0)!r} "
                            "(seine netting must never appear customer-facing)")
    if is_proposal and contact_names is not None:
        for path in [data_js] + sorted((booking_dir / "share").glob("*/data.js")):
            try:
                hits = internal_wording_hits(parse_data_js(path.read_text()), contact_names)
            except (ValueError, OSError):
                continue
            problems += [f"{path.relative_to(booking_dir)}: internal wording {h}" for h in hits[:5]]
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


SMOKE_FAILED_LINE = "Published, but the programs.reef.org check failed. See the run summary:"


def writeback_fields(result, ok, actions_run_url="", now=None, smoke_failed=False, smoke_run_url=""):
    """Bookings fields (by field ID) to write after a run.

    ok       True only when the page was generated, committed AND deployed.
    On success: published version, result, timestamp, message with run + page URLs.
    On failure: result and error text only; the published version and
    timestamp keep pointing at what is still live.
    Publish Requested is cleared either way.
    smoke_failed  the post-deploy programs.reef.org check failed AFTER a good
    publish. It is its own signal: the result stays Success and the message
    gains one extra line; it never turns a published page into a failure.
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
        if smoke_failed:
            fields[F_PUBLISH_MESSAGE] += (
                "\n" + SMOKE_FAILED_LINE + (f" {smoke_run_url}" if smoke_run_url else ""))
    else:
        fields[F_PUBLISH_RESULT] = RESULT_FAILED
        msg = result.get("message") or "The publish run did not complete; see the Actions run log."
        fields[F_PUBLISH_MESSAGE] = (f"{msg}\nActions run: {actions_run_url}" if actions_run_url else msg)[:4000]
    return fields
