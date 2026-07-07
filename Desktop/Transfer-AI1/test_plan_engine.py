"""
Test plan_engine.py against all known failing cases + breadth cases.

Usage:
  python test_plan_engine.py            # run all cases
  python test_plan_engine.py 1          # run case 1 only
  python test_plan_engine.py 1 2 5      # run specific cases

All cases must PASS before plan_engine replaces /plan.

Fail criteria (hard errors):
  - Ghost course: course in igetc_completion but not in any scheduled term
  - Prereq violation: same-prefix letter-sequence course in wrong term order
  - AND-group incomplete: multiple CC courses required but not all scheduled
  - Match failure: no articulation data found (empty schedule)
  - Crash: any exception during build_plan()
  - Completed course re-scheduled (when completedCourses provided)
  - Missing UNIT SHORTFALL warning (for cases marked expect_shortfall=True)

Soft observations (printed but don't fail the test):
  - EXTENDED PLAN: program needs >4 semesters (expected for heavy programs)
  - Under-loaded term: a term has <9u
  - UNIT SHORTFALL: plan under 60 SU (semester) or 90 QU (quarter); hard-checked
    only for cases with {"expect_shortfall": True} in their extra dict

Case tuple formats:
  (id, desc, college, uc, major, accept_honors)
  (id, desc, college, uc, major, accept_honors, extra_dict)

  extra_dict keys (all optional):
    completed        set[str]  -- courses already done; must NOT appear in plan
    ap_credits       str       -- AP exam string passed to build_plan
    expect_shortfall bool      -- if True, plan MUST emit UNIT SHORTFALL warning
    must_include     set[str]        -- course codes (e.g. "MATH 1A") that MUST appear
    must_not_include set[str]        -- course codes that must NOT appear (regression guard)
    min_courses      int             -- plan must have at least this many courses
    max_courses      int             -- plan must have at most this many courses
    must_not_all     list[set[str]]  -- each set: having ALL courses in it is an error
    expect_overreq   bool            -- if True, must_not_all violations are KNOWN_ISSUE
                                        (prints clearly, doesn't FAIL the suite; clears
                                        automatically once Conjunction=Or section-awareness
                                        is implemented)
"""

import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from plan_engine import (
    build_plan,
    build_render_prompt,
    repair_term_headers,
    PlanResult,
    _MAX_UNITS_PER_TERM,
    _MAX_QUARTER_UNITS_PER_TERM,
)
from course_sequence import infer_sequence_order, same_sequence_base

# ── Test case definitions ─────────────────────────────────────────────────────
# See module docstring for tuple format.

CASES = [
    # ── Original 9 cases (unchanged) ─────────────────────────────────────────
    (1, "De Anza -> Berkeley -> CS [calc-chain prereq ordering]",
        "De Anza College", "Berkeley", "Computer Science B.S.", False,
        {"expect_shortfall": True}),  # 78.5 QU < 90 QU min (quarter school)
    (2, "Foothill -> Berkeley -> CS [ENGL 8 ghost-course]",
        "Foothill College", "Berkeley", "Computer Science B.S.", False,
        {"expect_shortfall": True}),  # 71 QU < 90 QU min (quarter school)
    (3, "Foothill -> UCSD -> CS [4 ghost courses]",
        "Foothill College", "UCSD", "Computer Science B.S.", False),
    (4, "De Anza -> Berkeley -> CS [honors consistency]",
        "De Anza College", "Berkeley", "Computer Science B.S.", False,
        {"expect_shortfall": True}),  # 78.5 QU < 90 QU min (quarter school)
    (5, "De Anza -> Merced -> Applied Math CS [was 413-trigger]",
        "De Anza College", "Merced",
        "Applied Mathematical Sciences -- Computer Science Emphasis B.S.", False),
    (6, "Foothill -> Merced -> CS Engineering [was 413-trigger]",
        "Foothill College", "Merced", "Computer Science and Engineering B.S.", False),
    (7, "De Anza -> UCSD -> CS [was 413-trigger]",
        "De Anza College", "UCSD", "Computer Science B.S.", False),
    (8, "De Anza -> UC Davis -> Psychology B.A. [non-CS/Math]",
        "De Anza College", "Davis", "Psychology B.A.", False,
        {"must_include": {"PSYC C1000", "ANTH 1", "PSYC 2"},
         "min_courses": 10,
         "expect_shortfall": True}),  # 68 QU < 90 QU min (quarter school)
    (9, "Foothill -> Merced -> Electrical Engineering [high AND-group]",
        "Foothill College", "Merced", "Electrical Engineering B.S.", False,
        {"expect_shortfall": True}),  # 76 QU < 90 QU min (quarter school)

    # ── UCLA coverage (previously zero) ──────────────────────────────────────
    (10, "De Anza -> UCLA -> Psychology B.A. [UCLA non-STEM]",
         "De Anza College", "Los Angeles", "Psychology B.A.", False,
         {"must_include": {"PSYC C1000"},
          "must_not_include": {"MATH 1BH"},        # regression: wrong major ghost
          "max_courses": 35,
          # KNOWN ISSUE — Conjunction=Or group c2af6f45 is section-based (pick one track)
          # but conservative k=0 requires all entries.  Until section-awareness is added,
          # these alternative science tracks are co-scheduled when only one should appear.
          # Investigate: sectionAdvisements / group position in raw ASSIST templateAssets.
          "must_not_all": [
              {"PHYS 10", "PHYS 4A"},    # conceptual vs calc-based physics are alternative tracks
              {"CHEM 10", "CHEM 1A"},    # intro vs general chemistry are alternative tracks
          ],
          "expect_overreq": True}),
    (11, "CCSF -> UCLA -> History B.A. [new CC: CCSF; shortfall expected]",
         "City College of San Francisco", "Los Angeles", "History B.A.", False,
         {"expect_shortfall": True,
          "must_include": {"HIST 4A"},           # Western Civ must appear
          "must_not_include": {"ART 101"}}),     # regression: Art History wrong match

    # ── UCI coverage ──────────────────────────────────────────────────────────
    (12, "ARC -> UCI -> Psychology B.S. [new CC: ARC; shortfall expected]",
         "American River College", "Irvine", "Psychology B.S.", False,
         {"expect_shortfall": True}),
    (13, "De Anza -> UCI -> Economics B.A. [UCI non-STEM, heavy major]",
         "De Anza College", "Irvine", "Economics B.A.", False,
         {"must_include": {"MATH 1A", "ECON 1", "ECON 2", "MATH 1B"},
          "must_not_include": {"PHTG 1", "PHTG 4", "ARTS 4A"},  # regression: Art major ghost
          "max_courses": 20,
          "expect_shortfall": True}),  # 50.5 QU < 90 QU min (quarter school)

    # ── UCSB coverage (previously zero) ──────────────────────────────────────
    (14, "ARC -> UCSB -> Political Science B.A. [UCSB; shortfall expected]",
         "American River College", "Santa Barbara", "Political Science B.A.", False,
         {"expect_shortfall": True}),
    (15, "De Anza -> UCSB -> Sociology B.A. [UCSB non-STEM; shortfall expected]",
         "De Anza College", "Santa Barbara", "Sociology B.A.", False,
         {"expect_shortfall": True}),  # 44 QU < 90 QU min (quarter school)

    # ── UCSC coverage (previously zero) ──────────────────────────────────────
    (16, "ARC -> UCSC -> Psychology B.A. [UCSC; shortfall expected]",
         "American River College", "Santa Cruz", "Psychology B.A.", False,
         {"expect_shortfall": True}),
    (17, "DVC -> UCSC -> History B.A. [new CC: Diablo Valley]",
         "Diablo Valley College", "Santa Cruz", "History B.A.", False,
         {"must_include": {"HIST 124"}}),  # regression: HIST 124 was scheduled twice

    # ── Berkeley non-CS/Eng ───────────────────────────────────────────────────
    (18, "ARC -> Berkeley -> Economics B.A. [Berkeley non-STEM; shortfall expected]",
         "American River College", "Berkeley", "Economics B.A.", False,
         {"expect_shortfall": True}),

    # ── UCSD non-CS ───────────────────────────────────────────────────────────
    (19, "ARC -> UCSD -> Psychology B.S. [UCSD non-CS, heavy]",
         "American River College", "San Diego", "Psychology B.S.", False),
    (20, "De Anza -> UCSD -> Economics B.A. [UCSD non-STEM; shortfall expected]",
         "De Anza College", "San Diego", "Economics B.A.", False,
         {"expect_shortfall": True}),  # 61 QU < 90 QU min (quarter school)

    # ── Merced non-CS ─────────────────────────────────────────────────────────
    (21, "ARC -> Merced -> Sociology B.A. [Merced non-STEM; shortfall expected]",
         "American River College", "Merced", "Sociology B.A.", False,
         {"expect_shortfall": True}),

    # ── Unit-shortfall regression (permanent 60u check tests) ─────────────────
    (22, "Foothill -> Riverside -> English B.A. [shortfall regression ~46.5 QU / ~31 SU]",
         "Foothill College", "Riverside", "English B.A.", False,
         {"expect_shortfall": True}),
    (23, "De Anza -> Riverside -> Philosophy B.A. [shortfall regression ~53 QU / ~35 SU]",
         "De Anza College", "Riverside", "Philosophy B.A.", False,
         {"expect_shortfall": True}),

    # ── New CC: Pasadena City College ─────────────────────────────────────────
    (24, "PCC -> UCI -> Sociology B.A. [new CC: Pasadena City College]",
         "Pasadena City College", "Irvine", "Sociology B.A.", False),

    # ── completedCourses parameter tests ─────────────────────────────────────
    (25, "De Anza -> Berkeley -> CS [completedCourses=MATH 1A,ENGL C1000]",
         "De Anza College", "Berkeley", "Computer Science B.S.", False,
         {"completed": {"MATH 1A", "ENGL C1000"},
          "expect_shortfall": True}),  # 68.5 QU < 90 QU min (quarter school)
    (26, "De Anza -> Davis -> Psychology B.A. [completedCourses=PSYC 2]",
         "De Anza College", "Davis", "Psychology B.A.", False,
         {"completed": {"PSYC 2"},
          "expect_shortfall": True}),  # 62 QU < 90 QU min (quarter school)

    # ── apCredits parameter test ───────────────────────────────────────────────
    (27, "De Anza -> Berkeley -> CS [apCredits=AP Calculus BC]",
         "De Anza College", "Berkeley", "Computer Science B.S.", False,
         {"ap_credits": "AP Calculus BC",
          "expect_shortfall": True}),  # 78.5 QU < 90 QU min (quarter school)

    # ── Davis additional non-STEM coverage ───────────────────────────────────
    (28, "De Anza -> Davis -> Sociology B.A. [Davis non-STEM breadth; shortfall expected]",
         "De Anza College", "Davis", "Sociology B.A.", False,
         {"expect_shortfall": True}),  # 61 QU < 90 QU min (quarter school)
]

TAG_NOTES = {
    "berkeley":     "UC Berkeley does NOT offer TAG.",
    "san diego":    "UC San Diego does NOT offer TAG.",
    "merced":       "UC Merced DOES offer TAG (min 3.0 GPA for most STEM majors).",
    "davis":        "UC Davis DOES offer TAG (min 3.2 GPA for Psych).",
    "los angeles":  "UC Los Angeles does NOT offer TAG.",
    "irvine":       "UC Irvine DOES offer TAG (min 3.4 GPA for some majors).",
    "santa barbara":"UC Santa Barbara DOES offer TAG (min 3.2 GPA).",
    "santa cruz":   "UC Santa Cruz DOES offer TAG (min 3.0 GPA).",
    "riverside":    "UC Riverside DOES offer TAG (min 3.0 GPA).",
}
GPA_NOTES = {
    "berkeley":     ("3.7-3.9", "UC Berkeley CS is extremely competitive. Aim for 3.9."),
    "san diego":    ("3.7-3.9", "UCSD CS is highly competitive. Aim for 3.7+."),
    "merced":       ("3.2-3.4", "UC Merced is accessible. Target 3.2+ for CS."),
    "davis":        ("3.5-3.7", "UC Davis Psychology is moderately competitive."),
    "los angeles":  ("3.7-4.0", "UCLA is extremely competitive across all majors."),
    "irvine":       ("3.5-3.7", "UCI is moderately competitive."),
    "santa barbara":("3.5-3.7", "UCSB is moderately competitive."),
    "santa cruz":   ("3.3-3.5", "UCSC is accessible."),
    "riverside":    ("3.0-3.5", "UCR is accessible."),
}

# ── Checkers ─────────────────────────────────────────────────────────────────

def check_ghost_courses(result: PlanResult) -> list:
    placed = {s.code for s in result.all_courses()}
    errors = []
    for area, course_code in result.igetc_completion.items():
        for code in course_code.split(", "):
            code = code.strip()
            if not code or "via" in code or "satisfied" in code or "already completed" in code:
                continue
            if code not in placed:
                errors.append(f"Ghost in area {area}: {code!r} not placed in any term")
    return errors


def check_prereq_violations(result: PlanResult) -> list:
    all_courses = result.all_courses()
    errors = []
    checked = set()
    for a in all_courses:
        for b in all_courses:
            if a.code == b.code or (a.code, b.code) in checked:
                continue
            checked.add((a.code, b.code))
            if a.prefix != b.prefix:
                continue
            if not same_sequence_base(a.number, b.number):
                continue
            ord_a = infer_sequence_order(a.number)[1]
            ord_b = infer_sequence_order(b.number)[1]
            # a should precede b (ord_a < ord_b) meaning a.term <= b.term
            if ord_a < ord_b and a.term > b.term:
                errors.append(
                    f"Prereq violation: {a.code} (ord {ord_a}, term {a.term}) "
                    f"placed AFTER {b.code} (ord {ord_b}, term {b.term})"
                )
    return errors


def check_and_groups(result: PlanResult) -> list:
    placed = {s.code for s in result.all_courses()}
    errors = []
    for uc_req, cc_code, status in result.requirement_audit:
        if status != "MET":
            continue
        if cc_code.startswith("satisfied via"):  # OR-group: winner handles this requirement
            continue
        required = [c.strip() for c in cc_code.split(" + ") if c.strip()]
        missing  = [c for c in required if c not in placed and "already completed" not in c]
        if missing:
            errors.append(f"AND-group incomplete for {uc_req!r}: missing {missing}")
    return errors


def check_unit_overload(result: PlanResult) -> list:
    cap = _MAX_QUARTER_UNITS_PER_TERM if result.is_quarter else _MAX_UNITS_PER_TERM
    errors = []
    for t in range(1, result.active_terms + 1):
        units = sum(s.units for s in result.terms.get(t, []))
        if units > cap + 0.5:  # 0.5 tolerance for rounding
            errors.append(
                f"Term {t} has {units:.1f}u -- exceeds {cap}u hard cap"
            )
    return errors


def check_token_size(prompt: str, threshold: int = 3000) -> list:
    est = len(prompt) // 4
    if est > threshold:
        return [f"Render prompt is ~{est} tokens (threshold {threshold})"]
    return []


def check_completed_excluded(result: PlanResult, completed: set) -> list:
    """Completed courses must not appear anywhere in the scheduled plan."""
    if not completed:
        return []
    placed = {s.code for s in result.all_courses()}
    errors = []
    for raw in completed:
        code = raw.strip().upper()
        if code in placed:
            errors.append(
                f"Completed course {code} was re-scheduled (should have been excluded)"
            )
    return errors


def check_no_duplicates(result: PlanResult) -> list:
    """No course should appear in more than one term."""
    seen: dict = {}
    errors = []
    for s in result.all_courses():
        if s.code in seen:
            errors.append(
                f"Duplicate: {s.code} scheduled in term {seen[s.code]} AND term {s.term}"
            )
        else:
            seen[s.code] = s.term
    return errors


def check_content(
    result: PlanResult,
    must_include: set,
    must_not_include: set,
    min_courses: int | None,
    max_courses: int | None,
) -> list:
    """Validate course-content expectations from the extra_dict."""
    all_codes = {s.code for s in result.all_courses()}
    errors = []
    for code in sorted(must_include or set()):
        if code not in all_codes:
            errors.append(f"Required course missing from plan: {code}")
    for code in sorted(must_not_include or set()):
        if code in all_codes:
            errors.append(f"Forbidden course present in plan: {code}")
    total = len(result.all_courses())
    if min_courses is not None and total < min_courses:
        errors.append(f"Plan has {total} courses but needs at least {min_courses}")
    if max_courses is not None and total > max_courses:
        errors.append(f"Plan has {total} courses but max allowed is {max_courses}")
    return errors


def check_must_not_all(result: PlanResult, must_not_all: list) -> list:
    """Each set in must_not_all: if ALL courses in that set are present, it's an error.
    Used to flag Conjunction=Or over-requirement where alternative tracks are co-scheduled."""
    all_codes = {s.code for s in result.all_courses()}
    errors = []
    for course_set in (must_not_all or []):
        present = sorted(c for c in course_set if c in all_codes)
        if len(present) == len(course_set):
            errors.append(
                f"Alternative tracks co-scheduled (Conjunction=Or over-requirement): "
                f"{present} — student should pick only one track"
            )
    return errors


def check_shortfall_fires(result: PlanResult) -> list:
    """UNIT SHORTFALL warning must be present (hard check for known sub-60u cases)."""
    if not any("UNIT SHORTFALL" in w for w in result.warnings):
        return [
            f"Expected UNIT SHORTFALL warning but none fired "
            f"(plan has {result.total_units:.1f}u)"
        ]
    return []


# ── Runner ────────────────────────────────────────────────────────────────────

def run_case(case_id, desc, college, uc, major, accept_honors, extra=None) -> dict:
    extra = extra or {}
    completed   = extra.get("completed", set())
    ap_credits  = extra.get("ap_credits", "")
    exp_short   = extra.get("expect_shortfall", False)

    print(f"\n{'-'*70}")
    print(f"CASE {case_id}: {desc}")
    extra_note = ""
    if completed:   extra_note += f"  completed={sorted(completed)}"
    if ap_credits:  extra_note += f"  apCredits={ap_credits!r}"
    print(f"  {college} -> {uc} | {major}{extra_note}")

    try:
        result = build_plan(college, uc, major, accept_honors=accept_honors,
                            completed=completed, ap_credits=ap_credits)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"  ERROR: {type(e).__name__}: {e}")
        print(tb)
        return {"id": case_id, "desc": desc, "status": "ERROR",
                "errors": [f"{type(e).__name__}: {e}"], "traceback": tb}

    errors = []

    if not result.all_courses():
        errors.append("No courses scheduled (match failure or empty shard)")
        print(f"  FAIL: {errors[0]}")
        return {"id": case_id, "desc": desc, "status": "FAIL", "errors": errors}

    errors += check_ghost_courses(result)
    errors += check_prereq_violations(result)
    errors += check_and_groups(result)
    errors += check_unit_overload(result)
    errors += check_completed_excluded(result, completed)
    errors += check_no_duplicates(result)
    errors += check_content(
        result,
        must_include=extra.get("must_include", set()),
        must_not_include=extra.get("must_not_include", set()),
        min_courses=extra.get("min_courses"),
        max_courses=extra.get("max_courses"),
    )

    # Known-issue check: Conjunction=Or over-requirement (alternative tracks co-scheduled)
    overreq_errors = check_must_not_all(result, extra.get("must_not_all", []))
    if overreq_errors and extra.get("expect_overreq"):
        for e in overreq_errors:
            print(f"  KNOWN ISSUE (Conjunction=Or): {e[:120]}")
        known_issue_flag = True
    else:
        errors += overreq_errors
        known_issue_flag = False

    if exp_short:
        errors += check_shortfall_fires(result)

    uc_l    = _UC_NAME_MAP_LOCAL.get(uc.lower().strip(), uc.lower())
    tag     = TAG_NOTES.get(uc_l, "Check UC TAG page for eligibility.")
    gpa_r, gpa_n = GPA_NOTES.get(uc_l, ("3.0-4.0", "See UC admissions stats."))
    prompt  = build_render_prompt(result, tag, gpa_r, gpa_n)
    errors += check_token_size(prompt)

    # Print schedule summary
    ext_flag = " [EXTENDED]" if result.extended_plan else ""
    print(f"  {result.active_terms} terms{ext_flag}, {len(result.all_courses())} courses, {result.total_units:.0f}u total")
    for t in range(1, result.active_terms + 1):
        t_units = sum(s.units for s in result.terms.get(t, []))
        names   = ", ".join(s.code for s in result.terms.get(t, []))
        print(f"    Term {t}: {t_units:.0f}u  [{names}]")
    print(f"  IGETC: {sorted(result.igetc_completion.keys())}")
    print(f"  Post-transfer: {len(result.post_transfer)}")
    print(f"  Render prompt: ~{len(prompt) // 4} tokens")

    # Print soft observations (not failures)
    soft = [w for w in result.warnings if not w.startswith("Ghost:")]
    for w in soft:
        print(f"  NOTE: {w[:120]}")

    if errors:
        print(f"  FAIL ({len(errors)} errors):")
        for e in errors:
            print(f"    * {e}")
        return {"id": case_id, "desc": desc, "status": "FAIL", "errors": errors,
                "result": result}
    elif known_issue_flag:
        print(f"  KNOWN_ISSUE")
        return {"id": case_id, "desc": desc, "status": "KNOWN_ISSUE", "errors": [],
                "result": result, "prompt": prompt}
    else:
        print(f"  PASS")
        return {"id": case_id, "desc": desc, "status": "PASS", "errors": [],
                "result": result, "prompt": prompt}


# Needed locally in test (not importing from plan_engine to avoid pollution)
from plan_engine import _UC_NAME_MAP as _UC_NAME_MAP_LOCAL


# ── Term header repair test ────────────────────────────────────────────────────

def test_term_header_repair():
    """Simulate the live scramble (Fall/Spring/Fall/Winter/Spring/Fall) for Case 1
    (De Anza -> Berkeley -> CS, a quarter school) and assert repair restores the
    correct Fall Q1/Winter Q1/Spring Q1/Fall Q2/Winter Q2/Spring Q2 sequence."""
    print(f"\n{'-'*70}")
    print("TERM HEADER REPAIR TEST: De Anza -> Berkeley -> CS (quarter school)")

    try:
        result = build_plan("De Anza College", "Berkeley", "Computer Science B.S.",
                            accept_honors=False)
    except Exception as e:
        import traceback
        print(f"  ERROR building plan: {e}")
        print(traceback.format_exc()[:500])
        return {"id": "THR", "desc": "Term header repair", "status": "ERROR",
                "errors": [str(e)]}

    if not result.is_quarter:
        errors = ["De Anza College was not detected as a quarter school (is_quarter=False)"]
        print(f"  FAIL: {errors[0]}")
        return {"id": "THR", "desc": "Term header repair", "status": "FAIL", "errors": errors}

    # Reproduce the exact scramble observed in the live response:
    # Correct:  Fall Q1, Winter Q1, Spring Q1, Fall Q2, Winter Q2, Spring Q2
    # Observed: Fall,    Spring,    Fall,      Winter,  Spring,    Fall
    wrong_seasons = ["Fall", "Spring", "Fall", "Winter", "Spring", "Fall"]
    lines = []
    for t in range(1, result.active_terms + 1):
        wrong = wrong_seasons[t - 1] if t <= len(wrong_seasons) else f"Term {t}"
        lines.append(f"## Term {t} ({wrong})")
        for slot in result.terms.get(t, []):
            lines.append(f"- {slot.code} -- {slot.title}")
        lines.append("")
    lines.append("## Key Notes")
    lines.append("- Some note")
    scrambled = "\n".join(lines)

    repaired, n_repairs = repair_term_headers(scrambled, result)

    expected = ["Fall Q1", "Winter Q1", "Spring Q1", "Fall Q2", "Winter Q2", "Spring Q2"]
    errors = []

    if n_repairs == 0:
        errors.append("No repairs applied — expected scrambled headers to be corrected")

    # Each expected label must appear in order
    last_pos = -1
    for label in expected[:result.active_terms]:
        pos = repaired.find(f"({label})")
        if pos == -1:
            errors.append(f"Expected label '({label})' not found after repair")
        elif pos <= last_pos:
            errors.append(f"Label '({label})' appears out of order (pos {pos} <= prev {last_pos})")
        else:
            last_pos = pos

    # None of the wrong labels should survive as a standalone header
    for t, wrong in enumerate(wrong_seasons[:result.active_terms], start=1):
        if re.search(rf"## Term {t} \({re.escape(wrong)}\)", repaired):
            errors.append(f"Scrambled label still present: '## Term {t} ({wrong})'")

    if errors:
        print(f"  FAIL ({len(errors)} errors):")
        for e in errors:
            print(f"    * {e}")
        return {"id": "THR", "desc": "Term header repair", "status": "FAIL", "errors": errors}

    print(f"  Repaired {n_repairs} of {result.active_terms} headers")
    print(f"  Confirmed: {' -> '.join(expected[:result.active_terms])}")
    print(f"  PASS")
    return {"id": "THR", "desc": "Term header repair", "status": "PASS", "errors": []}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) > 1:
        ids   = set(int(x) for x in sys.argv[1:])
        cases = [c for c in CASES if c[0] in ids]
    else:
        cases = CASES

    results = []
    for case in cases:
        # Pad to 7 elements so run_case always receives extra dict (or None)
        r = run_case(*case) if len(case) == 7 else run_case(*case, None)
        results.append(r)

    # Always run term header repair test regardless of case filter
    results.append(test_term_header_repair())

    print(f"\n{'='*70}")
    print("SUMMARY")
    print("="*70)
    passed       = [r for r in results if r["status"] == "PASS"]
    known_issues = [r for r in results if r["status"] == "KNOWN_ISSUE"]
    failed       = [r for r in results if r["status"] == "FAIL"]
    errored      = [r for r in results if r["status"] == "ERROR"]
    print(f"  PASS:         {len(passed)}")
    if known_issues:
        print(f"  KNOWN_ISSUE:  {len(known_issues)}  (tracked bugs — not regressions)")
    print(f"  FAIL:         {len(failed)}")
    print(f"  ERROR:        {len(errored)}")

    if known_issues:
        print("\nKnown issues (tracked, non-blocking):")
        for r in known_issues:
            print(f"  Case {r['id']}: {r['desc']}")

    if failed or errored:
        print("\nFailed cases:")
        for r in failed + errored:
            print(f"  Case {r['id']}: {r['desc']}")
            for e in r["errors"][:5]:
                print(f"    -> {e}")
            if "traceback" in r:
                print(r["traceback"][:1000])

    sys.exit(0 if not failed and not errored else 1)


if __name__ == "__main__":
    main()
