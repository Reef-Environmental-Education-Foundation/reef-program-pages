"""Post-deploy smoke check (run by deploy.yml after the Pages deploy).

Requests the site root and https://programs.reef.org/bookings/<slug>/ for every
booking published in the run. A URL fails if it does not answer 200 directly,
or if it redirects (any redirect, and github.io is called out by name).
Redirects are NOT followed, so a quiet bounce to the old address is caught.

Read-only: it only issues GET requests to the public site. No secrets are used
or printed. Results go to stdout and, when set, the GitHub run summary.

    python pipeline/smoke_check.py slug-one slug-two
Env: SMOKE_BASE_URL (default https://programs.reef.org), GITHUB_STEP_SUMMARY,
     SMOKE_ATTEMPTS (default 6), SMOKE_DELAY (seconds between tries, default 10).
"""
import os
import re
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "https://programs.reef.org"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch(url, timeout=20):
    """Return (status, location) for a single GET, without following redirects."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "reef-pages-smoke-check"})
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.headers.get("Location", "")
    except urllib.error.HTTPError as e:  # 3xx/4xx/5xx arrive here
        return e.code, e.headers.get("Location", "") if e.headers else ""
    except Exception as e:  # DNS, TLS, timeout
        return 0, "%s: %s" % (type(e).__name__, e)


def judge(status, location):
    """Return None when the URL is healthy, else a plain-English problem."""
    if status == 200:
        return None
    if 300 <= status < 400:
        if "github.io" in location.lower():
            return "redirects to github.io (%s): the custom domain is not serving this page" % location
        return "redirects (HTTP %d) to %s instead of answering 200" % (status, location or "an unknown address")
    if status == 0:
        return "request failed (%s)" % location
    return "HTTP %d instead of 200" % status


def check(url, attempts, delay, fetcher=fetch, sleep=time.sleep):
    """Retry briefly: Pages can take a moment to serve a fresh deploy."""
    problem = None
    for i in range(attempts):
        problem = judge(*fetcher(url))
        if problem is None:
            return None
        if i < attempts - 1:
            sleep(delay)
    return problem


def build_urls(base, slugs):
    base = base.rstrip("/")
    return [base + "/"] + ["%s/bookings/%s/" % (base, s) for s in slugs]


def run(base, slugs, attempts, delay, fetcher=fetch, sleep=time.sleep):
    bad = [s for s in slugs if not SLUG_RE.match(s)]
    if bad:
        raise ValueError("not a booking slug: %s" % ", ".join(bad))
    return [(u, check(u, attempts, delay, fetcher, sleep)) for u in build_urls(base, slugs)]


def summary(results):
    failed = [(u, p) for u, p in results if p]
    lines = ["## Post-deploy smoke check", ""]
    if failed:
        lines += ["**FAILED:** %d of %d URLs are not healthy. The deploy finished but the live site is not serving them correctly." % (len(failed), len(results)), ""]
    else:
        lines += ["All %d URLs answered 200 with no redirect." % len(results), ""]
    lines += ["| URL | Result |", "| --- | --- |"]
    for u, p in results:
        lines.append("| %s | %s |" % (u, "FAIL: " + p if p else "OK (200)"))
    return "\n".join(lines) + "\n"


def main(argv):
    base = os.environ.get("SMOKE_BASE_URL") or DEFAULT_BASE
    attempts = int(os.environ.get("SMOKE_ATTEMPTS") or 6)
    delay = float(os.environ.get("SMOKE_DELAY") or 10)
    results = run(base, argv, attempts, delay)
    text = summary(results)
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
    return 1 if any(p for _, p in results) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
