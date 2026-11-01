"""Get Ready checklist and the internal next-phase preview (sprint Task D/E, 2026-10-31).

STAGED ONLY. Nothing here is linked from a live page or published. It builds:

  build_checklist(b, today)   checklist items with due dates, grouped by who does them
  build_preview_html(b, ...)  one self-contained, noindex HTML file for Martha and Rose

Dates come from Airtable wherever Airtable has them (Guarantee Lock Date,
Final Roster Due, the agreement deposit and payment dates). Items marked
"Template (confirm)" are generic and need Rose's review before any school sees
them. Completion state is read from b["checklist_state"] ({item key: {"done": bool,
"doneOn": "YYYY-MM-DD"}}), loaded from the Airtable "Checklist Items" table by
fetch_completion_state(). A missing row means outstanding.

Family and student pages never show pricing or contract terms: the checklist
carries no dollar amounts for those groups (enforced by a test).
"""
import html
from datetime import date, datetime, timedelta

import os

import requests

GROUPS = ["REEF", "School administrator", "Teacher to families", "Students and families"]
PRETRIP_WINDOW_DAYS = 120


def _d(value):
    if not value:
        return None
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _item(key, group, title, due=None, source="Template (confirm)", detail="", money=None, provisional=False):
    return {"key": key, "group": group, "title": title, "due": due, "source": source,
            "detail": detail, "money": money, "provisional": provisional}



# ---- Completion state: Airtable "Checklist Items" (tbl6BmRXNhnxxfabD) -------------
# One row per (booking, item). "Item Key" must be one of ITEM_KEYS below; "Done" is
# the checkbox; "Done On" and "Done By" are optional. A missing row means outstanding.
BOOKINGS_BASE = "app3FIECuG8iQr7kY"
CHECKLIST_TABLE = "tbl6BmRXNhnxxfabD"
F_ITEM_KEY = "fldvPaPRRFhDtFRCW"
F_DONE = "fldyIZDGmyfULPD8x"
F_DONE_ON = "flddmf1qgpHfyB48Z"
F_DONE_BY = "fldZFvEtmrZ5cZghT"
F_BOOKING = "fldl9U7R5wd51QTCQ"
ITEM_KEYS = ["sign_agreement", "deposit", "payment2", "guarantee", "final_payment", "chaperones",
             "share_family_page", "collect_forms", "final_roster", "return_forms", "bring_lunch",
             "confirm_boat_times", "confirm_transport", "confirm_rates", "send_agreement"]


def state_from_rows(rows, record_id):
    """{item key: {"done", "doneOn", "doneBy"}} for one booking from Checklist Items rows
    (REST shape, fields keyed by field ID). Rows for other bookings, with no Item Key, or
    with no Booking link are ignored. If a key appears twice, done wins."""
    state = {}
    for row in rows:
        f = row.get("fields", {})
        key = (f.get(F_ITEM_KEY) or "").strip()
        if not key or record_id not in (f.get(F_BOOKING) or []):
            continue
        done = bool(f.get(F_DONE))
        prev = state.get(key)
        if prev and prev["done"] and not done:
            continue
        state[key] = {"done": done, "doneOn": f.get(F_DONE_ON) or None, "doneBy": f.get(F_DONE_BY) or None}
    return state


def unknown_keys(state):
    """Item Keys in Airtable that no checklist item uses (typos), so Cowork can fix them."""
    return sorted(set(state) - set(ITEM_KEYS))


def fetch_completion_state(record_id, api_key=None, http=requests):
    """Read this booking's completion state from the Checklist Items table. Read only.
    Any failure returns {} (everything outstanding) and says so; it never raises."""
    api_key = api_key or os.environ.get("AIRTABLE_API_KEY")
    if not api_key:
        print("WARNING: no AIRTABLE_API_KEY; checklist shows everything outstanding.")
        return {}
    rows, offset = [], None
    try:
        while True:
            params = [("returnFieldsByFieldId", "true")] + [("fields[]", f) for f in
                      (F_ITEM_KEY, F_DONE, F_DONE_ON, F_DONE_BY, F_BOOKING)]
            if offset:
                params.append(("offset", offset))
            resp = http.get(f"https://api.airtable.com/v0/{BOOKINGS_BASE}/{CHECKLIST_TABLE}", params=params,
                            headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
            resp.raise_for_status()
            body = resp.json()
            rows.extend(body.get("records", []))
            offset = body.get("offset")
            if not offset:
                break
    except Exception as exc:  # noqa: BLE001 - a read problem must never break a build
        print(f"WARNING: could not read Checklist Items ({type(exc).__name__}); showing everything outstanding.")
        return {}
    state = state_from_rows(rows, record_id)
    for k in unknown_keys(state):
        print(f"WARNING: Checklist Items has an Item Key {k!r} that no checklist item uses.")
    return state


def build_checklist(b, today=None, state=None):
    """Ordered checklist items (dicts) with `done` filled from `state`."""
    today = today or datetime.utcnow().date()
    state = state if state is not None else (b.get("checklist_state") or {})
    arrival = _d(b.get("arrival_date"))
    agreement_known = bool(b.get("agreement_date"))
    lock = _d(b.get("guarantee_lock_date"))
    roster = _d(b.get("final_roster_due"))
    dep_due = _d(b.get("deposit_due_agreement"))
    p2_due = _d(b.get("payment2_due_agreement"))
    final_due = _d(b.get("final_due_date"))
    money = lambda v: f"${v:,.2f}" if isinstance(v, (int, float)) and v else None  # noqa: E731
    prov = not agreement_known  # payment dates are provisional until the Agreement Date is entered

    items = [
        # ---- School administrator
        _item("sign_agreement", "School administrator", "Review and sign the agreement",
              source="Airtable (Agreement/Contract Status)", detail="REEF sends the agreement; signing starts the payment schedule."),
        _item("deposit", "School administrator", "Pay the deposit", dep_due, "Airtable (Deposit Due)",
              money=money(b.get("deposit_amount_agreement")), provisional=prov),
        _item("payment2", "School administrator", "Second payment", p2_due, "Airtable (Payment 2 Due)",
              money=money(b.get("payment2_amount_agreement")), provisional=prov),
        _item("guarantee", "School administrator", "Confirm the final paid count (guarantee lock)", lock,
              "Airtable (Guarantee Lock Date)",
              detail=(f"Minimum guaranteed paid spaces: {b['min_guaranteed_spaces']}." if b.get("min_guaranteed_spaces") else "")),
        _item("final_payment", "School administrator", "Final payment", final_due, "Airtable (Final Payment Due Date)",
              detail="Amount: the balance under the signed agreement (not shown until the agreement exists).",
              provisional=prov),
        _item("chaperones", "School administrator", "Confirm the chaperone count",
              lock, "Airtable (# Total Chaperones is unconfirmed)",
              detail="The chaperone count changes the total: confirm it before the guarantee lock."),
        # ---- Teacher to families
        _item("share_family_page", "Teacher to families", "Share the family information page with families",
              roster, detail="Use the Family view of the proposal."),
        _item("collect_forms", "Teacher to families", "Collect signed forms and waivers", roster,
              "Airtable (Final Roster Due)", detail="Liability, medical, conduct and media forms are due with the final roster."),
        _item("final_roster", "Teacher to families", "Send REEF the final roster", roster, "Airtable (Final Roster Due)"),
        # ---- Students and families
        _item("return_forms", "Students and families", "Return signed forms to your teacher", roster,
              detail="Waiver links come from REEF; none are on this page yet."),
        _item("bring_lunch", "Students and families", "Pack a lunch for the program day", arrival,
              detail="Lunch is not provided."),
        # ---- REEF (from the booking's open items)
        _item("confirm_boat_times", "REEF", "Confirm real Pennekamp boat times", None, "Airtable (Missing Info / Risk Flag)"),
        _item("confirm_transport", "REEF", "Confirm whether REEF-arranged transport is available (never promise it until confirmed)",
              None, "Airtable (Missing Info / Risk Flag)"),
        _item("confirm_rates", "REEF", "Confirm Pennekamp group rates", None, "Airtable (Missing Info / Risk Flag)"),
        _item("send_agreement", "REEF", "Send the agreement (Rose, by hand)", None, "Airtable (Next Action)"),
    ]
    for it in items:
        s = state.get(it["key"]) or {}
        it["done"] = bool(s.get("done"))
        it["doneOn"] = s.get("doneOn")
        it["doneBy"] = s.get("doneBy")
        it["daysToDue"] = (it["due"] - today).days if it["due"] else None
        it["overdue"] = bool(it["due"] and not it["done"] and it["due"] < today)
    return items


def summarize(items):
    open_items = [i for i in items if not i["done"]]
    return {"total": len(items), "complete": len(items) - len(open_items), "outstanding": len(open_items),
            "overdue": sum(1 for i in open_items if i["overdue"])}


_CSS = """body{font-family:Public Sans,system-ui,sans-serif;margin:0;background:#f6f8fa;color:#0b2a4a}
.wrap{max-width:900px;margin:0 auto;padding:24px}
.banner{background:#7a1f1f;color:#fff;padding:10px 20px;text-align:center;font-weight:600;position:sticky;top:0}
h1{font-family:Fraunces,Georgia,serif;margin:.4em 0}h2{margin-top:1.6em;border-bottom:2px solid #1b8a9a;padding-bottom:4px}
.card{background:#fff;border:1px solid #d5dde5;border-radius:8px;padding:14px 18px;margin:10px 0}
.prov{background:#fff6dc;border:1px solid #e6c766;border-radius:6px;padding:2px 8px;font-size:12px;margin-left:6px}
table{border-collapse:collapse;width:100%}td,th{padding:7px 8px;border-bottom:1px solid #e3e8ee;text-align:left;vertical-align:top;font-size:14px}
.todo{color:#8a5a00}.done{color:#1b6b3a}.over{color:#a11;font-weight:700}.src{color:#667;font-size:12px}"""


def _fmt(d):
    return d.strftime("%b %-d, %Y") if d else "date not set"


def build_preview_html(b, today=None, items=None):
    today = today or datetime.utcnow().date()
    items = items if items is not None else build_checklist(b, today)
    s = summarize(items)
    e = html.escape
    agreement_known = bool(b.get("agreement_date"))
    prov = '' if agreement_known else '<span class="prov">provisional until the Agreement Date is entered</span>'
    rows = []
    for g in GROUPS:
        rows.append(f"<h3>{e(g)}</h3><table><tr><th>Task</th><th>Due</th><th>Status</th><th>Source</th></tr>")
        for it in [i for i in items if i["group"] == g]:
            status = (f'<span class="done">Complete{(" " + e(it["doneOn"])) if it.get("doneOn") else ""}</span>' if it["done"]
                      else '<span class="over">Overdue</span>' if it["overdue"] else '<span class="todo">Outstanding</span>')
            due = _fmt(it["due"]) + (' <span class="prov">provisional</span>' if it["provisional"] and it["due"] else "")
            title = e(it["title"]) + (f' <span class="src">{e(it["money"])}</span>' if it["money"] and g == "School administrator" else "")
            if it["detail"]:
                title += f'<div class="src">{e(it["detail"])}</div>'
            rows.append(f"<tr><td>{title}</td><td>{due}</td><td>{status}</td><td class=\"src\">{e(it['source'])}</td></tr>")
        rows.append("</table>")
    arrival = _d(b.get("arrival_date"))
    days_out = (arrival - today).days if arrival else None
    money_lines = [("Estimated total", b.get("total_package_price")), ("Deposit (agreement model)", b.get("deposit_amount_agreement")),
                   ("Second payment (agreement model)", b.get("payment2_amount_agreement")),
                   ("Guaranteed program cost (85% of paid spaces)", b.get("guaranteed_cost_agreement"))]
    money_html = "".join(f"<tr><td>{e(k)}</td><td>${v:,.2f}</td></tr>" for k, v in money_lines if v)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="robots" content="noindex, nofollow">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>INTERNAL PREVIEW: {e(b.get('org_name',''))} next phase</title>
<style>{_CSS}</style></head><body>
<div class="banner">INTERNAL PREVIEW for Martha and Rose. Not linked from any live page. Not for schools. Nothing here has been sent.</div>
<div class="wrap">
<h1>{e(b.get('org_name',''))}: what happens next</h1>
<p>Program date {e(_fmt(arrival))}{f' ({days_out} days away)' if days_out is not None else ''} &middot; {e(str(b.get('students') or ''))} students, {e(str(b.get('chaperones') or ''))} chaperones (chaperone count not yet confirmed by the school) &middot; stage: <b>{e(b.get('stage',''))}</b></p>
<h2>Where things stand</h2>
<div class="card"><b>Proposal:</b> version {e(str(b.get('proposal_version') or 1))}, approved and published. The school's earlier "Ready to Proceed" was clicked on version 1; it is not treated as final for the current numbers until Rose reconfirms the total with the school.<br>
<b>Agreement:</b> {e(str(b.get('agreement_contract_status') or 'not sent yet'))}. {prov}</div>
<h2>Admin view: money and dates</h2><div class="card">{prov}
<table>{money_html}</table>
<p class="src">Payment amounts and dates on this preview come from Airtable's agreement fields. They stay provisional until the Agreement Date is entered; the older Deposit / Payment 2 / Final fields give different amounts and should not both be shown to the school.</p>
<table><tr><td>Guarantee lock</td><td>{_fmt(_d(b.get('guarantee_lock_date')))}</td></tr><tr><td>Final roster due</td><td>{_fmt(_d(b.get('final_roster_due')))}</td></tr></table></div>
<h2>Get Ready checklist preview</h2>
<p>{s['complete']} of {s['total']} complete, {s['outstanding']} outstanding, {s['overdue']} overdue. Items marked "Template (confirm)" are generic and need Rose's review.</p>
{''.join(rows)}
<p class="src">Completion comes from the Airtable "Checklist Items" table (one row per item, matched by Item Key). An item with no row shows as outstanding.</p>
</div></body></html>"""
