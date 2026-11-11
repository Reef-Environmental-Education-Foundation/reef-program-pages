"""Browser check for the 2027 meals block (not part of unittest discovery: needs playwright + chromium).

    python pipeline/qa_meals_render_check.py [base_ref=origin/main]

For each committed proposal below it loads the page twice, once with base_ref's assets/render.js
and once with the working tree's, and requires identical DOM when the booking has no meals.
It then injects a pricing.mealsOutside block into the data and checks where it renders.
Nothing is published and Airtable is never called."""
import http.server, json, re, subprocess, sys, threading, functools
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE_REF = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
SLUGS = ["zzz-test-org-scenario-abcd-sample-academy",
         "thomas-jefferson-high-school-for-science-and-technology-tjhsst"]
MEALS = {"text": "Optional meals during scheduled programming:\nLunch Day 1: 40 x $14.00 = $560.00 (optional)\n\nBreakfast, dinner and lodging are arranged and paid directly by your school.",
         "totalPayableLabel": "Total payable to REEF (including selected meals)", "totalPayable": "$31,515.60"}
INTERNAL_SENTINELS = ["Vendor", "Margin", "Access Code", "fld"]


def norm(html):
    """render.js gives each hero's SVG gradients a random id suffix; that is the only
    nondeterminism in the DOM, so it is normalised before comparing."""
    return re.sub(r'((?:bg|sun)[a-z]+?)[a-z0-9]{5}(?=["\)])', r"\1", html)


def main():
    base_js = subprocess.check_output(["git", "show", f"{BASE_REF}:assets/render.js"], cwd=ROOT, text=True)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    failures = []
    with sync_playwright() as p:
        br = p.chromium.launch()

        def load(slug, render_override=None, data_override=None):
            ctx = br.new_context()
            pg = ctx.new_page()
            if render_override is not None:
                pg.route(re.compile(r".*/assets/render\.js.*"), lambda r, _q=None: r.fulfill(body=render_override, content_type="application/javascript"))
            if data_override is not None:
                pg.route(re.compile(r".*/data\.js.*"), lambda r, _q=None: r.fulfill(body=data_override, content_type="application/javascript"))
            pg.goto(f"http://127.0.0.1:{port}/bookings/{slug}/", wait_until="networkidle")
            return ctx, pg

        for slug in SLUGS:
            c1, a = load(slug, render_override=base_js); base_dom = norm(a.inner_html("body")); c1.close()
            c2, b = load(slug); new_dom = norm(b.inner_html("body"))
            has = b.query_selector("#meals-outside") is not None; c2.close()
            same = base_dom == new_dom and not has
            print(f"{slug}: no-meals DOM identical to {BASE_REF}: {same}")
            if not same: failures.append(f"{slug}: DOM changed without meals")

            src = (ROOT / "bookings" / slug / "data.js").read_text()
            data = json.loads(src[src.index("{"): src.rindex("}") + 1])
            data["proposal"]["pricing"]["mealsOutside"] = MEALS
            c3, m = load(slug, data_override="window.BOOKING_DATA = " + json.dumps(data) + ";")
            order = m.evaluate("""() => { const s = document.querySelector('#sec-pricing'); const k = [...s.querySelectorAll(':scope > .container')];
              const i = k.findIndex(e => e.querySelector('.price-tiles')); const j = k.findIndex(e => e.id === 'meals-outside');
              return {tiles: i, meals: j, text: (k[j]||{}).innerText || '', est: s.querySelector('.price-total-note')?.innerText || ''}; }""")
            ok = order["meals"] == order["tiles"] + 1 and "Total payable to REEF (including selected meals): $31,515.60" in order["text"] \
                and "paid directly by your school" in order["text"] and "Estimated total" not in order["text"]
            body = m.inner_text("body"); c3.close()
            for s in INTERNAL_SENTINELS:
                if s in body: ok = False; failures.append(f"{slug}: '{s}' on page")
            print(f"{slug}: meals block directly after Total Package block, text + total present: {ok}  {order['tiles']}->{order['meals']}")
            if not ok: failures.append(f"{slug}: meals placement/content")
        br.close()
    print("PASS" if not failures else "FAIL: " + "; ".join(failures))
    sys.exit(1 if failures else 0)


main()
