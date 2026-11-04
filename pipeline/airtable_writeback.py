"""Last step of publish-booking.yml: record the outcome on the Bookings record.

Runs with `if: always()`, so it executes after failures too. It never fails
the workflow: a missing token or an Airtable error is logged and ignored,
because the publish itself has already succeeded or failed by this point.

Environment:
  RECORD_ID            Bookings record ID (validated)
  RESULT_FILE          JSON written by generate_booking_package.py (may be absent)
  GENERATE_OUTCOME     steps.gen.outcome
  COMMIT_OUTCOME       steps.commit.outcome
  DEPLOY_OUTCOME       steps.deploy.outcome   ("skipped" when nothing was pushed)
  PUSHED               steps.commit.outputs.pushed ("false" = nothing changed)
  AIRTABLE_WRITE_KEY   token with data.records:write on the Bookings base
  GITHUB_*             set by Actions (run URL)
"""

import json
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
import publish_support as ps  # noqa: E402

BOOKINGS_BASE = "app3FIECuG8iQr7kY"
BOOKINGS_TABLE = "tbl9Jb9UVSYLQ1Puc"


def decide(result, generate, commit, deploy, pushed="true"):
    """(ok, message) from the generator's result and the workflow step outcomes."""
    if generate != "success":
        return False, (result or {}).get("message") or "The generator step failed; see the Actions run log."
    if not result:
        return False, "The generator did not write a result; see the Actions run log."
    if result.get("status") != "published":
        return False, result.get("message") or f"Nothing was published (status: {result.get('status')})."
    if commit != "success":
        return False, "The page was built but committing it to main failed; the previous version is still live."
    if pushed == "false":
        return True, ""  # regenerated identical files: the live page already matches
    if deploy != "success":
        return False, "The page was committed but the Pages deploy did not succeed; check the deploy run."
    return True, ""


def patch_record(record_id, fields, key):
    resp = requests.patch(
        f"https://api.airtable.com/v0/{BOOKINGS_BASE}/{BOOKINGS_TABLE}/{record_id}",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"fields": fields, "typecast": True}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def main(env=None):
    env = os.environ if env is None else env
    record_id = env.get("RECORD_ID", "")
    if not ps.RECORD_ID_RE.match(record_id):
        print(f"Skipping write-back: {record_id!r} is not a Bookings record ID.")
        return 0
    key = env.get("AIRTABLE_WRITE_KEY")
    if not key:
        print("Skipping write-back: AIRTABLE_WRITE_KEY is not set (add the repo secret to enable it).")
        return 0

    result = {}
    result_file = env.get("RESULT_FILE", "")
    if result_file and Path(result_file).exists():
        try:
            result = json.loads(Path(result_file).read_text())
        except ValueError:
            result = {}
    ok, message = decide(result, env.get("GENERATE_OUTCOME", ""), env.get("COMMIT_OUTCOME", ""),
                         env.get("DEPLOY_OUTCOME", ""), env.get("PUSHED", "true"))
    if message:
        result = dict(result, message=message)
    fields = ps.writeback_fields(result, ok, ps.run_url(env))
    try:
        patch_record(record_id, fields, key)
        print(f"Wrote publish result to {record_id}: {fields[ps.F_PUBLISH_RESULT]}")
    except requests.RequestException as exc:
        print(f"WARNING: could not write the publish result to Airtable: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
