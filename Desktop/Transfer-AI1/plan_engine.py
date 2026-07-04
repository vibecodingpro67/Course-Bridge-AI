"""
Deterministic UC transfer plan builder — plan_engine.py

Replaces LLM-based schedule generation with Python for:
  1. Option resolution  (pick one option per multi-option UC requirement)
  2. IGETC selection    (rule-based, one course per area)
  3. Term bin-packing   (prereq-respecting greedy assignment, 20u/term hard cap)
  4. Compact LLM call   (~600-1200 tokens vs ~12 000 for rendering only)

If all 4 standard terms fill up at 20u/term, courses overflow to terms 5-6
and result.extended_plan is set True with a clear warning.

Entry points
------------
  result = build_plan(college, uc, major, accept_honors=False,
                      completed=None, ap_credits=None)
  for chunk in render_plan_stream(result, tag_note, gpa_range, gpa_note):
      ...

Self-contained — does NOT import from app.py (avoids circular imports
when app.py adds the /plan_v2 route).
"""

from __future__ import annotations

import gzip
import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from course_sequence import infer_sequence_order, same_sequence_base
from advisor import _PLAN_SYSTEM_PROMPT

# ── Replicated data (originally in app.py) ────────────────────────────────────
# Kept here so plan_engine is fully self-contained and importable from app.py
# without creating a circular dependency.

_UC_NAME_MAP = {
    "ucla":           "los angeles",
    "uc la":          "los angeles",
    "los angeles":    "los angeles",
    "ucb":            "berkeley",
    "uc berkeley":    "berkeley",
    "cal":            "berkeley",
    "berkeley":       "berkeley",
    "ucsd":           "san diego",
    "uc san diego":   "san diego",
    "san diego":      "san diego",
    "uci":            "irvine",
    "uc irvine":      "irvine",
    "irvine":         "irvine",
    "ucsb":           "santa barbara",
    "uc santa barbara": "santa barbara",
    "santa barbara":  "santa barbara",
    "ucd":            "davis",
    "uc davis":       "davis",
    "davis":          "davis",
    "ucsc":           "santa cruz",
    "uc santa cruz":  "santa cruz",
    "santa cruz":     "santa cruz",
    "ucr":            "riverside",
    "uc riverside":   "riverside",
    "riverside":      "riverside",
    "ucm":            "merced",
    "uc merced":      "merced",
    "merced":         "merced",
}

_UC_SHARD_MAP = {
    "los angeles":   "Los_Angeles",
    "berkeley":      "Berkeley",
    "san diego":     "San_Diego",
    "irvine":        "Irvine",
    "santa barbara": "Santa_Barbara",
    "davis":         "Davis",
    "santa cruz":    "Santa_Cruz",
    "riverside":     "Riverside",
    "merced":        "Merced",
}

_IGETC_REQUIRED = [
    ("1A", "English Composition",                      1),
    ("1B", "Critical Thinking / English Composition",  1),
    ("2A", "Mathematical Concepts",                    1),
    ("3A", "Arts",                                     1),
    ("3B", "Humanities",                               1),
    ("4",  "Social & Behavioral Sciences",             3),
    ("5A", "Physical Sciences",                        1),
    ("5B", "Biological Sciences",                      1),
    ("5C", "Laboratory Science (LAB course required)", 1),
    ("6",  "Languages Other Than English",             1),
]

_ART_SHARDS: dict = {}
_IGETC_CACHE = None
_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _load_uc_shard(uc_canonical: str) -> dict:
    shard_name = _UC_SHARD_MAP.get(uc_canonical)
    if not shard_name:
        return {}
    if shard_name in _ART_SHARDS:
        return _ART_SHARDS[shard_name]
    base = os.path.join(_DATA_DIR, f"articulations_{shard_name}.json")
    for path in (base + ".gz", base):
        if not os.path.exists(path):
            continue
        try:
            opener = gzip.open if path.endswith(".gz") else open
            with opener(path, "rt", encoding="utf-8") as f:
                shard = json.load(f)
            _ART_SHARDS[shard_name] = shard
            return shard
        except Exception:
            break
    _ART_SHARDS[shard_name] = {}
    return {}


def _load_igetc() -> dict:
    global _IGETC_CACHE
    if _IGETC_CACHE is not None:
        return _IGETC_CACHE
    base = os.path.join(_DATA_DIR, "igetc_map.json")
    for path in (base + ".gz", base):
        if not os.path.exists(path):
            continue
        try:
            opener = gzip.open if path.endswith(".gz") else open
            with opener(path, "rt", encoding="utf-8") as f:
                _IGETC_CACHE = json.load(f)
            return _IGETC_CACHE
        except Exception:
            break
    _IGETC_CACHE = {}
    return _IGETC_CACHE


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class CourseSlot:
    prefix: str
    number: str
    title: str
    units: float
    term: int = 0
    tags: list = field(default_factory=list)
    uc_reqs: list = field(default_factory=list)
    explicit_prereqs: list = field(default_factory=list)

    @property
    def code(self) -> str:
        return f"{self.prefix} {self.number}"

    @property
    def is_honors(self) -> bool:
        return self.number.upper().endswith("H")

    def tag_str(self) -> str:
        return " / ".join(self.tags) if self.tags else ""


@dataclass
class PlanResult:
    college: str
    uc: str
    major: str
    terms: dict = field(default_factory=lambda: {t: [] for t in range(1, 7)})
    igetc_completion: dict = field(default_factory=dict)
    requirement_audit: list = field(default_factory=list)
    post_transfer: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    total_units: float = 0.0
    active_terms: int = 4      # how many terms actually have courses
    extended_plan: bool = False  # True when courses spill past term 4
    summer_overflow: bool = False  # True when T5 is <10u (recommend as summer session, not extra year)

    def all_courses(self) -> list:
        out = []
        for t in range(1, self.active_terms + 1):
            out.extend(self.terms.get(t, []))
        return out


# ── Term naming ───────────────────────────────────────────────────────────────

_MAX_TERMS_HARD = 8      # absolute ceiling — even the heaviest programs top out here
_MAX_UNITS_PER_TERM = 20.0    # hard cap per term — never create a 25u term

_TERMS_PER_YEAR = {
    1: "Fall",
    2: "Spring",
    3: "Fall",
    4: "Spring",
    5: "Extended / Semester 5",
    6: "Extended / Semester 6",
    7: "Extended / Semester 7",
    8: "Extended / Semester 8",
}


# ── Calc-chain detection ───────────────────────────────────────────────────────

_CALC_PATTERNS = [
    ("calc1",  re.compile(r'\bcalculus\s+i\b', re.I),                   lambda t: 'ii' not in t and 'iii' not in t),
    ("calc2",  re.compile(r'\bcalculus\s+ii\b', re.I),                   lambda t: 'iii' not in t),
    ("calc3",  re.compile(r'(\bcalculus\s+iii\b|multivariable)', re.I),  lambda _: True),
    ("diffeq", re.compile(r'differential\s+eq', re.I),                   lambda _: True),
    ("linalg", re.compile(r'linear\s+algebra', re.I),                    lambda _: True),
]

def _calc_role(title: str) -> Optional[str]:
    tl = title.lower()
    for role, pat, extra in _CALC_PATTERNS:
        if pat.search(tl) and extra(tl):
            return role
    return None


# ── Fuzzy-match helpers ────────────────────────────────────────────────────────

# Words that appear in nearly every CC name and must NOT score on their own.
_CC_STOP_WORDS = {"college", "community"}


def _prefix_hit(key_word: str, user_str: str) -> bool:
    """True if key_word matches user_str exactly (substring) or via 5-char prefix.

    The prefix check handles single-character typos at the end of a word
    (e.g. 'foothil' vs 'foothill', 'anzaa' vs 'anza' is caught by substring).
    """
    if key_word in user_str:
        return True
    if len(key_word) >= 5 and key_word[:5] in user_str:
        return True
    return False


def _cc_names_related(user_college: str, matched_cc: str) -> bool:
    """True when user_college and matched_cc refer to the same institution.

    Used as a sanity check: if the shard fuzzy-match found major-prep data
    but IGETC came back empty, verify the matched CC name overlaps the user's
    input before returning a partial plan.
    """
    user_l  = user_college.lower()
    match_l = matched_cc.lower()
    unique_m = [w for w in match_l.split() if len(w) >= 4 and w not in _CC_STOP_WORDS]
    if not unique_m:
        return False
    for mw in unique_m:
        if _prefix_hit(mw, user_l):
            return True
    return False


# ── CC-side prerequisite chains ───────────────────────────────────────────────
# When a CC course is chosen to satisfy a UC requirement, its own internal
# prerequisite chain at the CC may not be captured in ASSIST data.  This table
# records those chains for known colleges so plan_engine can inject the missing
# courses automatically.
#
# Key:   (college_name_lower, prefix_upper, number_upper) of the UC-required CC course
# Value: dict with two keys:
#   "inject"         – ordered list of (prefix, number, title, units, [explicit_prereq_codes])
#                      to inject before the trigger course.  Earlier entries in the
#                      list are prerequisites of later ones unless explicit_prereq_codes
#                      is set (cross-series dependency).
#   "trigger_prereqs"– list of course codes to set as explicit_prereqs on the trigger
#                      course itself (cross-prefix deps: e.g. PHYS → ENGR).
_CC_PREREQ_CHAINS: dict = {
    # De Anza CIS 22C: needs CIS 22A → CIS 22B first.
    # same_sequence_base("22A","22B","22C") all True, so sequence detection
    # handles 22A→22B→22C ordering automatically once they're injected.
    ("de anza college", "CIS", "22C"): {
        "inject": [
            ("CIS", "22A", "Introduction to Programming (Python)", 4.5, []),
            ("CIS", "22B", "C++ Programming and Data Structures", 4.5, []),
        ],
        "trigger_prereqs": [],
    },
    ("de anza college", "CIS", "22CH"): {
        "inject": [
            ("CIS", "22A", "Introduction to Programming (Python)", 4.5, []),
            ("CIS", "22B", "C++ Programming and Data Structures", 4.5, []),
        ],
        "trigger_prereqs": [],
    },
    # De Anza CIS 26B: intro path is CIS 22A (intro Python) → CIS 26A (C programming).
    # 22A→26A is cross-series (numeric 22 vs 26) so explicit_prereqs required on 26A.
    # 26A→26B is same-series so sequence detection handles it.
    ("de anza college", "CIS", "26B"): {
        "inject": [
            ("CIS", "22A", "Introduction to Programming (Python)", 4.5, []),
            ("CIS", "26A", "C Programming Fundamentals", 4.5, ["CIS 22A"]),
        ],
        "trigger_prereqs": [],
    },
    # De Anza ENGR 37: requires PHYS 4B (concurrent) and MATH 1D (concurrent).
    # PHYS 4A→4B: sequence detection handles ordering (same base 4, A<B).
    # MATH 1C→1D: sequence detection handles ordering (same base 1, C<D).
    # ENGR 37 itself needs explicit cross-prefix deps on PHYS 4B and MATH 1D.
    # PHYS 4A also satisfies IGETC Area 5A (it IS in De Anza's 5A list), so it
    # double-labels automatically once it's in scheduled_keys — no PHYS 10 needed.
    ("de anza college", "ENGR", "37"): {
        "inject": [
            ("PHYS", "4A", "Physics for Scientists and Engineers: Mechanics", 5.0, ["MATH 1A"]),
            ("MATH", "1D", "Calculus IV", 5.0, []),
            ("PHYS", "4B", "Physics for Scientists and Engineers: Electricity and Magnetism", 5.0, []),
        ],
        "trigger_prereqs": ["PHYS 4B", "MATH 1D"],
    },
}

# UC requirement OR groups — within each frozenset only ONE needs to be
# satisfied.  When multiple members appear in a shard we keep the cheapest
# CC path (fewest total units) and mark the rest as "satisfied via <winner>".
# Key: normalized UC campus name (matches _UC_NAME_MAP values).
_UC_REQ_OR_GROUPS: list[tuple[str, frozenset]] = [
    # Berkeley CS / EECS: "MATH 54 or EECS 16A or MATH 56"
    ("berkeley", frozenset({("MATH", "54"), ("EECS", "16A"), ("MATH", "56")})),
]


def _inject_cc_prereqs(
    major_courses: list,
    college: str,
    completed_keys: set,
) -> None:
    """
    For each course in major_courses, check whether it has a known CC-side
    prerequisite chain.  Missing prerequisite courses are prepended to
    major_courses and tagged 'CC Prerequisite'.  explicit_prereqs is set on
    injected courses (for cross-series deps) and on the trigger course itself
    (for cross-prefix deps like PHYS 4B → ENGR 37).
    """
    college_key = college.lower().strip()
    existing = {(s.prefix.upper(), s.number.upper()) for s in major_courses}
    new_slots: list = []

    for slot in list(major_courses):
        chain_key = (college_key, slot.prefix.upper(), slot.number.upper())
        chain_data = _CC_PREREQ_CHAINS.get(chain_key)
        if not chain_data:
            continue

        for prefix, number, title, units, slot_explicit_prereqs in chain_data["inject"]:
            k = (prefix.upper(), number.upper())
            if k in existing or (prefix, number) in completed_keys:
                continue
            prereq_slot = CourseSlot(
                prefix=prefix, number=number, title=title, units=units,
                tags=["CC Prerequisite"],
                explicit_prereqs=list(slot_explicit_prereqs),
            )
            new_slots.append(prereq_slot)
            existing.add(k)

        for code in chain_data.get("trigger_prereqs", []):
            if code not in slot.explicit_prereqs:
                slot.explicit_prereqs.append(code)

    # Prepend so injected courses are available to sequence detection
    for s in reversed(new_slots):
        major_courses.insert(0, s)


# ── Option resolution ─────────────────────────────────────────────────────────

def _resolve_major_prep(
    arts: list,
    accept_honors: bool,
    completed: set,
    uc_normalized: str = "",
) -> tuple[list, list, list]:
    """
    For each UC articulation entry, pick one option group deterministically.
    Honors consistency is automatic: once a non-honors course is committed,
    later options with only the honors version have less overlap and lose.

    OR-group pre-pass: when multiple UC requirements in the shard are genuine
    alternatives (e.g. MATH 54 or EECS 16A at Berkeley), only the cheapest
    CC path is scheduled; the rest are marked MET via the winner.
    """
    # ── OR-group pre-pass ─────────────────────────────────────────────────────
    skip_uc_keys: dict = {}   # (p,n) -> winner (p,n)
    for group_uc, or_group in _UC_REQ_OR_GROUPS:
        if group_uc != uc_normalized:
            continue
        members: list = []
        for art in arts:
            uc_c = art.get("uc", {})
            key  = (uc_c.get("p","").upper(), uc_c.get("n","").upper())
            if key not in or_group:
                continue
            valid = [g for g in art.get("cc", []) if g]
            if not accept_honors:
                nh = [g for g in valid if not all(
                    c.get("n","").upper().endswith("H") for c in g
                )]
                if nh:
                    valid = nh
            cost = min(
                (sum(float(c.get("u", 3) or 3) for c in g) for g in valid),
                default=999.0,
            )
            members.append((key, cost))
        if len(members) <= 1:
            continue
        winner = min(members, key=lambda x: x[1])[0]
        for key, _ in members:
            if key != winner:
                skip_uc_keys[key] = winner
    # ─────────────────────────────────────────────────────────────────────────

    committed: dict = {}
    audit_rows = []
    post_transfer = []

    for art in arts:
        uc_c      = art.get("uc", {})
        uc_key    = (uc_c.get("p","").upper(), uc_c.get("n","").upper())
        uc_str    = f"{uc_c.get('p','')} {uc_c.get('n','')} - {uc_c.get('t','')}"

        if uc_key in skip_uc_keys:
            winner = skip_uc_keys[uc_key]
            audit_rows.append((uc_str, f"satisfied via {winner[0]} {winner[1]}", "MET"))
            continue
        cc_groups = art.get("cc", [])
        valid_groups = [g for g in cc_groups if g]

        if not valid_groups:
            post_transfer.append(uc_str)
            audit_rows.append((uc_str, "-", "POST-TRANSFER"))
            continue

        if not accept_honors:
            filtered = [g for g in valid_groups if not all(
                c.get("n", "").upper().endswith("H") for c in g
            )]
            if filtered:
                valid_groups = filtered

        def _overlap(grp):
            return sum(1 for c in grp if (c.get("p",""), c.get("n","")) in committed)

        def _honors_count(grp):
            return sum(1 for c in grp if c.get("n", "").upper().endswith("H"))

        if accept_honors:
            chosen = max(valid_groups, key=lambda grp: (_overlap(grp), _honors_count(grp)))
        else:
            chosen = max(valid_groups, key=_overlap)

        cc_codes = []
        for c in chosen:
            key = (c.get("p",""), c.get("n",""))
            if key in completed:
                cc_codes.append(f"{key[0]} {key[1]} (already completed)")
                continue
            if key not in committed:
                try:
                    units = float(c.get("u", 3) or 3)
                except (TypeError, ValueError):
                    units = 3.0
                slot = CourseSlot(
                    prefix=c.get("p",""),
                    number=c.get("n",""),
                    title=c.get("t",""),
                    units=units,
                    tags=["Required Major Prep"],
                    uc_reqs=[uc_str],
                )
                committed[key] = slot
            else:
                committed[key].uc_reqs.append(uc_str)
            cc_codes.append(f"{key[0]} {key[1]}")

        audit_rows.append((uc_str, " + ".join(cc_codes), "MET"))

    return list(committed.values()), audit_rows, post_transfer


# ── IGETC selection ───────────────────────────────────────────────────────────

def _select_igetc(
    college: str,
    scheduled_keys: set,
    accept_honors: bool,
) -> tuple[list, dict]:
    data = _load_igetc()
    if not data:
        return [], {}

    by_school = data.get("bySchool", {})
    school_key = next((k for k in by_school if k.lower() == college.lower()), None)
    if not school_key:
        school_key = next((k for k in by_school if college.lower() in k.lower()), None)
    if not school_key:
        return [], {}

    by_area = by_school[school_key].get("byArea", {})
    lab_keys = {(c.get("prefix",""), c.get("number","")) for c in by_area.get("5C", [])}

    igetc_courses: list[CourseSlot] = []
    area_assignments: dict = {}
    five_b_has_lab = False

    for area_code, area_name, _needed in _IGETC_REQUIRED:
        if area_code == "5C":
            if five_b_has_lab:
                area_assignments["5C"] = area_assignments.get("5B", "via 5B LAB")
            continue

        courses = by_area.get(area_code, [])
        if not courses:
            continue

        # Major prep double-label
        matches = [c for c in courses if (c.get("prefix",""), c.get("number","")) in scheduled_keys]
        if matches:
            m = matches[0]
            code = f"{m.get('prefix','')} {m.get('number','')}"
            area_assignments[area_code] = code
            if area_code in ("5A", "5B"):
                mk = (m.get("prefix",""), m.get("number",""))
                if mk in lab_keys:
                    five_b_has_lab = True
            continue

        def _ok(c):
            pfx = c.get("prefix","").upper()
            ttl = c.get("title","").upper()
            if pfx.startswith("ESL") or "ENGLISH AS A SECOND" in ttl:
                return False
            if not accept_honors and c.get("number","").upper().endswith("H"):
                return False
            return True

        unique = []
        seen = set()
        for c in courses:
            if not _ok(c):
                continue
            k = (c.get("prefix",""), c.get("number",""))
            if k not in seen:
                seen.add(k)
                unique.append(c)
        if not unique:
            continue

        if area_code == "1B":
            unique.sort(key=lambda c: (0 if c.get("prefix","").upper().startswith("ENGL") else 1))
        if area_code == "5B":
            unique.sort(key=lambda c: (0 if (c.get("prefix",""), c.get("number","")) in lab_keys else 1))

        if area_code == "4":
            picks = [c for c in unique if (c.get("prefix",""), c.get("number","")) not in scheduled_keys][:3]
            codes = []
            for c in picks:
                try:
                    units = float(c.get("units", 3) or 3)
                except (TypeError, ValueError):
                    units = 3.0
                slot = CourseSlot(
                    prefix=c.get("prefix",""),
                    number=c.get("number",""),
                    title=c.get("title",""),
                    units=units,
                    tags=["IGETC Area 4"],
                )
                igetc_courses.append(slot)
                codes.append(slot.code)
            area_assignments["4"] = ", ".join(codes)
            continue

        pick = unique[0]
        pk   = (pick.get("prefix",""), pick.get("number",""))
        try:
            units = float(pick.get("units", 3) or 3)
        except (TypeError, ValueError):
            units = 3.0
        slot = CourseSlot(
            prefix=pick.get("prefix",""),
            number=pick.get("number",""),
            title=pick.get("title",""),
            units=units,
            tags=[f"IGETC Area {area_code}"],
        )
        igetc_courses.append(slot)
        area_assignments[area_code] = slot.code
        if area_code in ("5A","5B") and pk in lab_keys:
            five_b_has_lab = True

    return igetc_courses, area_assignments


# ── Term bin-packing ──────────────────────────────────────────────────────────

def _assign_terms(
    major_courses: list,
    igetc_courses: list,
    major: str,
) -> tuple[dict, dict]:
    """
    Greedy term bin-packing with prereq constraints and 20u/term hard cap.

    Number of terms is computed from total unit load so no term ever exceeds
    the cap: max_terms = ceil(total_units / 20), capped at _MAX_TERMS_HARD.
    Returns: (terms_dict, term_units_dict)
    """
    import math

    max_units = _MAX_UNITS_PER_TERM

    # Pre-calculate needed terms from total unit load so the cap is never breached
    total_u   = sum(s.units for s in major_courses + igetc_courses)
    max_terms = max(4, min(math.ceil(total_u / max_units), _MAX_TERMS_HARD))

    terms: dict      = {t: []   for t in range(1, max_terms + 1)}
    term_units: dict = {t: 0.0  for t in range(1, max_terms + 1)}

    def _place(slot: CourseSlot, term: int):
        terms[term].append(slot)
        term_units[term] += slot.units
        slot.term = term

    # Pass 1: lock calc chain to terms 1-4 in order
    calc_assigned: dict = {}
    unassigned_major = []
    for slot in major_courses:
        role = _calc_role(slot.title)
        if role and role not in calc_assigned:
            calc_assigned[role] = slot
        else:
            unassigned_major.append(slot)

    role_order = ["calc1", "calc2", "calc3", "diffeq", "linalg"]
    present_roles = [r for r in role_order if r in calc_assigned]
    for i, role in enumerate(present_roles):
        term = min(i + 1, 4)   # calc chain stays in terms 1-4
        _place(calc_assigned[role], term)

    # Pass 2: remaining major prep — topological order respecting both
    # sequence-based (same-prefix) and explicit (cross-prefix) prereqs.
    from collections import defaultdict, deque
    seq_groups: dict = defaultdict(list)
    for slot in unassigned_major:
        key_order = infer_sequence_order(slot.number)
        numeric   = key_order[0]
        lprefix   = key_order[2]
        seq_key   = (slot.prefix, lprefix, numeric) if key_order[1] >= 0 else (slot.prefix, slot.number)
        seq_groups[seq_key].append(slot)

    ordered_major: list = []
    for grp in seq_groups.values():
        ordered_major.extend(sorted(grp, key=lambda s: infer_sequence_order(s.number)))

    # Topological sort within ordered_major so cross-prefix explicit deps
    # (e.g. PHYS 4B must be placed before ENGR 37) are processed in the right order.
    _code_map = {s.code: s for s in ordered_major}
    _dep_in: dict = defaultdict(int)
    _dep_adj: dict = defaultdict(list)
    for slot in ordered_major:
        for pc in slot.explicit_prereqs:
            if pc in _code_map:
                _dep_adj[pc].append(slot.code)
                _dep_in[slot.code] += 1
        for other in ordered_major:
            if other.code == slot.code or other.prefix != slot.prefix:
                continue
            if not same_sequence_base(other.number, slot.number):
                continue
            o_ord = infer_sequence_order(other.number)[1]
            s_ord = infer_sequence_order(slot.number)[1]
            if 0 <= o_ord < s_ord:
                _dep_adj[other.code].append(slot.code)
                _dep_in[slot.code] += 1

    _q = deque(s for s in ordered_major if _dep_in.get(s.code, 0) == 0)
    topo_major: list = []
    while _q:
        s = _q.popleft()
        topo_major.append(s)
        for dep_code in _dep_adj.get(s.code, []):
            _dep_in[dep_code] -= 1
            if _dep_in[dep_code] == 0:
                _q.append(_code_map[dep_code])
    # Cycle guard: append any stragglers
    _placed = {s.code for s in topo_major}
    topo_major.extend(s for s in ordered_major if s.code not in _placed)

    # Include calc-assigned courses so successor detection works across the whole list
    all_slots_for_pred = list(calc_assigned.values()) + topo_major

    for slot in topo_major:
        preds = _find_predecessors(slot, all_slots_for_pred)
        t     = _earliest_valid_term(slot, preds, term_units, max_units, max_terms)
        _place(slot, t)

    # Pass 3: IGETC courses — prefer standard terms (1-4) first, then extended.
    # Track placed IGETC area terms to enforce 1A-before-1B ordering.
    igetc_area_term: dict = {}   # area_code -> term where it was placed

    def _igetc_min_term(slot: CourseSlot) -> int:
        """Return earliest allowed term for this IGETC slot."""
        for tag in slot.tags:
            if tag == "IGETC Area 1B":
                return igetc_area_term.get("1A", 1) + 1  # 1B must come strictly after 1A
        return 1

    def _record_igetc_area(slot: CourseSlot, t: int):
        for tag in slot.tags:
            if tag.startswith("IGETC Area "):
                igetc_area_term[tag.split("IGETC Area ")[1]] = t

    for slot in igetc_courses:
        placed = False
        min_t  = _igetc_min_term(slot)
        # Try standard terms in load order, respecting min_t
        for t in sorted(range(1, 5), key=lambda t: term_units[t]):
            if t < min_t:
                continue
            if term_units[t] + slot.units <= max_units:
                _place(slot, t)
                _record_igetc_area(slot, t)
                placed = True
                break
        if not placed and max_terms > 4:
            # Try extended terms with cap
            for t in sorted(range(5, max_terms + 1), key=lambda t: term_units[t]):
                if t < min_t:
                    continue
                if term_units[t] + slot.units <= max_units:
                    _place(slot, t)
                    _record_igetc_area(slot, t)
                    placed = True
                    break
        if not placed:
            # Prefer adding a new term over overloading an existing one
            if max_terms < _MAX_TERMS_HARD:
                max_terms += 1
                terms[max_terms] = []
                term_units[max_terms] = 0.0
                _place(slot, max_terms)
                _record_igetc_area(slot, max_terms)
            else:
                # At hard ceiling — put in least-loaded term (cap breached by ≤1 course)
                t = min(range(1, max_terms + 1), key=lambda t: term_units[t])
                _place(slot, t)
                _record_igetc_area(slot, t)

    return terms, term_units


def _find_predecessors(slot: CourseSlot, all_slots: list) -> list:
    preds = []
    explicit = set(slot.explicit_prereqs)
    for other in all_slots:
        if other.code == slot.code:
            continue
        # Explicit cross-prefix/cross-series dependency (e.g. PHYS 4B → ENGR 37)
        if explicit and other.code in explicit:
            preds.append(other)
            continue
        # Sequence-based within-prefix ordering (e.g. MATH 1C → MATH 1D)
        if other.prefix != slot.prefix:
            continue
        if not same_sequence_base(other.number, slot.number):
            continue
        other_ord = infer_sequence_order(other.number)[1]
        slot_ord  = infer_sequence_order(slot.number)[1]
        if 0 <= other_ord < slot_ord:
            preds.append(other)
    return preds


def _earliest_valid_term(
    slot: CourseSlot,
    predecessors: list,
    term_units: dict,
    max_units: float,
    max_terms: int,
) -> int:
    min_term = 1
    for pred in predecessors:
        if pred.term > 0:
            min_term = max(min_term, pred.term + 1)
    min_term = min(min_term, max_terms)

    for t in range(min_term, max_terms + 1):
        if term_units[t] + slot.units <= max_units:
            return t
    # All terms overflow — put in least-loaded term >= min_term
    return min(range(min_term, max_terms + 1), key=lambda t: term_units[t])


# ── Double-label ──────────────────────────────────────────────────────────────

def _apply_double_labels(result: PlanResult):
    for area_code, course_code in result.igetc_completion.items():
        for t in range(1, result.active_terms + 1):
            for slot in result.terms.get(t, []):
                if slot.code == course_code and f"IGETC Area {area_code}" not in slot.tags:
                    slot.tags.append(f"IGETC Area {area_code}")


# ── Main entry point ──────────────────────────────────────────────────────────

def build_plan(
    college: str,
    uc: str,
    major: str,
    accept_honors: bool = False,
    completed: set = None,
    ap_credits: str = "",
) -> PlanResult:
    if completed is None:
        completed = set()
    completed_keys: set = set()
    for item in completed:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            completed_keys.add((str(item[0]).strip(), str(item[1]).strip()))
        elif isinstance(item, str):
            parts = item.strip().split()
            if len(parts) >= 2:
                completed_keys.add((parts[0], parts[1]))

    uc_l  = _UC_NAME_MAP.get(uc.lower().strip(), uc.lower())
    shard = _load_uc_shard(uc_l)
    if not shard:
        r = PlanResult(college=college, uc=uc, major=major)
        r.warnings.append(f"No shard data found for UC: {uc}")
        return r

    # Fuzzy key match — stop-word filtered, prefix-aware
    # _CC_STOP_WORDS ("college", "community") are excluded from cc_words so
    # generic inputs like "Nonexistent Community College" don't score.
    # Threshold 3.0 requires the CC name OR the major to have a real hit.
    college_l = college.lower()
    major_l   = major.lower()
    best_score, best_key = 0.0, None
    for key in shard:
        if key.startswith("_"):
            continue
        parts = key.split("__")
        if len(parts) < 3:
            continue
        cc_l_k  = parts[0].replace("_", " ").lower()
        maj_l_k = "__".join(parts[2:]).replace("_", " ").lower()
        cc_words  = [w for w in cc_l_k.split()  if len(w) >= 3 and w not in _CC_STOP_WORDS]
        maj_words = [w for w in maj_l_k.split() if len(w) >= 4]
        cc_hit  = sum(1 for w in cc_words  if _prefix_hit(w, college_l)) / max(len(cc_words), 1)
        maj_hit = sum(1 for w in maj_words if _prefix_hit(w, major_l))   / max(len(maj_words), 1)
        score = cc_hit * 5 + maj_hit * 5
        if score > best_score:
            best_score = score
            best_key   = key

    if not best_key or best_score < 3.0:
        r = PlanResult(college=college, uc=uc, major=major)
        r.warnings.append(f"No articulation data found for {college} -> {uc} | {major}")
        return r

    arts   = shard[best_key]
    result = PlanResult(college=college, uc=uc, major=major)

    major_courses, audit_rows, post_transfer = _resolve_major_prep(
        arts, accept_honors, completed_keys, uc_normalized=uc_l
    )
    result.requirement_audit = audit_rows
    result.post_transfer     = post_transfer

    # Use matched CC name from shard key for IGETC lookup so typos in the
    # user's college string still resolve to the correct IGETC school entry.
    matched_cc_name = best_key.split("__")[0].replace("_", " ")

    # Inject CC-side prerequisite chains (e.g. CIS 22A→26A before CIS 26B,
    # PHYS 4A→4B and MATH 1D before ENGR 37).  Must run before scheduled_keys
    # is built so injected courses (like PHYS 4A) can double-label IGETC areas.
    _inject_cc_prereqs(major_courses, matched_cc_name, completed_keys)

    scheduled_keys = {(s.prefix, s.number) for s in major_courses}
    igetc_courses, area_assignments = _select_igetc(matched_cc_name, scheduled_keys, accept_honors)
    result.igetc_completion = area_assignments

    # Sanity check: if major prep was found but IGETC is empty, the shard
    # match may have slipped past the threshold on a marginal score.
    # Verify the matched CC name loosely matches the user's input before
    # returning a partial plan.
    if major_courses and not area_assignments:
        if not _cc_names_related(college, matched_cc_name):
            r = PlanResult(college=college, uc=uc, major=major)
            r.warnings.append(f"No articulation data found for {college} -> {uc} | {major}")
            return r

    result.terms, _ = _assign_terms(major_courses, igetc_courses, major)

    # Compute how many terms have courses
    last_used = 4
    for t in range(_MAX_TERMS_HARD, 0, -1):
        if result.terms.get(t):
            last_used = t
            break
    result.active_terms  = last_used
    result.extended_plan = last_used > 4

    _apply_double_labels(result)

    result.total_units = sum(s.units for s in result.all_courses())
    _sanity_check(result)
    return result


def _sanity_check(result: PlanResult):
    # Ghost course check
    placed = {s.code for s in result.all_courses()}
    for area_code, course_code in result.igetc_completion.items():
        for code in course_code.split(", "):
            code = code.strip()
            if code and "via" not in code and "satisfied" not in code and code not in placed:
                result.warnings.append(
                    f"Ghost: {code} listed in IGETC area {area_code} but not placed in any term."
                )

    # Extended plan warning
    if result.extended_plan:
        t5_units = sum(s.units for s in result.terms.get(5, []))
        overflow_light = result.active_terms == 5 and t5_units < 10.0
        result.summer_overflow = overflow_light
        if overflow_light:
            t5_slots = result.terms.get(5, [])
            courses_str = ", ".join(s.code for s in t5_slots)
            if len(t5_slots) == 1:
                tail = "Most transfer students handle this as a single summer course between Year 1 and Year 2."
            else:
                tail = "Most transfer students handle these as summer courses between Year 1 and Year 2."
            result.warnings.append(
                f"SUMMER SESSION: This plan fits in 4 regular semesters plus one summer session "
                f"({courses_str}, {t5_units:.0f}u). {tail}"
            )
        else:
            extra = result.active_terms - 4
            result.warnings.append(
                f"EXTENDED PLAN: {result.major} at {result.uc} requires "
                f"{result.active_terms} semesters of preparation ({extra} beyond the standard "
                f"4-semester / 2-year timeline). This program is unusually heavy. "
                f"Students typically need summer coursework or an extra year at CC."
            )

    # UC 60-unit minimum transferable unit check
    _UC_MIN_UNITS = 60.0
    if result.total_units < _UC_MIN_UNITS:
        shortfall = _UC_MIN_UNITS - result.total_units
        result.warnings.append(
            f"UNIT SHORTFALL: This plan totals {result.total_units:.0f} transferable units, "
            f"which is {shortfall:.0f}u below the UC minimum of 60 semester units required "
            f"for transfer eligibility. Add {shortfall:.0f}u of transferable electives "
            f"(e.g., additional GE courses, language courses, or major-adjacent electives) "
            f"before applying."
        )

    # Under-loaded term check (light GE-only semesters are suspicious)
    for t in range(1, result.active_terms + 1):
        if result.summer_overflow and t == 5:
            continue  # summer session can legitimately be 1-2 courses
        units = sum(s.units for s in result.terms.get(t, []))
        if units > 0 and units < 9.0:
            result.warnings.append(
                f"Term {t} has only {units:.0f} units — likely needs additional GE electives."
            )


# ── Compact rendering prompt ──────────────────────────────────────────────────

def build_render_prompt(
    result: PlanResult,
    tag_note: str,
    gpa_range: str,
    gpa_note: str,
    mode: str = "competitive",
) -> str:
    lines = [
        "Render this pre-computed UC transfer plan into the exact output format "
        "from your system instructions. DO NOT change any course, term, unit count, "
        "status, or IGETC assignment. Copy all values verbatim.\n",
        f"Student: {result.college} -> {result.uc} | {result.major}\n",
    ]

    if result.extended_plan and not result.summer_overflow:
        extra = result.active_terms - 4
        lines.append(
            f"WARNING: This is an EXTENDED PLAN requiring {result.active_terms} semesters "
            f"({extra} beyond the standard 4). Terms 5+ represent additional semesters. "
            "Include a prominent note in Key Notes that this program requires more than "
            "the standard 2-year CC timeline and students should plan for summer sessions "
            "or a 3rd year at CC.\n"
        )
    elif result.summer_overflow:
        t5_slots = result.terms.get(5, [])
        t5_units = sum(s.units for s in t5_slots)
        courses_str = ", ".join(s.code for s in t5_slots)
        if len(t5_slots) == 1:
            summer_tail = (
                "the summer course is optional-but-recommended and most students complete it "
                "between Year 1 and Year 2 without extending their timeline."
            )
        else:
            summer_tail = (
                "the summer session courses are optional-but-recommended and most students "
                "complete them between Year 1 and Year 2 without extending their timeline."
            )
        lines.append(
            f"NOTE: Term 5 is a lightweight summer session ({courses_str}, {t5_units:.0f}u) — "
            "NOT a full extra semester. Label Term 5 as 'Summer Session' in the schedule header. "
            f"In Key Notes, reassure the student: this plan fits in 4 regular semesters; "
            f"{summer_tail}\n"
        )

    for t in range(1, result.active_terms + 1):
        season = "Summer Session" if (result.summer_overflow and t == 5) else _TERMS_PER_YEAR.get(t, f"Term {t}")
        t_units = sum(s.units for s in result.terms.get(t, []))
        lines.append(f"## Term {t} ({season}) -- {t_units:.0f} units")
        for slot in result.terms.get(t, []):
            tag = f" [{slot.tag_str()}]" if slot.tags else ""
            lines.append(f"- {slot.code} -- {slot.title} ({slot.units:.0f}u){tag}")
        lines.append("")

    lines.append("## Requirement Audit (copy verbatim into audit table)")
    lines.append("Major Preparation:")
    for uc_req, cc_code, status in result.requirement_audit:
        lines.append(f"  {uc_req} | {cc_code} | {status}")
    if result.post_transfer:
        lines.append("Post-Transfer (no CC articulation):")
        for pt in result.post_transfer:
            lines.append(f"  {pt}")
    lines.append("")

    lines.append("## IGETC Completion (mark checkmark for every area listed here):")
    area_labels = {
        "1A": "Area 1A English Composition",
        "1B": "Area 1B Critical Thinking",
        "2A": "Area 2A Math",
        "3A": "Area 3A Arts",
        "3B": "Area 3B Humanities",
        "4":  "Area 4 Social Science (x3 courses)",
        "5A": "Area 5A Physical Science",
        "5B": "Area 5B Biological Science",
        "5C": "Area 5C Lab",
        "6":  "Area 6 Language",
    }
    for area_code, label in area_labels.items():
        course = result.igetc_completion.get(area_code, "NOT ASSIGNED")
        if area_code == "5C":
            five_b = result.igetc_completion.get("5B", "")
            lines.append(f"  {label}: SATISFIED by {five_b} LAB -- no separate course needed")
        elif course == "NOT ASSIGNED":
            if area_code == "6":
                lines.append(
                    f"  {label}: NOT ASSIGNED -- can be satisfied by 2+ years of the "
                    "same foreign language in high school (grade C or better); "
                    "or by completing an approved foreign language course at CC"
                )
            else:
                lines.append(f"  {label}: NOT ASSIGNED")
        else:
            lines.append(f"  {label}: {course}")
    lines.append("")

    lines.append("## Key Notes")
    lines.append(f"- TAG: {tag_note}")
    lines.append(f"- GPA target: {gpa_range} -- {gpa_note}")
    if result.summer_overflow:
        lines.append(f"- Total units: {result.total_units:.0f} across 4 semesters + 1 summer session")
    else:
        lines.append(f"- Total units: {result.total_units:.0f} across {result.active_terms} terms")
    for w in result.warnings:
        lines.append(f"- NOTE: {w}")

    return "\n".join(lines)


# ── Streaming LLM render ──────────────────────────────────────────────────────

def render_plan_stream(
    result: PlanResult,
    tag_note: str,
    gpa_range: str,
    gpa_note: str,
    mode: str = "competitive",
):
    """
    Stream markdown from LLM.  The LLM only formats —
    all scheduling decisions are already fixed in result.
    Uses llama-4-scout as primary; falls back to llama-3.3-70b if needed.
    """
    from advisor import _get_client

    prompt  = build_render_prompt(result, tag_note, gpa_range, gpa_note, mode)
    system  = _PLAN_SYSTEM_PROMPT
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": prompt},
    ]

    for model, max_tok in [
        ("meta-llama/llama-4-scout-17b-16e-instruct", 5000),
        ("llama-3.3-70b-versatile", 6000),
    ]:
        try:
            stream = _get_client().chat.completions.create(
                model=model, messages=messages,
                max_tokens=max_tok, temperature=0.05, stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
            return
        except Exception as e:
            err_str = str(e).lower()
            if "rate" in err_str or "quota" in err_str or "429" in err_str:
                continue  # try next model
            raise
    yield "\n\n[Error: all rendering models unavailable — please retry]"
