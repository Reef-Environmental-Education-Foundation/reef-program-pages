"""Standalone verification script for the 2026-09-09 QA walkthrough fixes.

Not part of the deployed pipeline -- run manually (`python3
verify_qa_walkthrough_fixes_2026-09-09.py`) as evidence for two of the
"must fix" findings that turned out to already be correct in the live
system, so the fix was verifying and documenting them, not changing code:

1. The ZZZ sample-flag safety net (is_test_org) actually forces
   sampleFlag=True for every case-variant of a "ZZZ..." org name, and
   never fires for a normal org name -- i.e. QA/test content cannot
   render for a real booking. Checked with a real test, not just a
   code read (this is the same language the Sept 9 checkpoint doc used
   to describe this exact gap).
2. Martha's stated chaperone rule (2026-09-09: "for every nine paid
   humans, there is one free human... seventeen total people... one
   free... nineteen... twenty... two free") matches the *existing*
   Airtable formula on "# Free Chaperones" exactly:
     MIN(chaperones, ROUNDDOWN((students+chaperones)/threshold, 0))
   with threshold defaulting to 9. No pipeline or Airtable change was
   needed -- this only needed to be confirmed and then explained in the
   proposal's own copy (see the new pricing.conditions bullets in
   build_proposal_data()).
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from generate_booking_package import is_test_org  # noqa: E402


def free_chaperones(students, chaperones, threshold=9):
    """Python port of the live Airtable formula on "# Free Chaperones"
    (fldWpVEwDKeGkUrcu), fetched directly from the base on 2026-09-09:
    MIN(chaperones, ROUNDDOWN((students+chaperones)/threshold, 0))."""
    return min(chaperones, math.floor((students + chaperones) / threshold))


def check(label, actual, expected):
    status = "PASS" if actual == expected else "FAIL"
    print(f"[{status}] {label}: got {actual!r}, expected {expected!r}")
    return actual == expected


def main():
    ok = True

    print("-- ZZZ sample-flag safety net (is_test_org) --")
    ok &= check("'ZZZ TEST ORG'", is_test_org("ZZZ TEST ORG -- Riverside Academy"), True)
    ok &= check("'zzz test org' (lowercase)", is_test_org("zzz test org"), True)
    ok &= check("'  ZzZ Staff Test' (mixed case, leading space)", is_test_org("  ZzZ Staff Test"), True)
    ok &= check("'Riverside Academy' (real org)", is_test_org("Riverside Academy"), False)
    ok &= check("'' (blank)", is_test_org(""), False)
    ok &= check("None", is_test_org(None), False)

    print("\n-- Chaperone free-space formula vs. Martha's stated rule (2026-09-09) --")
    # Martha: 17 total -> 1 free; 19 total -> 2 free; 20 total -> 2 free.
    # Read as (students, chaperones) pairs summing to those totals, with
    # enough chaperones present that the MIN() cap isn't the binding
    # constraint (i.e. testing the ROUNDDOWN ratio itself).
    ok &= check("17 total people (e.g. 12 students + 5 chaperones)", free_chaperones(12, 5), 1)
    ok &= check("19 total people (e.g. 14 students + 5 chaperones)", free_chaperones(14, 5), 2)
    ok &= check("20 total people (e.g. 15 students + 5 chaperones)", free_chaperones(15, 5), 2)
    # Real booking rec4YP9ruVPOD90US from the QA walkthrough: 32 students +
    # 5 chaperones = 37 total -> matches the "4 complimentary chaperones"
    # shown on the actual proposal page.
    ok &= check("QA fixture booking (32 students + 5 chaperones)", free_chaperones(32, 5), 4)
    # MIN() cap: formula never grants more free spaces than chaperones present.
    ok &= check("MIN() cap: 90 students + 2 chaperones (ratio would say 10)", free_chaperones(90, 2), 2)

    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
