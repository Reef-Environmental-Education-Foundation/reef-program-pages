"""Raise (or reset) bookings/<slug>/version.json when Airtable's Proposal Version
changes, so a live page shows "This proposal is being updated" instead of stale
pricing (render.js checkProposalVersion).

    python pipeline/write_version_marker.py <booking_record_id>

Read-only against Airtable (AIRTABLE_API_KEY). Writes only version.json, and only
for a page that is already published for this exact booking; otherwise it exits 0
having done nothing. The workflow commits and deploys the file.
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import generate_booking_package as g  # noqa: E402

RECORD_ID_RE = re.compile(r"^rec[A-Za-z0-9]{14}$")


def write_marker(record_id, org_name, proposal_version, bookings_dir=None):
    """Returns the path written, or None when there is nothing to update."""
    bookings_dir = Path(bookings_dir or g.BOOKINGS_OUT_DIR)
    slug = g.booking_slug(record_id, org_name)
    if g.published_booking_id(slug, bookings_dir) != record_id:
        print(f"No published page for {record_id} at bookings/{slug}/; nothing to mark.")
        return None
    path = bookings_dir / slug / "version.json"
    version = proposal_version or 1
    if path.exists():
        try:
            if json.loads(path.read_text()).get("currentVersion") == version:
                print(f"{path} already says version {version}.")
                return None
        except ValueError:
            pass
    path.write_text(json.dumps({"bookingId": record_id, "currentVersion": version,
                                "updatedAt": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}, indent=2) + "\n")
    print(f"Wrote {path}: currentVersion {version}")
    return path


def main():
    if len(sys.argv) != 2 or not RECORD_ID_RE.match(sys.argv[1]):
        print("Usage: python write_version_marker.py <booking_record_id>", file=sys.stderr)
        return 1
    record_id = sys.argv[1]
    fields = g.airtable_get(g.BOOKINGS_BASE, g.BOOKINGS_TABLE, record_id)["fields"]
    write_marker(record_id, fields.get("Organization Name", ""), fields.get("Proposal Version"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
