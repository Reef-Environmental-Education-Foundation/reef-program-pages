"""Post-deploy check (run by publish-booking.yml after the Pages deploy succeeds).

Fetches the DEPLOYED booking page over HTTPS with a cache-busting query string and
confirms what a visitor's browser would get: the main page data, the administrator
share view and version.json all carry the version and total that were just published.
It retries for up to ~2 minutes because Pages takes a moment to serve a new deploy.

Never changes anything. On mismatch it writes `live_check_warning` into the run's
result file (so the Airtable Last Publish Message says so) and exits 1 (the run turns
red). If it cannot tell (no result file, no page URL) it exits 0 quietly.

    RESULT_FILE   JSON written by generate_booking_package.py
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
import publish_support as ps  # noqa: E402


def _get(http, url):
    resp = http.get(url, timeout=30, headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
    resp.raise_for_status()
    return resp.text


def live_problems(page_url, expected_version, expected_total, http=requests, now=time.time):
    """Problems between the deployed files and the expected publish; [] means they match."""
    base = page_url.rstrip("/") + "/"
    cb = f"cb={int(now())}"
    problems = []
    try:
        main = ps.parse_data_js(_get(http, f"{base}data.js?{cb}"))
        marker = json.loads(_get(http, f"{base}version.json?{cb}"))
        admin = ps.parse_data_js(_get(http, f"{base}share/administrator/data.js?{cb}"))
    except Exception as exc:  # noqa: BLE001 - any fetch/parse failure is a finding, not a crash
        return [f"could not fetch or read the deployed files ({type(exc).__name__})"]
    pd = main.get("proposal") or {}
    page_v = ps._version_number((pd.get("meta") or {}).get("proposalVersion"))
    admin_v = ps._version_number(((admin.get("view") or {}).get("version")))
    marker_v = ps._version_number(marker.get("currentVersion"))
    if expected_version is not None:
        for label, v in (("main page", page_v), ("administrator view", admin_v), ("version.json", marker_v)):
            if v != expected_version:
                problems.append(f"{label} serves v{v}, expected v{expected_version}")
    elif len({page_v, admin_v, marker_v}) > 1:
        problems.append(f"versions differ: main page v{page_v}, administrator v{admin_v}, version.json v{marker_v}")
    total = (pd.get("pricing") or {}).get("estimatedTotal")
    if expected_total and total != expected_total:
        problems.append(f"main page total {total} differs from the published total {expected_total}")
    admin_total = ((admin.get("view") or {}).get("pricing") or {}).get("total")
    if total and admin_total and total != admin_total:
        problems.append(f"main page total {total} differs from the administrator view total {admin_total}")
    return problems


def main(env=None, http=requests, sleep=time.sleep, attempts=12, delay=10):
    env = os.environ if env is None else env
    rf = env.get("RESULT_FILE", "")
    if not rf or not Path(rf).exists():
        print("Live check skipped: no result file.")
        return 0
    result = json.loads(Path(rf).read_text())
    page_url = result.get("page_url")
    if result.get("status") != "published" or not page_url:
        print("Live check skipped: nothing was published.")
        return 0
    expected_total = result.get("estimated_total")
    problems = []
    for i in range(attempts):
        problems = live_problems(page_url, ps._version_number(result.get("proposal_version")), expected_total, http=http)
        if not problems:
            print(f"Live check passed for {page_url}")
            return 0
        print(f"Live check attempt {i + 1}/{attempts}: " + "; ".join(problems))
        if i < attempts - 1:
            sleep(delay)
    result["live_check_warning"] = ("The deployed page does not match what was published: " + "; ".join(problems)
                                    + ". Check the live page with a hard refresh; if it is still wrong, republish.")
    ps.write_result(rf, **result)
    return 1


if __name__ == "__main__":
    sys.exit(main())
