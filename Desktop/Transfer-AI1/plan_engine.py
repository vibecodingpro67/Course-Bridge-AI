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

# Cal-GETC (default — for students who first enrolled at a CCC fall 2025 or later).
# Area 6 (Ethnic Studies) is processed before Area 4 so the Ethnic Studies course doesn't
# also compete for an Area 4 slot.
_CALGETC_REQUIRED = [
    ("1A", "English Composition",                         1),
    ("1B", "Critical Thinking / English Composition",     1),
    ("1C", "Oral Communication",                          1),
    ("2",  "Mathematical Concepts and Quantitative Reasoning", 1),
    ("3A", "Arts",                                        1),
    ("3B", "Humanities",                                  1),
    ("6",  "Ethnic Studies",                              1),
    ("4",  "Social & Behavioral Sciences",                2),
    ("5A", "Physical Sciences",                           1),
    ("5B", "Biological Sciences",                         1),
    ("5C", "Laboratory Science",                          1),
]

# Legacy IGETC — for students who first enrolled before fall 2025 (catalog rights).
_IGETC_REQUIRED = [
    ("1A", "English Composition",                         1),
    ("1B", "Critical Thinking / English Composition",     1),
    ("2A", "Mathematical Concepts",                       1),
    ("3A", "Arts",                                        1),
    ("3B", "Humanities",                                  1),
    ("4",  "Social & Behavioral Sciences",                3),
    ("5A", "Physical Sciences",                           1),
    ("5B", "Biological Sciences",                         1),
    ("5C", "Laboratory Science",                          1),
    ("6",  "Languages Other Than English",                1),
]

# Quarter-system schools (termType=1 in ASSIST; 3 out of 116 CCCs)
_QUARTER_SCHOOLS = {"De Anza College", "Foothill College", "Lake Tahoe Community College"}

def _is_quarter(college: str) -> bool:
    return college in _QUARTER_SCHOOLS

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


_CALGETC_CACHE: dict | None = None

def _load_calgetc() -> dict:
    global _CALGETC_CACHE
    if _CALGETC_CACHE is not None:
        return _CALGETC_CACHE
    path = os.path.join(_DATA_DIR, "calgetc_map.json.gz")
    if os.path.exists(path):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                _CALGETC_CACHE = json.load(f)
            return _CALGETC_CACHE
        except Exception:
            pass
    _CALGETC_CACHE = {}
    return _CALGETC_CACHE


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
    not_articulated: list = field(default_factory=list)  # required, zero CC equivalent per ASSIST
    warnings: list = field(default_factory=list)
    total_units: float = 0.0
    active_terms: int = 4      # how many terms actually have courses
    extended_plan: bool = False  # True when courses spill past base term count
    summer_overflow: bool = False  # True when overflow term is light (<10u)
    multi_track: bool = False  # True when agreement has duplicate OR-menus (emphasis tracks detected)
    is_quarter: bool = False   # True for De Anza, Foothill, Lake Tahoe
    ge_pattern: str = "calgetc"  # "calgetc" (default, F2025+) or "igetc" (catalog-rights)

    def all_courses(self) -> list:
        out = []
        for t in range(1, self.active_terms + 1):
            out.extend(self.terms.get(t, []))
        return out


# ── Term naming ───────────────────────────────────────────────────────────────

_MAX_TERMS_HARD = 8            # absolute ceiling
_MAX_UNITS_PER_TERM = 20.0    # hard cap per semester term
_MAX_QUARTER_UNITS_PER_TERM = 18.0  # hard cap per quarter term (De Anza/Foothill norm)

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

# Quarter schools run 3 terms/year (Fall/Winter/Spring); base plan = 6 quarters (2 years)
_TERMS_QUARTER = {
    1: "Fall Q1",
    2: "Winter Q1",
    3: "Spring Q1",
    4: "Fall Q2",
    5: "Winter Q2",
    6: "Spring Q2",
    7: "Extended / Quarter 7",
    8: "Extended / Quarter 8",
}


def _fmt_units(u: float) -> str:
    """Format a unit count without losing fractional units (ASSIST commonly
    lists X.5-unit courses, e.g. CIS 22CH = 4.5u) — never round to the nearest
    whole number for display."""
    return f"{u:g}"


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


def _major_word_hit(key_word: str, user_str: str) -> bool:
    """Conservative substring match for major-name words.

    Uses an 8-char prefix threshold (vs 5 for CC names) to prevent false matches
    between related majors, e.g. 'psychobiology' vs 'psychology' both start with
    'psych' (5 chars) but differ at char 7 ('psycholo' vs 'psychobi').
    """
    if key_word in user_str:
        return True
    if len(key_word) >= 8 and key_word[:8] in user_str:
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
            ("CIS", "22A", "Beginning Programming Methodologies in C++", 4.5, []),
            ("CIS", "22B", "Intermediate Programming Methodologies in C++", 4.5, []),
        ],
        "trigger_prereqs": [],
    },
    ("de anza college", "CIS", "22CH"): {
        "inject": [
            ("CIS", "22A", "Beginning Programming Methodologies in C++", 4.5, []),
            ("CIS", "22B", "Intermediate Programming Methodologies in C++", 4.5, []),
        ],
        "trigger_prereqs": [],
    },
    # De Anza CIS 26B: intro path is CIS 22A (intro C++) → CIS 26A (C programming).
    # 22A→26A is cross-series (numeric 22 vs 26) so explicit_prereqs required on 26A.
    # 26A→26B is same-series so sequence detection handles it.
    ("de anza college", "CIS", "26B"): {
        "inject": [
            ("CIS", "22A", "Beginning Programming Methodologies in C++", 4.5, []),
            ("CIS", "26A", "C as a Second Programming Language", 4.5, ["CIS 22A"]),
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
            ("PHYS", "4A", "Physics for Scientists and Engineers: Mechanics", 6.0, ["MATH 1A"]),
            ("MATH", "1D", "Calculus IV", 5.0, []),
            ("PHYS", "4B", "Physics for Scientists and Engineers: Electricity and Magnetism", 6.0, []),
        ],
        "trigger_prereqs": ["PHYS 4B", "MATH 1D"],
    },
}

# UC requirement OR groups — within each frozenset only ONE needs to be
# satisfied.  When multiple members appear in a shard we keep the cheapest
# CC path (fewest total units) and mark the rest as "satisfied via <winner>".
#
# Tuple formats:
#   (uc_normalized, frozenset)               — applies to all majors at this campus
#   (uc_normalized, major_substr, frozenset) — applies only when major name contains major_substr
_UC_REQ_OR_GROUPS: list = [
    # Berkeley CS / EECS: "MATH 54 or EECS 16A or MATH 56"
    ("berkeley", frozenset({("MATH", "54"), ("EECS", "16A"), ("MATH", "56")})),

    # Davis Sociology A.B. — breadth elective clusters ("pick one" per group).
    # ASSIST lists the full GE elective menu as separate required entries, causing
    # the engine to schedule all ~11 History, ~8 Ethnic Studies, etc. options.
    # Each group below collapses to one representative course.
    ("davis", "sociology", frozenset({
        ("HIS","007A"), ("HIS","007B"), ("HIS","007C"),
        ("HIS","009A"), ("HIS","009B"), ("HIS","010C"),
        ("HIS","004A"), ("HIS","004B"), ("HIS","004C"),
        ("HIS","017A"), ("HIS","017B"),
    })),
    ("davis", "sociology", frozenset({
        ("NAS","001"), ("NAS","010"),
        ("ASA","001"), ("ASA","002"), ("ASA","004"),
        ("CHI","010"), ("CHI","050"), ("AAS","010"),
    })),
    ("davis", "sociology", frozenset({
        ("PHI","005"), ("PHI","014"), ("PHI","024"),
    })),
    ("davis", "sociology", frozenset({
        ("POL","001"), ("POL","002"), ("POL","003"), ("POL","004"),
        ("PSC","001"), ("ECN","001B"), ("ANT","002"),
    })),
]

# Known bridge courses for "conditional" articulations — ASSIST marks the CC
# course as satisfying the requirement only if a specific UC course is also
# completed after transfer (e.g. CIS 22C -> COMPSCI 61B still requires
# COMPSCI 47B at Berkeley). Keyed by (uc_prefix, uc_number).
_BRIDGE_COURSE_MAP = {
    ("COMPSCI", "61A"): "COMPSCI 47A",
    ("COMPSCI", "61B"): "COMPSCI 47B",
    ("COMPSCI", "61C"): "COMPSCI 47C",
}


def _conditional_bridge_note(uc_str: str) -> str:
    """Build a Post-Transfer entry for a MET (CONDITIONAL) requirement."""
    head = uc_str.split(" - ", 1)[0].strip()
    parts = head.split()
    prefix, number = (parts[0], parts[-1]) if len(parts) >= 2 else ("", "")
    bridge = _BRIDGE_COURSE_MAP.get((prefix.upper(), number.upper()))
    if bridge:
        return (
            f"{head} — CONDITIONAL: also complete {bridge} at the university after "
            "transfer to fully satisfy this requirement (per ASSIST's conditional "
            "articulation note)."
        )
    return (
        f"{head} — CONDITIONAL: ASSIST requires an additional university-level course "
        "after transfer to fully satisfy this requirement; confirm the specific course "
        "with a UC advisor."
    )


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
    major: str = "",
) -> tuple[list, list, list, bool, set, list, list]:
    """
    For each UC articulation entry, pick one option group deterministically.

    Two processing modes, selected per shard entry by the "g"/"k" fields
    added during the ASSIST pipeline build:

    NFromArea (k > 0):  entries that share a RequirementGroup (same "g") are
        alternatives — only the cheapest k CC paths are scheduled; the rest
        are marked MET via winner.  Duplicate groups (same UC-code set
        appearing in multiple emphasis tracks) are deduped.

    Following / legacy (k == 0 or g == ""):  each entry is an independent
        AND requirement.  Falls back to the legacy _UC_REQ_OR_GROUPS list for
        old shards that predate the "g"/"k" fields.

    Returns (major_courses, audit_rows, post_transfer, multi_track,
    loser_cc_codes, not_articulated, stale_notes) where multi_track is True
    when duplicate NFromArea menus were detected (indicating the agreement
    covers multiple emphasis tracks and this plan is a superset).
    """
    major_l = major.lower()

    # ── Split out "na" rows: required by the major (present in ASSIST's own
    #    template) but with NO articulation entry at all — not even an explicit
    #    noArticulationReason. Render these as their own NOT ARTICULATED list
    #    rather than silently dropping them or conflating with POST-TRANSFER. ──
    not_articulated = []
    filtered_arts = []
    for art in arts:
        if art.get("na"):
            uc_c = art.get("uc", {})
            not_articulated.append(f"{uc_c.get('p','')} {uc_c.get('n','')} - {uc_c.get('t','')}")
        else:
            filtered_arts.append(art)
    arts = filtered_arts

    # ── Staleness notes: ASSIST occasionally flags an articulation as due to
    #    be revised. Surface regardless of which option ends up chosen. ──────
    stale_notes = []
    for art in arts:
        note = art.get("stale")
        if note:
            uc_c = art.get("uc", {})
            uc_str = f"{uc_c.get('p','')} {uc_c.get('n','')}"
            stale_notes.append(f"ASSIST flags {uc_str} as subject to change: {note}")

    # ── Legacy OR-group pre-pass (fallback for shards without g/k) ───────────
    skip_uc_keys: dict = {}
    winner_group_label: dict = {}   # winner_key -> combined "A / B / C" label
    for group in _UC_REQ_OR_GROUPS:
        if len(group) == 3:
            group_uc, major_substr, or_group = group
            if major_substr.lower() not in major_l:
                continue
        else:
            group_uc, or_group = group
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
        winner_group_label[winner] = " / ".join(f"{k[0]} {k[1]}" for k, _ in members)
        for key, _ in members:
            if key != winner:
                skip_uc_keys[key] = winner

    # ── Partition entries into NFromArea groups vs AND entries ────────────────
    # group_map: gid -> {"pick_n": int, "arts": list, "uc_codes": frozenset}
    group_map: dict = {}
    and_arts: list = []      # Following (k==0) or legacy (g=="")

    for art in arts:
        gid    = art.get("g", "")
        pick_n = art.get("k", 0)
        if gid and pick_n > 0:
            if gid not in group_map:
                group_map[gid] = {"pick_n": pick_n, "arts": []}
            group_map[gid]["arts"].append(art)
        else:
            and_arts.append(art)

    # Attach frozenset of UC keys to each group (needed for dedup + explosion detection)
    for gid, gdata in group_map.items():
        gdata["uc_codes"] = frozenset(
            (a.get("uc", {}).get("p","").upper(), a.get("uc", {}).get("n","").upper())
            for a in gdata["arts"]
        )

    # ── Detect emphasis-track explosion (duplicate OR-menus) ─────────────────
    # Two groups with ≥3-course menus that share ≥50% of UC codes = same elective
    # slot appearing in multiple tracks → this is a multi-track agreement.
    multi_track = False
    glist = [gd for gd in group_map.values() if len(gd["uc_codes"]) >= 3]
    for i, g1 in enumerate(glist):
        for g2 in glist[i+1:]:
            overlap = len(g1["uc_codes"] & g2["uc_codes"])
            if overlap >= 3 and overlap / min(len(g1["uc_codes"]), len(g2["uc_codes"])) >= 0.5:
                multi_track = True
                break
        if multi_track:
            break

    committed: dict = {}
    audit_rows = []
    post_transfer = []
    loser_cc_codes: set = set()   # CC codes from alternatives NOT chosen in an OR-group —
                                   # excluded from elective-filling to avoid redundant re-scheduling

    # ── Process NFromArea groups ───────────────────────────────────────────────
    seen_uc_sets: set = set()   # deduplicate groups with identical UC-code menus

    def _pick_cc(valid_groups):
        """Select the best CC option group from a list of alternatives."""
        if not accept_honors:
            filtered = [g for g in valid_groups if not all(
                c.get("n","").upper().endswith("H") for c in g
            )]
            if filtered:
                valid_groups = filtered
        def _overlap(grp):
            return sum(1 for c in grp if (c.get("p",""), c.get("n","")) in committed)
        def _honors_cnt(grp):
            return sum(1 for c in grp if c.get("n","").upper().endswith("H"))
        if accept_honors:
            return max(valid_groups, key=lambda g: (_overlap(g), _honors_cnt(g)))
        return max(valid_groups, key=_overlap)

    def _cc_cost(chosen):
        return sum(
            float(c.get("u", 3) or 3)
            for c in chosen
            if (c.get("p",""), c.get("n","")) not in completed
        )

    def _commit_chosen(chosen, uc_str, uc_key=None):
        cc_codes = []
        conditional = any(c.get("cond") for c in chosen)
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
                committed[key] = CourseSlot(
                    prefix=c.get("p",""), number=c.get("n",""),
                    title=c.get("t",""), units=units,
                    tags=["Required Major Prep"], uc_reqs=[uc_str],
                )
            else:
                committed[key].uc_reqs.append(uc_str)
            cc_codes.append(f"{key[0]} {key[1]}")
        # If this UC requirement won a legacy OR-group (e.g. MATH 54 / EECS 16A /
        # MATH 56), render ONE consolidated row for the whole group instead of a
        # separate "satisfied via" row per alternative.
        label = uc_str
        if uc_key is not None and uc_key in winner_group_label:
            _, _, title = uc_str.partition(" - ")
            label = f"{winner_group_label[uc_key]} - {title}" if title else winner_group_label[uc_key]
        status = "MET (CONDITIONAL)" if conditional else "MET"
        audit_rows.append((label, " + ".join(cc_codes) if cc_codes else "-", status))
        if conditional:
            post_transfer.append(_conditional_bridge_note(uc_str))

    for gid, gdata in group_map.items():
        uc_codes_fs = gdata["uc_codes"]

        if uc_codes_fs in seen_uc_sets:
            # Duplicate track menu — skip, just record as satisfied
            for art in gdata["arts"]:
                uc_c   = art.get("uc", {})
                uc_str = f"{uc_c.get('p','')} {uc_c.get('n','')} - {uc_c.get('t','')}"
                audit_rows.append((uc_str, "satisfied via alternate track", "MET"))
            continue
        seen_uc_sets.add(uc_codes_fs)

        pick_n     = gdata["pick_n"]
        sectioned  = any(a.get("sec") is not None for a in gdata["arts"])

        if sectioned:
            # ── Section-atomic pick: group rows by "sec" index, pick the
            #    cheapest pick_n whole sections, commit every row in a
            #    winning section (all-or-nothing per section). ─────────────
            sections: dict = {}
            for art in gdata["arts"]:
                sections.setdefault(art.get("sec"), []).append(art)

            sec_candidates = []   # (cost, sec_idx, rows_info)
            for sec_idx, sec_arts in sections.items():
                rows_info = []   # (uc_str, uc_key, chosen_cc_or_None)
                cost = 0.0
                for art in sec_arts:
                    uc_c   = art.get("uc", {})
                    uc_key = (uc_c.get("p","").upper(), uc_c.get("n","").upper())
                    uc_str = f"{uc_c.get('p','')} {uc_c.get('n','')} - {uc_c.get('t','')}"

                    if uc_key in skip_uc_keys:
                        # Alternative already satisfied by another member of this
                        # legacy OR-group elsewhere — no separate row for it.
                        continue

                    valid = [g for g in art.get("cc", []) if g]
                    if not valid:
                        rows_info.append((uc_str, uc_key, None, "post"))
                        continue

                    chosen = _pick_cc(list(valid))
                    cost += _cc_cost(chosen)
                    rows_info.append((uc_str, uc_key, chosen, "cc"))

                sec_candidates.append((cost, sec_idx, rows_info))

            if not sec_candidates:
                continue

            sec_candidates.sort(key=lambda x: x[0])
            winners = sec_candidates[:pick_n]
            losers  = sec_candidates[pick_n:]

            for _cost, _sec_idx, rows_info in winners:
                for uc_str, _uc_key, chosen, kind in rows_info:
                    if kind == "cc":
                        _commit_chosen(chosen, uc_str)
                    elif kind == "post":
                        post_transfer.append(uc_str)
                        audit_rows.append((uc_str, "-", "POST-TRANSFER"))

            winner_track_desc = (
                " or ".join(
                    "/".join(uc_str.split(" - ")[0] for uc_str, _, _, _ in w[2])
                    for w in winners
                ) if winners else "selected track"
            )
            for _cost, _sec_idx, rows_info in losers:
                for uc_str, _uc_key, chosen, kind in rows_info:
                    audit_rows.append((uc_str, f"satisfied via alternate track ({winner_track_desc})", "MET"))
                    if kind == "cc":
                        for c in chosen:
                            loser_cc_codes.add((c.get("p",""), c.get("n","")))

            continue

        candidates = []   # (cost, uc_str, chosen_cc_group, uc_key)

        for art in gdata["arts"]:
            uc_c   = art.get("uc", {})
            uc_key = (uc_c.get("p","").upper(), uc_c.get("n","").upper())
            uc_str = f"{uc_c.get('p','')} {uc_c.get('n','')} - {uc_c.get('t','')}"

            if uc_key in skip_uc_keys:
                # Alternative already satisfied by another member of this
                # legacy OR-group elsewhere — no separate row for it.
                continue

            valid = [g for g in art.get("cc", []) if g]
            if not valid:
                continue  # no CC articulation — post-transfer, skip from OR selection

            chosen = _pick_cc(list(valid))
            candidates.append((_cc_cost(chosen), uc_str, chosen, uc_key))

        if not candidates:
            continue

        candidates.sort(key=lambda x: x[0])
        winners = candidates[:pick_n]
        losers  = candidates[pick_n:]

        for _cost, uc_str, chosen, _key in winners:
            _commit_chosen(chosen, uc_str)

        # Record winner description for "satisfied via" on losers
        winner_cc_desc = (
            " or ".join(
                "/".join(c.get("p","") + " " + c.get("n","") for c in w[2])
                for w in winners
            ) if winners else "selected option"
        )
        for _cost, uc_str, chosen, _key in losers:
            audit_rows.append((uc_str, f"satisfied via {winner_cc_desc}", "MET"))
            for c in chosen:
                loser_cc_codes.add((c.get("p",""), c.get("n","")))

    # ── Process AND entries (Following / legacy) ──────────────────────────────
    for art in and_arts:
        uc_c   = art.get("uc", {})
        uc_key = (uc_c.get("p","").upper(), uc_c.get("n","").upper())
        uc_str = f"{uc_c.get('p','')} {uc_c.get('n','')} - {uc_c.get('t','')}"

        if uc_key in skip_uc_keys:
            # Alternative already satisfied by another member of this legacy
            # OR-group elsewhere — no separate row for it.
            continue

        cc_groups = art.get("cc", [])
        valid_groups = [g for g in cc_groups if g]

        if not valid_groups:
            post_transfer.append(uc_str)
            audit_rows.append((uc_str, "-", "POST-TRANSFER"))
            continue

        chosen = _pick_cc(list(valid_groups))
        _commit_chosen(chosen, uc_str, uc_key=uc_key)

    return (list(committed.values()), audit_rows, post_transfer, multi_track,
            loser_cc_codes, not_articulated, stale_notes)


# ── IGETC selection ───────────────────────────────────────────────────────────

def _select_igetc(
    college: str,
    scheduled_keys: set,
    accept_honors: bool,
    completed_keys: set | None = None,
    ge_pattern: str = "calgetc",
) -> tuple[list, dict]:
    data = _load_calgetc() if ge_pattern == "calgetc" else _load_igetc()
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
    completed_set = completed_keys or set()
    ge_tag_prefix = "Cal-GETC" if ge_pattern == "calgetc" else "IGETC"

    # Discipline map for Area 4 multi-course rule.
    # IGETC: uses 4A-4J sub-area codes from igetc_map.
    # Cal-GETC: calgetc_map has a flat "4" list with no sub-area codes; use course prefix
    #           as a discipline proxy (PSYC vs SOC = two disciplines).
    disc_map: dict = {}
    if ge_pattern == "igetc":
        for disc in ("4A","4B","4C","4D","4E","4F","4G","4H","4I","4J"):
            for c in by_area.get(disc, []):
                ck = (c.get("prefix",""), c.get("number",""))
                if ck not in disc_map:
                    disc_map[ck] = disc

    required = _CALGETC_REQUIRED if ge_pattern == "calgetc" else _IGETC_REQUIRED

    igetc_courses: list[CourseSlot] = []
    area_assignments: dict = {}
    five_b_has_lab = False
    placed_igetc_keys: set = set()

    def _ok(c):
        pfx = c.get("prefix","").upper()
        ttl = c.get("title","").upper()
        if pfx.startswith("ESL") or "ENGLISH AS A SECOND" in ttl:
            return False
        if not accept_honors and c.get("number","").upper().endswith("H"):
            return False
        return True

    def _data_courses(area_code: str) -> list:
        """Return raw course list from by_area for the given area code."""
        if area_code == "6":
            # IGETC stores Language under "6A"; Cal-GETC Ethnic Studies
            # should be under "6" (not available yet) with "4C" as proxy.
            return by_area.get("6A", []) if ge_pattern == "igetc" else by_area.get("6", [])
        return by_area.get(area_code, [])

    def _make_slot(c, tag: str) -> CourseSlot:
        try:
            units = float(c.get("units", 3) or 3)
        except (TypeError, ValueError):
            units = 3.0
        return CourseSlot(
            prefix=c.get("prefix",""),
            number=c.get("number",""),
            title=c.get("title",""),
            units=units,
            tags=[tag],
        )

    for area_code, area_name, _needed in required:
        tag = f"{ge_tag_prefix} Area {area_code}"

        # ── 5C: no separate slot — just record if 5B course is also a lab ──
        if area_code == "5C":
            if five_b_has_lab:
                area_assignments["5C"] = area_assignments.get("5B", "via 5B LAB")
            continue


        # ── Area 4: multi-course pick (handled before generic double-label) ─
        if area_code == "4":
            courses_4 = by_area.get("4", [])
            if not courses_4:
                continue
            quota = 2 if ge_pattern == "calgetc" else 3

            # Categorise every Area 4 course.
            # "existing" = already covered (completed or major-prep double-label)
            # "fresh"    = new IGETC-only course to schedule
            existing: list = []
            fresh: list = []
            seen_4: set = set()
            for c in courses_4:
                if not _ok(c):
                    continue
                ck = (c.get("prefix",""), c.get("number",""))
                if ck in seen_4 or ck in placed_igetc_keys:
                    continue
                seen_4.add(ck)
                if ck in completed_set or ck in scheduled_keys:
                    existing.append(c)
                else:
                    fresh.append(c)

            picks: list = []
            is_new_pick: list = []  # parallel bool — True if course needs a slot
            used_discs: set = set()

            def _try_add(c, is_new: bool):
                if len(picks) >= quota:
                    return
                if ge_pattern == "calgetc":
                    # Use prefix as discipline proxy (e.g. PSYC vs SOC = two disciplines).
                    d = c.get("prefix", "")
                    if picks and d in used_discs:
                        return
                    picks.append(c)
                    is_new_pick.append(is_new)
                    if d:
                        used_discs.add(d)
                else:
                    ck = (c.get("prefix",""), c.get("number",""))
                    d = disc_map.get(ck)
                    if d and d in used_discs:
                        return
                    picks.append(c)
                    is_new_pick.append(is_new)
                    if d:
                        used_discs.add(d)

            # Prefer double-labelling existing courses (no extra unit cost)
            for c in existing:
                _try_add(c, False)
            # Supplement with new courses as needed
            for c in fresh:
                _try_add(c, True)
            # If still short (e.g. discipline conflict) fill regardless of discipline
            if len(picks) < quota:
                for c in (existing + fresh):
                    if c not in picks:
                        if len(picks) >= quota:
                            break
                        picks.append(c)
                        is_new_pick.append(c not in existing)

            codes: list = []
            for c, is_new in zip(picks, is_new_pick):
                ck = (c.get("prefix",""), c.get("number",""))
                if is_new:
                    slot = _make_slot(c, tag)
                    igetc_courses.append(slot)
                    codes.append(slot.code)
                    placed_igetc_keys.add(ck)
                else:
                    suffix = " (already completed)" if ck in completed_set else ""
                    codes.append(f"{c.get('prefix','')} {c.get('number','')}{suffix}")
            area_assignments["4"] = ", ".join(codes)
            continue

        # ── Standard area processing ──────────────────────────────────────
        courses = _data_courses(area_code)
        if not courses:
            continue

        # Completed-course double-label
        completed_matches = [c for c in courses
                             if (c.get("prefix",""), c.get("number","")) in completed_set]
        if completed_matches:
            m = completed_matches[0]
            code = f"{m.get('prefix','')} {m.get('number','')}"
            area_assignments[area_code] = f"{code} (already completed)"
            if area_code in ("5A","5B"):
                mk = (m.get("prefix",""), m.get("number",""))
                if mk in lab_keys:
                    five_b_has_lab = True
            continue

        # Major prep double-label
        matches = [c for c in courses
                   if (c.get("prefix",""), c.get("number","")) in scheduled_keys]
        if matches:
            m = matches[0]
            code = f"{m.get('prefix','')} {m.get('number','')}"
            area_assignments[area_code] = code
            if area_code in ("5A","5B"):
                mk = (m.get("prefix",""), m.get("number",""))
                if mk in lab_keys:
                    five_b_has_lab = True
            continue

        # Build unique filtered list
        unique = []
        seen: set = set()
        for c in courses:
            if not _ok(c):
                continue
            k = (c.get("prefix",""), c.get("number",""))
            if k in completed_set or k in placed_igetc_keys:
                continue
            if k not in seen:
                seen.add(k)
                unique.append(c)
        if not unique:
            continue

        if area_code == "1B":
            unique.sort(key=lambda c: (0 if c.get("prefix","").upper().startswith("ENGL") else 1))
        if area_code == "5B":
            unique.sort(key=lambda c: (0 if (c.get("prefix",""), c.get("number","")) in lab_keys else 1))

        # ── Single-course areas ────────────────────────────────────────────
        pick = unique[0]
        pk = (pick.get("prefix",""), pick.get("number",""))
        slot = _make_slot(pick, tag)
        igetc_courses.append(slot)
        area_assignments[area_code] = slot.code
        placed_igetc_keys.add(pk)
        if area_code in ("5A","5B") and pk in lab_keys:
            five_b_has_lab = True

    return igetc_courses, area_assignments


# ── Term bin-packing ──────────────────────────────────────────────────────────

def _assign_terms(
    major_courses: list,
    igetc_courses: list,
    major: str,
    is_quarter: bool = False,
) -> tuple[dict, dict]:
    """
    Greedy term bin-packing with prereq constraints.

    Quarter schools use 18 QU/term cap and a 6-term minimum (Fall/Winter/Spring × 2 years).
    Semester schools use 20 SU/term cap and a 4-term minimum.
    Returns: (terms_dict, term_units_dict)
    """
    import math

    max_units  = _MAX_QUARTER_UNITS_PER_TERM if is_quarter else _MAX_UNITS_PER_TERM
    base_terms = 6 if is_quarter else 4

    # Pre-calculate needed terms from total unit load so the cap is never breached
    total_u   = sum(s.units for s in major_courses + igetc_courses)
    max_terms = max(base_terms, min(math.ceil(total_u / max_units), _MAX_TERMS_HARD))

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
        """Return earliest allowed term for this GE slot."""
        for tag in slot.tags:
            if "Area 1B" in tag:
                return igetc_area_term.get("1A", 1) + 1  # 1B must come strictly after 1A
        return 1

    def _record_igetc_area(slot: CourseSlot, t: int):
        for tag in slot.tags:
            if "Area " in tag:
                igetc_area_term[tag.split("Area ")[1]] = t

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
    ge_prefix = "Cal-GETC" if getattr(result, "ge_pattern", "calgetc") == "calgetc" else "IGETC"
    for area_code, course_code in result.igetc_completion.items():
        if "NOT ASSIGNED" in str(course_code):
            continue
        for t in range(1, result.active_terms + 1):
            for slot in result.terms.get(t, []):
                label = f"{ge_prefix} Area {area_code}"
                if slot.code == course_code and label not in slot.tags:
                    slot.tags.append(label)


# ── Elective filling ──────────────────────────────────────────────────────────

def _fill_electives(result: PlanResult, college: str, exclude_codes: set | None = None,
                     accept_honors: bool = False) -> None:
    """
    Fill unit shortfall with UC-transferable courses from the school's IGETC pool.

    Picks courses from varied disciplines (round-robin by prefix), respects per-term
    caps, and tags each added course [Elective — transfer unit minimum].
    If the pool is exhausted before the minimum is reached, the remaining shortfall
    is left for _sanity_check to report.

    exclude_codes: CC (prefix, number) pairs to skip — e.g. alternatives that LOST
    an OR-group pick in major prep. Scheduling them as "electives" would silently
    re-add a redundant course satisfying the same requirement the winner already met.
    """
    min_units = 90.0 if result.is_quarter else 60.0
    if result.total_units >= min_units:
        return

    igetc = _load_igetc()
    school_data = igetc.get("bySchool", {}).get(college, {})
    if not school_data:
        return

    placed_codes = {s.code for s in result.all_courses()}
    excluded = exclude_codes or set()

    # Aggregate deduplicated pool from byArea
    seen_keys: set = set()
    pool = []
    for area_courses in school_data.get("byArea", {}).values():
        for c in area_courses:
            ck = (c.get("prefix", ""), c.get("number", ""))
            if ck in seen_keys:
                continue
            code = f"{ck[0]} {ck[1]}".strip()
            if code in placed_codes:
                continue
            if ck in excluded:
                continue
            if not accept_honors and ck[1].upper().endswith("H"):
                continue
            units = float(c.get("units") or 0)
            if units <= 0:
                continue
            seen_keys.add(ck)
            pool.append(c)

    if not pool:
        return

    # Group by prefix; within each group sort by sequence order (low numbers first)
    from collections import defaultdict
    by_prefix: dict = defaultdict(list)
    for c in pool:
        by_prefix[c.get("prefix", "OTHER")].append(c)
    for pfx in by_prefix:
        by_prefix[pfx].sort(key=lambda c: infer_sequence_order(c.get("number", "")))

    # Round-robin across prefixes for discipline variety
    sorted_prefixes = sorted(by_prefix.keys())
    candidates: list = []
    while any(by_prefix[p] for p in sorted_prefixes):
        for p in sorted_prefixes:
            if by_prefix[p]:
                candidates.append(by_prefix[p].pop(0))

    cap        = _MAX_QUARTER_UNITS_PER_TERM if result.is_quarter else _MAX_UNITS_PER_TERM
    base_terms = 6 if result.is_quarter else 4
    shortfall  = min_units - result.total_units

    for c in candidates:
        if shortfall <= 0:
            break

        prefix = c.get("prefix", "")
        number = c.get("number", "")
        title  = c.get("title", "")
        units  = float(c.get("units") or 0)

        # Sequence constraint: skip prereqs of already-placed later-sequence courses;
        # enforce that higher-sequence courses go after their prerequisites.
        ord_c = infer_sequence_order(number)[1]
        min_term_from = 1
        if ord_c >= 0:
            same_base_placed = [
                s for s in result.all_courses()
                if s.prefix == prefix and same_sequence_base(s.number, number)
            ]
            if same_base_placed:
                placed_info = [
                    (infer_sequence_order(s.number)[1], s.term) for s in same_base_placed
                ]
                # Skip if this is a prereq of an already-placed later-sequence course
                if any(p_ord > ord_c for p_ord, _ in placed_info):
                    continue
                # Must come after all earlier-sequence placed courses
                min_term_from = max(
                    (t for p_ord, t in placed_info if p_ord < ord_c),
                    default=0
                ) + 1

        # Find the term (>= min_term_from) with the most spare capacity that fits
        best_t    = None
        best_room = 0.0
        for t in range(min_term_from, result.active_terms + 1):
            used = sum(s.units for s in result.terms.get(t, []))
            room = cap - used
            if room >= units and room > best_room:
                best_room = room
                best_t    = t

        if best_t is None:
            # All eligible terms full — open a new term if the hard limit allows
            if result.active_terms >= _MAX_TERMS_HARD:
                continue
            best_t = result.active_terms + 1
            result.terms[best_t] = []
            result.active_terms  = best_t
            result.extended_plan = best_t > base_terms

        slot = CourseSlot(
            prefix=prefix, number=number, title=title, units=units,
            term=best_t, tags=["Elective — transfer unit minimum"]
        )
        result.terms[best_t].append(slot)
        result.total_units += units
        shortfall          -= units


# ── Main entry point ──────────────────────────────────────────────────────────

def build_plan(
    college: str,
    uc: str,
    major: str,
    accept_honors: bool = False,
    completed: set = None,
    ap_credits: str = "",
    ge_pattern: str = "calgetc",
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
        # Replace both underscores and hyphens so "Psychology-B.A." → "psychology b.a."
        maj_l_k = "__".join(parts[2:]).replace("_", " ").replace("-", " ").lower()
        cc_words  = [w for w in cc_l_k.split()  if len(w) >= 3 and w not in _CC_STOP_WORDS]
        # Exclude degree suffixes (e.g. "b.a.", "b.s.") — they contain dots and match
        # any major with the same suffix, causing short-named majors like "Art B.A."
        # to score 10.0 against unrelated queries like "Economics B.A.".
        maj_words = [w for w in maj_l_k.split() if len(w) >= 3 and "." not in w]
        cc_hit  = sum(1 for w in cc_words  if _prefix_hit(w, college_l))     / max(len(cc_words), 1)
        maj_hit = sum(1 for w in maj_words if _major_word_hit(w, major_l))   / max(len(maj_words), 1)
        score = cc_hit * 5 + maj_hit * 5
        if score > best_score:
            best_score = score
            best_key   = key

    if not best_key or best_score < 3.0:
        r = PlanResult(college=college, uc=uc, major=major)
        r.warnings.append(f"No articulation data found for {college} -> {uc} | {major}")
        return r

    arts   = shard[best_key]
    result = PlanResult(college=college, uc=uc, major=major, ge_pattern=ge_pattern)

    (major_courses, audit_rows, post_transfer, multi_track,
     loser_cc_codes, not_articulated, stale_notes) = _resolve_major_prep(
        arts, accept_honors, completed_keys, uc_normalized=uc_l, major=major
    )
    result.requirement_audit = audit_rows
    result.multi_track = multi_track
    result.post_transfer     = post_transfer
    result.not_articulated   = not_articulated
    result.warnings.extend(stale_notes)

    # Use matched CC name from shard key for IGETC lookup so typos in the
    # user's college string still resolve to the correct IGETC school entry.
    matched_cc_name = best_key.split("__")[0].replace("_", " ")

    # Inject CC-side prerequisite chains (e.g. CIS 22A→26A before CIS 26B,
    # PHYS 4A→4B and MATH 1D before ENGR 37).  Must run before scheduled_keys
    # is built so injected courses (like PHYS 4A) can double-label IGETC areas.
    _inject_cc_prereqs(major_courses, matched_cc_name, completed_keys)

    scheduled_keys = {(s.prefix, s.number) for s in major_courses}
    igetc_courses, area_assignments = _select_igetc(matched_cc_name, scheduled_keys, accept_honors,
                                                     completed_keys=completed_keys, ge_pattern=ge_pattern)
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

    result.is_quarter = _is_quarter(college)
    result.terms, _ = _assign_terms(major_courses, igetc_courses, major, is_quarter=result.is_quarter)

    # Compute how many terms have courses
    base_terms = 6 if result.is_quarter else 4
    last_used = base_terms
    for t in range(_MAX_TERMS_HARD, 0, -1):
        if result.terms.get(t):
            last_used = t
            break
    result.active_terms  = last_used
    result.extended_plan = last_used > base_terms

    _apply_double_labels(result)

    result.total_units = sum(s.units for s in result.all_courses())
    _fill_electives(result, college, exclude_codes=loser_cc_codes, accept_honors=accept_honors)

    # Recompute metadata after elective filling (new terms may have been added)
    base_terms = 6 if result.is_quarter else 4
    last_used = base_terms
    for t in range(_MAX_TERMS_HARD, 0, -1):
        if result.terms.get(t):
            last_used = t
            break
    result.active_terms  = last_used
    result.extended_plan = last_used > base_terms
    result.total_units   = sum(s.units for s in result.all_courses())

    _sanity_check(result)

    if ap_credits and ap_credits.strip():
        result.warnings.append(
            "AP CREDIT NOTE: AP exam credit handling is not yet implemented in the "
            "plan builder — your AP scores have not been applied. Consult your "
            "college's AP chart to identify which CC courses your scores satisfy, "
            "then re-run with those courses listed under \"already completed\"."
        )

    return result


def _sanity_check(result: PlanResult):
    # Multi-track note
    if result.multi_track:
        result.warnings.append(
            "MULTI-TRACK: This major's ASSIST agreement lists requirements for multiple "
            "emphasis tracks simultaneously. This plan is a superset — selecting a specific "
            "emphasis with a counselor may reduce the total course load."
        )

    # Ghost course check
    placed = {s.code for s in result.all_courses()}
    for area_code, course_code in result.igetc_completion.items():
        for code in course_code.split(", "):
            code = code.strip()
            if code and "via" not in code and "satisfied" not in code and "already completed" not in code and "NOT ASSIGNED" not in code and code not in placed:
                result.warnings.append(
                    f"Ghost: {code} listed in IGETC area {area_code} but not placed in any term."
                )

    # Extended plan warning
    base_terms    = 6 if result.is_quarter else 4
    overflow_term = base_terms + 1
    if result.extended_plan:
        ov_units = sum(s.units for s in result.terms.get(overflow_term, []))
        overflow_light = result.active_terms == overflow_term and ov_units < 10.0
        result.summer_overflow = overflow_light
        if overflow_light:
            ov_slots = result.terms.get(overflow_term, [])
            courses_str = ", ".join(s.code for s in ov_slots)
            if len(ov_slots) == 1:
                tail = "Most transfer students handle this as a single summer course."
            else:
                tail = "Most transfer students handle these as summer courses."
            if result.is_quarter:
                result.warnings.append(
                    f"SUMMER SESSION: This plan fits in 6 regular quarters plus one summer session "
                    f"({courses_str}, {ov_units:.0f}u). {tail}"
                )
            else:
                result.warnings.append(
                    f"SUMMER SESSION: This plan fits in 4 regular semesters plus one summer session "
                    f"({courses_str}, {ov_units:.0f}u). {tail}"
                )
        else:
            extra = result.active_terms - base_terms
            if result.is_quarter:
                result.warnings.append(
                    f"EXTENDED PLAN: {result.major} at {result.uc} requires "
                    f"{result.active_terms} quarters of preparation ({extra} beyond the standard "
                    f"6-quarter / 2-year timeline). This program is unusually heavy. "
                    f"Students typically need additional summer coursework."
                )
            else:
                result.warnings.append(
                    f"EXTENDED PLAN: {result.major} at {result.uc} requires "
                    f"{result.active_terms} semesters of preparation ({extra} beyond the standard "
                    f"4-semester / 2-year timeline). This program is unusually heavy. "
                    f"Students typically need summer coursework or an extra year at CC."
                )

    # UC unit minimum check: 60 semester units = 90 quarter units
    _UC_MIN_UNITS = 90.0 if result.is_quarter else 60.0
    if result.total_units < _UC_MIN_UNITS:
        if result.is_quarter:
            sem_equiv   = result.total_units * (2.0 / 3.0)
            shortfall_qu = _UC_MIN_UNITS - result.total_units
            shortfall_su = 60.0 - sem_equiv
            result.warnings.append(
                f"UNIT SHORTFALL: This plan totals {result.total_units:.1f} quarter units "
                f"(approx. {sem_equiv:.1f} semester units), which is {shortfall_qu:.1f} QU "
                f"({shortfall_su:.1f} SU) below the UC minimum of 90 quarter units "
                f"(= 60 semester units) required for transfer eligibility. "
                f"Add {shortfall_qu:.1f} QU of transferable electives before applying."
            )
        else:
            shortfall = _UC_MIN_UNITS - result.total_units
            result.warnings.append(
                f"UNIT SHORTFALL: This plan totals {result.total_units:.1f} transferable units, "
                f"which is {shortfall:.1f}u below the UC minimum of 60 semester units required "
                f"for transfer eligibility. Add {shortfall:.1f}u of transferable electives "
                f"(e.g., additional GE courses, language courses, or major-adjacent electives) "
                f"before applying."
            )

    # Under-loaded term check
    for t in range(1, result.active_terms + 1):
        if result.summer_overflow and t == overflow_term:
            continue  # summer session can legitimately be light
        units = sum(s.units for s in result.terms.get(t, []))
        if units > 0 and units < 9.0:
            result.warnings.append(
                f"Term {t} has only {units:.0f} units — likely needs additional GE electives."
            )


# ── Compact rendering prompt ──────────────────────────────────────────────────

def repair_term_headers(text: str, result: PlanResult) -> tuple:
    """
    Deterministically fix LLM-scrambled '## Term N (anything)' headers.
    Compares each rendered header against the engine's assigned label and replaces
    on mismatch. Returns (repaired_text, n_repairs).
    """
    base_terms    = 6 if result.is_quarter else 4
    overflow_term = base_terms + 1
    term_names    = _TERMS_QUARTER if result.is_quarter else _TERMS_PER_YEAR

    correct: dict = {}
    for t in range(1, result.active_terms + 1):
        if result.summer_overflow and t == overflow_term:
            correct[t] = "Summer Session"
        else:
            correct[t] = term_names.get(t, f"Term {t}")

    repairs = 0

    def _fix(m: re.Match) -> str:
        nonlocal repairs
        t = int(m.group(1))
        found = m.group(2)
        expected = correct.get(t)
        if expected is None or found == expected:
            return m.group(0)
        repairs += 1
        return f"## Term {t} ({expected})"

    repaired = re.sub(r"## Term (\d+) \(([^)]*)\)", _fix, text)
    return repaired, repairs


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
        "status, or IGETC assignment. Copy all values verbatim.\n"
        "CRITICAL — TERM HEADERS: Each '## Term N (LABEL)' section below has a "
        "pre-assigned label. Copy the label VERBATIM, character for character. "
        "Do NOT simplify, reorder, paraphrase, or drop the quarter suffix. "
        "'Fall Q1', 'Winter Q1', 'Spring Q1', 'Fall Q2', 'Winter Q2', 'Spring Q2' "
        "are distinct labels — do not shorten any to 'Fall', 'Winter', or 'Spring'.\n",
        f"Student: {result.college} -> {result.uc} | {result.major}\n",
    ]

    if result.multi_track:
        lines.append(
            "NOTE: MULTI-TRACK MAJOR — The ASSIST agreement for this major lists requirements "
            "for multiple emphasis tracks (e.g. General, Global, Law & Society, etc.) simultaneously. "
            "This plan covers the union of requirements across all tracks, which may be more courses "
            "than a student who selects one specific track needs. In Key Notes, add: "
            "'This major has multiple emphasis tracks. This plan covers requirements across "
            "all tracks — meeting with a counselor to choose a specific emphasis may reduce "
            "the total course load.'\n"
        )

    base_terms    = 6 if result.is_quarter else 4
    overflow_term = base_terms + 1
    term_names    = _TERMS_QUARTER if result.is_quarter else _TERMS_PER_YEAR
    term_word     = "quarters" if result.is_quarter else "semesters"
    std_timeline  = "6-quarter / 2-year" if result.is_quarter else "4-semester / 2-year"

    if result.extended_plan and not result.summer_overflow:
        extra = result.active_terms - base_terms
        lines.append(
            f"WARNING: This is an EXTENDED PLAN requiring {result.active_terms} {term_word} "
            f"({extra} beyond the standard {std_timeline}). Terms {overflow_term}+ represent "
            f"additional {term_word}. Include a prominent note in Key Notes that this program "
            "requires more than the standard 2-year CC timeline and students should plan for "
            "summer sessions or additional terms at CC.\n"
        )
    elif result.summer_overflow:
        ov_slots = result.terms.get(overflow_term, [])
        ov_units = sum(s.units for s in ov_slots)
        courses_str = ", ".join(s.code for s in ov_slots)
        if len(ov_slots) == 1:
            summer_tail = (
                "the summer course is optional-but-recommended and most students complete it "
                "without extending their timeline."
            )
        else:
            summer_tail = (
                "the summer session courses are optional-but-recommended and most students "
                "complete them without extending their timeline."
            )
        std_count = "6 regular quarters" if result.is_quarter else "4 regular semesters"
        lines.append(
            f"NOTE: Term {overflow_term} is a lightweight summer session ({courses_str}, {ov_units:.0f}u) — "
            f"NOT a full extra {'quarter' if result.is_quarter else 'semester'}. "
            f"Label Term {overflow_term} as 'Summer Session' in the schedule header. "
            f"In Key Notes, reassure the student: this plan fits in {std_count}; "
            f"{summer_tail}\n"
        )

    for t in range(1, result.active_terms + 1):
        if result.summer_overflow and t == overflow_term:
            season = "Summer Session"
        else:
            season = term_names.get(t, f"Term {t}")
        t_units = sum(s.units for s in result.terms.get(t, []))
        lines.append(f"## Term {t} ({season}) -- {_fmt_units(t_units)} units")
        for slot in result.terms.get(t, []):
            tag = f" [{slot.tag_str()}]" if slot.tags else ""
            lines.append(f"- {slot.code} -- {slot.title} ({_fmt_units(slot.units)}u){tag}")
        lines.append("")

    lines.append("## Requirement Audit (copy verbatim into audit table)")
    lines.append("Major Preparation:")
    for uc_req, cc_code, status in result.requirement_audit:
        lines.append(f"  {uc_req} | {cc_code} | {status}")
    if result.post_transfer:
        lines.append("Post-Transfer (no CC articulation):")
        for pt in result.post_transfer:
            lines.append(f"  {pt}")
    if result.not_articulated:
        lines.append("Not Articulated (required by the major, zero CC equivalent per ASSIST):")
        for na in result.not_articulated:
            lines.append(
                f"  {na} | NOT ARTICULATED — no CC equivalent; take at {result.uc} "
                f"or via {result.uc} Summer Session before transfer."
            )
    lines.append("")

    is_calgetc = getattr(result, "ge_pattern", "calgetc") == "calgetc"
    ge_header = "Cal-GETC" if is_calgetc else "IGETC"
    lines.append(f"## {ge_header} Completion (mark checkmark for every area listed here):")
    if is_calgetc:
        area_labels = {
            "1A": "Area 1A English Composition",
            "1B": "Area 1B Critical Thinking",
            "1C": "Area 1C Oral Communication",
            "2":  "Area 2 Mathematical Concepts and Quantitative Reasoning",
            "3A": "Area 3A Arts",
            "3B": "Area 3B Humanities",
            "6":  "Area 6 Ethnic Studies",
            "4":  "Area 4 Social & Behavioral Sciences (2 courses, 2 disciplines)",
            "5A": "Area 5A Physical Sciences",
            "5B": "Area 5B Biological Sciences",
            "5C": "Area 5C Science Lab",
        }
    else:
        area_labels = {
            "1A": "Area 1A English Composition",
            "1B": "Area 1B Critical Thinking",
            "2A": "Area 2A Math",
            "3A": "Area 3A Arts",
            "3B": "Area 3B Humanities",
            "4":  "Area 4 Social & Behavioral Sciences (3 courses)",
            "5A": "Area 5A Physical Sciences",
            "5B": "Area 5B Biological Sciences",
            "5C": "Area 5C Science Lab",
            "6":  "Area 6 Languages Other Than English",
        }
    for area_code, label in area_labels.items():
        course = result.igetc_completion.get(area_code, "NOT ASSIGNED")
        if area_code == "5C":
            five_b = result.igetc_completion.get("5B", "")
            lines.append(f"  {label}: SATISFIED by {five_b} LAB -- no separate course needed")
        elif "NOT ASSIGNED" in str(course):
            if area_code == "6" and not is_calgetc:
                lines.append(
                    f"  {label}: NOT ASSIGNED -- can be satisfied by 2+ years of the "
                    "same foreign language in high school (grade C or better); "
                    "or by completing an approved foreign language course at CC"
                )
            else:
                lines.append(f"  {label}: {course}")
        else:
            lines.append(f"  {label}: {course}")
    lines.append("")

    lines.append("## Key Notes")
    lines.append(f"- TAG: {tag_note}")
    lines.append(f"- GPA target: {gpa_range} -- {gpa_note}")
    if result.is_quarter:
        sem_equiv = round(result.total_units * (2.0 / 3.0), 1)
        if result.summer_overflow:
            lines.append(
                f"- Total units: {_fmt_units(result.total_units)} QU (approx. {_fmt_units(sem_equiv)} SU) "
                f"across 6 quarters + 1 summer session"
            )
        else:
            lines.append(
                f"- Total units: {_fmt_units(result.total_units)} quarter units "
                f"(approx. {_fmt_units(sem_equiv)} semester units) across {result.active_terms} quarters"
            )
    else:
        if result.summer_overflow:
            lines.append(f"- Total units: {_fmt_units(result.total_units)} across 4 semesters + 1 summer session")
        else:
            lines.append(f"- Total units: {_fmt_units(result.total_units)} across {result.active_terms} terms")
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
