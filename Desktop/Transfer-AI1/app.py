import json
import os
import time
from collections import defaultdict
from flask import Flask, request, Response, stream_with_context, session, jsonify
from advisor import ask_advisor_stream, ask_advisor_stream_fallback, ask_advisor_onboarding_stream, ask_plan_stream, ask_plan_stream_fallback
from db import (
    init_db, create_user, get_user_by_email, get_user_by_id,
    verify_password, email_exists, update_profile,
    create_session, get_session, get_user_sessions,
    update_session_title, delete_session,
    add_messages, get_session_messages,
    create_reset_token, redeem_reset_token,
    save_feedback,
)
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder="static")
app.secret_key = os.getenv("FLASK_SECRET", "transfer-ai-change-this-key-xyz")

init_db()

# ── Rate limiting ──────────────────────────────────────────────
# 100 requests per IP per hour
RATE_LIMIT   = 100
RATE_WINDOW  = 3600  # seconds
MAX_MSG_LEN  = 4000  # characters — enough for full course lists, essay drafts, transcripts

_rate_log = defaultdict(list)  # ip -> [timestamps]


def _get_ip():
    # Respect proxy headers if behind nginx/reverse proxy
    return request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()


def _check_rate(ip):
    now    = time.time()
    cutoff = now - RATE_WINDOW
    _rate_log[ip] = [t for t in _rate_log[ip] if t > cutoff]
    if len(_rate_log[ip]) >= RATE_LIMIT:
        return False
    _rate_log[ip].append(now)
    return True


# ── Quick off-topic guard (no LLM tokens spent) ───────────────
# Only blocks clear-cut exploitation: math homework, recipes, code
# debugging, etc. Greetings and ambiguous messages pass through to
# the LLM which handles them gracefully.
_HARD_BLOCK_PATTERNS = [
    "solve for x", "solve for y", "solve this equation",
    "find the derivative", "find the integral", "differentiate ",
    "do my homework", "finish my homework", "math homework",
    "write a story about", "write me a story",
    "recipe for ", "how to cook ", "how to bake ",
    "debug this code", "fix my code", "write this code for me",
    "what is the capital of", "who invented the ",
]


_REFUSAL = "That's a bit outside my lane — I'm best at UC transfer stuff! Is there anything about transferring I can help you with?"


def _is_obvious_offtopic(msg):
    q = msg.lower()
    return any(p in q for p in _HARD_BLOCK_PATTERNS)


# ── Routes ─────────────────────────────────────────────────────

@app.route("/")
def home():
    return app.send_static_file("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    ip = _get_ip()

    # Rate limit check
    if not _check_rate(ip):
        remaining = RATE_WINDOW - (time.time() - _rate_log[ip][0])
        minutes   = int(remaining // 60) + 1

        def rate_msg():
            msg = f"You've sent {RATE_LIMIT} messages this hour. Please wait about {minutes} minute{'s' if minutes != 1 else ''} and then continue."
            yield f"data: {json.dumps(msg)}\n\n"
            yield "data: [DONE]\n\n"

        return Response(stream_with_context(rate_msg()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache"})

    data         = request.json or {}
    user_message = data.get("message", "").strip()
    history      = list(data.get("history", []))

    # Support history-only mode: last history item is the user message
    if not user_message and history and history[-1].get("role") == "user":
        user_message = history[-1]["content"].strip()
        history = history[:-1]

    # Message length guard
    if len(user_message) > MAX_MSG_LEN:
        def too_long():
            yield f"data: {json.dumps(f'Please keep messages under {MAX_MSG_LEN} characters.')}\n\n"
            yield "data: [DONE]\n\n"
        return Response(stream_with_context(too_long()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache"})

    if not user_message:
        return Response("data: [DONE]\n\n", mimetype="text/event-stream")

    # Instant off-topic rejection (no Groq tokens used)
    if _is_obvious_offtopic(user_message):
        def offtopic():
            yield f"data: {json.dumps(_REFUSAL)}\n\n"
            yield "data: [DONE]\n\n"
        return Response(stream_with_context(offtopic()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache"})

    # Ensure history ends with the current user message
    if not history or history[-1].get("content") != user_message:
        history.append({"role": "user", "content": user_message})

    if len(history) > 20:
        history = history[-20:]

    uid = session.get("user_id")
    user_profile = get_user_by_id(uid) if uid else None

    def generate():
        try:
            for chunk in ask_advisor_stream(history, user_profile=user_profile):
                yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as e:
            err_str = str(e).lower()
            # If the primary model is rate-limited, fall back to the faster/smaller model
            if any(kw in err_str for kw in ["rate_limit", "rate limit", "429", "quota", "tokens per"]):
                try:
                    yield f"data: {json.dumps('[Note: switching to faster model — high demand right now]')}\n\n"
                    for chunk in ask_advisor_stream_fallback(history, user_profile=user_profile):
                        yield f"data: {json.dumps(chunk)}\n\n"
                except Exception:
                    yield f"data: {json.dumps('Something went wrong. Please try again in a moment.')}\n\n"
            elif "configuration" in err_str or "api_key" in err_str:
                yield f"data: {json.dumps(f'Configuration error: {e}')}\n\n"
            else:
                yield f"data: {json.dumps('Something went wrong. Please try again.')}\n\n"
        yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/reset", methods=["POST"])
def reset():
    return ("", 204)


# ── Plan generation ────────────────────────────────────────────────────────

# IGETC data loaded once on first use
_IGETC_DATA = None

def _load_igetc():
    import gzip as _gz
    global _IGETC_DATA
    if _IGETC_DATA is not None:
        return _IGETC_DATA
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "igetc_map.json")
    for path in (base + ".gz", base):
        if not os.path.exists(path):
            continue
        try:
            opener = _gz.open if path.endswith(".gz") else open
            with opener(path, "rt", encoding="utf-8") as f:
                _IGETC_DATA = json.load(f)
            return _IGETC_DATA
        except Exception:
            break
    _IGETC_DATA = {}
    return _IGETC_DATA


# Required IGETC areas for the UC Transfer Curriculum (most majors)
_IGETC_REQUIRED = [
    ("1A", "English Composition",                     1),
    ("1B", "Critical Thinking / English Composition", 1),
    ("2A", "Mathematical Concepts",                   1),
    ("3A", "Arts",                                    1),
    ("3B", "Humanities",                              1),
    ("4",  "Social & Behavioral Sciences",            3),
    ("5A", "Physical Sciences",                       1),
    ("5B", "Biological Sciences",                     1),
    ("6",  "Languages Other Than English",            1),
]


def _extract_igetc_courses(college: str) -> str:
    """
    Return a block listing 3-5 real IGETC-approved courses per required area
    for the given community college, so the AI picks actual catalog courses.
    """
    data = _load_igetc()
    if not data:
        return ""

    by_school = data.get("bySchool", {})
    # Case-insensitive college match
    school_key = next((k for k in by_school if k.lower() == college.lower()), None)
    if not school_key:
        # Partial match fallback
        school_key = next((k for k in by_school if college.lower() in k.lower()), None)
    if not school_key:
        return ""

    by_area = by_school[school_key].get("byArea", {})
    if not by_area:
        return ""

    lines = [
        f"=== IGETC COURSES AVAILABLE AT {college} ===",
        "The schedule MUST include courses covering ALL required IGETC areas below.",
        "Use ONLY courses listed here for IGETC slots — do not invent course numbers.",
        "NOTE: Area 6 (Languages Other Than English) — if no course is listed, the student may satisfy this with 2+ years of the same HS foreign language (C or better). Include a note about this in Key Notes.",
        "",
    ]

    for area_code, area_name, needed in _IGETC_REQUIRED:
        courses = by_area.get(area_code, [])
        if not courses:
            continue
        seen_nums = set()
        unique = []
        for c in courses:
            prefix = c.get("prefix", "").upper()
            title  = c.get("title", "").upper()
            # Strip ESL and non-native-speaker courses — they don't belong in transfer plans
            if prefix.startswith("ESL") or "ENGLISH AS A SECOND" in title or "ESL" in title:
                continue
            key = (c.get("prefix",""), c.get("number",""))
            if key not in seen_nums:
                seen_nums.add(key)
                unique.append(c)
        if not unique:
            continue
        sample = unique[:5]
        course_strs = [
            f"{c.get('prefix','')} {c.get('number','')} - {c.get('title','')} ({c.get('units','?')} units)"
            for c in sample
        ]
        lines.append(f"Area {area_code} — {area_name} (need {needed} course{'s' if needed > 1 else ''}):")
        for cs in course_strs:
            lines.append(f"  • {cs}")
        if len(courses) > 5:
            lines.append(f"  (+ {len(courses)-5} more options)")
        lines.append("")

    lines.append("=== END IGETC DATA ===")
    return "\n".join(lines)

_UC_NAME_MAP = {
    "ucla":          "los angeles",
    "uc la":         "los angeles",
    "los angeles":   "los angeles",
    "ucb":           "berkeley",
    "uc berkeley":   "berkeley",
    "cal":           "berkeley",
    "berkeley":      "berkeley",
    "ucsd":          "san diego",
    "uc san diego":  "san diego",
    "san diego":     "san diego",
    "uci":           "irvine",
    "uc irvine":     "irvine",
    "irvine":        "irvine",
    "ucsb":          "santa barbara",
    "uc santa barbara": "santa barbara",
    "santa barbara": "santa barbara",
    "ucd":           "davis",
    "uc davis":      "davis",
    "davis":         "davis",
    "ucsc":          "santa cruz",
    "uc santa cruz": "santa cruz",
    "santa cruz":    "santa cruz",
    "ucr":           "riverside",
    "uc riverside":  "riverside",
    "riverside":     "riverside",
    "ucm":           "merced",
    "uc merced":     "merced",
    "merced":        "merced",
}


# Real average transfer GPA ranges per UC (Fall 2025 official data)
_UC_GPA_TARGETS = {
    "los angeles":   ("3.7–3.9", "UCLA avg admitted transfer GPA is 3.5–3.9. Economics is highly competitive — target 3.7 minimum, aim for 3.9."),
    "berkeley":      ("3.7–3.9", "UC Berkeley avg admitted transfer GPA is 3.5–3.9. Economics is competitive — target 3.7 minimum, aim for 3.9."),
    "san diego":     ("3.7–3.9", "UCSD avg admitted transfer GPA is 3.55–3.94 — target 3.7+."),
    "irvine":        ("3.6–3.7", "UCI avg admitted transfer GPA is 3.4–3.7 — target 3.6+."),
    "santa barbara": ("3.6–3.7", "UCSB avg admitted transfer GPA is 3.4–3.7 — target 3.6+."),
    "davis":         ("3.6–3.7", "UC Davis avg admitted transfer GPA is 3.4–3.7 — target 3.6+."),
    "santa cruz":    ("3.5–3.6", "UCSC avg admitted transfer GPA is 3.3–3.6 — target 3.5+."),
    "riverside":     ("3.3–3.5", "UCR avg admitted transfer GPA is 3.0–3.5 — target 3.3+."),
    "merced":        ("3.2–3.4", "UC Merced avg admitted transfer GPA is 3.0–3.4 — target 3.2+."),
}

# UC shard name → loaded shard dict (loaded lazily per UC)
_ART_SHARDS: dict = {}

# Maps canonical UC name → shard filename stem
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


def _load_uc_shard(uc_canonical: str) -> dict:
    """Load (and cache) the shard for the given canonical UC name. Returns {} on failure."""
    import gzip as _gz
    shard_name = _UC_SHARD_MAP.get(uc_canonical)
    if not shard_name:
        return {}
    if shard_name in _ART_SHARDS:
        return _ART_SHARDS[shard_name]
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", f"articulations_{shard_name}.json")
    for path in (base + ".gz", base):
        if not os.path.exists(path):
            continue
        try:
            opener = _gz.open if path.endswith(".gz") else open
            with opener(path, "rt", encoding="utf-8") as f:
                shard = json.load(f)
            _ART_SHARDS[shard_name] = shard
            return shard
        except Exception:
            break
    _ART_SHARDS[shard_name] = {}
    return {}


def _extract_major_prep(college: str, uc: str, major: str) -> str:
    """
    Load only the UC-specific shard (<1 MB each) and find the best CC+major match.
    """
    college_l = college.lower()
    uc_l      = _UC_NAME_MAP.get(uc.lower().strip(), uc.lower())
    major_l   = major.lower()

    shard = _load_uc_shard(uc_l)
    if not shard:
        return ""

    best_score, best_key = 0.0, None
    for key in shard:
        parts = key.split("__")
        if len(parts) < 3:
            continue
        cc_l_k  = parts[0].replace("_", " ").lower()
        maj_l_k = "__".join(parts[2:]).replace("_", " ").lower()

        cc_words  = [w for w in cc_l_k.split()  if len(w) >= 3]
        maj_words = [w for w in maj_l_k.split() if len(w) >= 4]

        cc_hit  = sum(1 for w in cc_words  if w in college_l or college_l in w) / max(len(cc_words), 1)
        maj_hit = sum(1 for w in maj_words if w in major_l  or major_l  in w)  / max(len(maj_words), 1)

        score = cc_hit * 5 + maj_hit * 5
        if score > best_score:
            best_score = score
            best_key   = key

    if not best_key or best_score < 2.0:
        return ""

    arts = shard[best_key]
    kparts = best_key.split("__")
    uc_display    = kparts[1].replace("_", " ") if len(kparts) > 1 else uc
    major_display = "__".join(kparts[2:]).replace("_", " ") if len(kparts) > 2 else major

    lines = [
        f"=== VERIFIED ARTICULATION DATA: {college} -> {uc_display} | {major_display} ===",
        "Source: ASSIST.org (authoritative - do not deviate from this list)",
        "",
        "The student MUST complete the following courses at their community college.",
        "Use ONLY these exact course numbers and titles. Do not substitute.",
        "",
    ]
    for art in arts:
        uc_c   = art.get("uc", {})
        uc_str = f"{uc_c.get('p','')} {uc_c.get('n','')} - {uc_c.get('t','')}"
        lines.append(f"UC requires: {uc_str}")
        for grp in art.get("cc", []):
            parts_cc = []
            for c in grp:
                parts_cc.append(
                    f"{c.get('p','')} {c.get('n','')} - {c.get('t','')} ({c.get('u','?')} units)"
                )
            conj = grp[0].get("j", "Or") if grp else "Or"
            lines.append(f"  -> Enroll in: {f' {conj} '.join(parts_cc)}")
    lines.append("")
    lines.append("=== END ARTICULATION DATA ===")
    return "\n".join(lines)


@app.route("/plan", methods=["POST"])
def plan():
    ip = _get_ip()
    if not _check_rate(ip):
        def rate_msg():
            yield f"data: {json.dumps('Rate limit reached. Please wait a moment.')}\n\n"
            yield "data: [DONE]\n\n"
        return Response(stream_with_context(rate_msg()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache"})

    data          = request.json or {}
    college       = data.get("college", "").strip()
    school        = data.get("school", "").strip()
    major         = data.get("major", "").strip()
    completed     = data.get("completedCourses", "").strip()
    accept_honors = data.get("acceptHonors", True)
    ap_credits    = data.get("apCredits", "").strip()
    hs_math       = data.get("hsMath", "").strip()

    if not college or not school or not major:
        def err():
            yield f"data: {json.dumps('Missing college, school, or major.')}\n\n"
            yield "data: [DONE]\n\n"
        return Response(stream_with_context(err()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache"})

    # Pre-extract articulation data and IGETC courses for this CC
    major_prep_block = _extract_major_prep(college, school, major)
    igetc_block      = _extract_igetc_courses(college)
    completed_str    = completed if completed else "none"
    honors_rule      = "" if accept_honors else "\n0. HONORS — HIGHEST PRIORITY RULE: The student has DECLINED honors courses. This overrides everything. NEVER include any course whose number ends in 'H' (e.g. ECON 1H, MATH 1AH, ENGL 1AH) or whose title contains 'Honors'. If the only option for a requirement is an honors course, use the non-honors equivalent instead."

    # Build background section (AP credit + HS math)
    background_lines = []
    if ap_credits:
        background_lines.append(f"AP EXAM CREDIT (treat as completed prerequisites): {ap_credits}")
    if hs_math:
        background_lines.append(f"HIGH SCHOOL MATH COMPLETED: {hs_math} — this satisfies the prerequisite for the next course in the math sequence (e.g. Pre-Calculus in HS → student is eligible for Calculus I at the CC).")
    ap_section = ("\n" + "\n".join(background_lines)) if background_lines else "\nNo AP credit or HS math background provided."

    # Detect fresh-start student: no completed courses AND no AP credit
    # Math: always assume student completed Pre-Calculus in HS — they can take Calc I
    fresh_start = (not completed) and (not ap_credits)
    fresh_start_rule = (
        "\n   FRESH START: This student has no prior college courses. "
        "In Term 1, only place courses with no prerequisites EXCEPT: "
        "Calculus I is always allowed (assume HS Pre-Calculus is satisfied). "
        "Do NOT place Critical Thinking, Calc II, or any course requiring another college course in Term 1."
    ) if fresh_start else ""

    if major_prep_block:
        articulation_section = major_prep_block
    else:
        articulation_section = (f"No exact agreement found for {college} -> {school} {major}. "
                                f"Use your ASSIST knowledge — mark each suggestion '(verify on ASSIST.org)'.")

    igetc_section = f"\n\n{igetc_block}" if igetc_block else ""

    uc_l_for_gpa = _UC_NAME_MAP.get(school.lower().strip(), school.lower())
    gpa_range, gpa_note = _UC_GPA_TARGETS.get(uc_l_for_gpa, ("3.5+", f"Target 3.5+ for {school}."))

    prompt = f"""You are building a complete 4-term UC transfer schedule for a student at {college} transferring to {school} for {major}.

{articulation_section}{igetc_section}

Already completed — EXCLUDE ENTIRELY: {completed_str}
{ap_section}

===== STEP 1: ASSEMBLE YOUR REQUIRED COURSE POOL =====
Before writing any terms, you must identify every course that will appear in the schedule:

A) MAJOR PREP — list every course from the articulation data above. These are mandatory.

B) IGETC — pick exactly ONE course per required area from the IGETC list above:
   - Area 1A: one first-year English Composition course (NOT ESL)
   - Area 1B: one Critical Thinking course (must come AFTER Area 1A)
   - Area 2A: one Math course (Calculus counts if listed)
   - Area 3A: one Arts course
   - Area 3B: one Humanities course
   - Area 4: three Social/Behavioral Science courses (ECON 1 and ECON 2 count here)
   - Area 5A: one Physical Science course
   - Area 5B: one Biological Science course
   - Area 6: one foreign language course, OR note HS proficiency fallback
{'' if accept_honors else '   DO NOT pick any course whose number ends in H (e.g. ECON 1H) — use non-honors only.'}
If a major prep course satisfies an IGETC area, count it for both — do NOT add a separate IGETC course for that area.
Every course in the pool must appear exactly once in the final schedule.

===== STEP 2: DISTRIBUTE ACROSS 4 TERMS =====
Rules:{honors_rule}
- Each term: 12–16 units, 3–5 courses. Any term under 12 units is INVALID.
- Prerequisites: Area 1A before 1B. Calculus I → II → III. No course before its prereq.
- No ESL courses (prefix ESL or title containing "English as a Second Language").
- No invented course numbers — use only exact courses from the data above.
- No {school} course numbers — only {college} courses.
- No already-completed courses.
- Each course appears exactly ONCE across all 4 terms.

===== STEP 3: OUTPUT =====
Start directly with ## Term 1 (Fall). No preamble.

## Term 1 (Fall)
- COURSE# — Official Title (X units) [Area Xn / Major Prep if applicable]

## Term 2 (Spring)
- COURSE# — Official Title (X units) [Area Xn]

## Term 3 (Fall)
- COURSE# — Official Title (X units) [Area Xn]

## Term 4 (Spring)
- COURSE# — Official Title (X units) [Area Xn]

## Major Prep Summary
- [Each UC requirement → which {college} course fulfills it]

## IGETC Completion
(ONLY check ✅ if that course appears in the schedule above)
- Area 1A: ✅/❌ COURSE#
- Area 1B: ✅/❌ COURSE#
- Area 2A: ✅/❌ COURSE#
- Area 3A: ✅/❌ COURSE#
- Area 3B: ✅/❌ COURSE#
- Area 4: ✅/❌ COURSE#, COURSE#, COURSE#
- Area 5A: ✅/❌ COURSE#
- Area 5B: ✅/❌ COURSE#
- Area 6: ✅/❌ COURSE# or ⚠️ satisfy with 2+ years HS foreign language

## Key Notes
- TAG: [eligible/not and why]
- GPA target: {gpa_range} — {gpa_note}"""

    def generate():
        try:
            for chunk in ask_plan_stream(prompt):
                yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as e:
            err_str = str(e).lower()
            if any(kw in err_str for kw in ["rate_limit", "429", "quota", "tokens per"]):
                try:
                    for chunk in ask_plan_stream_fallback(prompt):
                        yield f"data: {json.dumps(chunk)}\n\n"
                except Exception:
                    yield f"data: {json.dumps('Something went wrong generating your plan. Please try again.')}\n\n"
            else:
                yield f"data: {json.dumps('Something went wrong generating your plan. Please try again.')}\n\n"
        yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/onboard", methods=["POST"])
def onboard():
    data    = request.json or {}
    history = list(data.get("history", []))
    if len(history) > 20:
        history = history[-20:]
    # Groq requires conversations to start with a user message.
    # Prepend a synthetic opener to preserve AI context rather than stripping it.
    if not history or history[0].get("role") == "assistant":
        history = [{"role": "user", "content": "Hi, I want to set up my transfer plan."}] + history

    def generate():
        try:
            for chunk in ask_advisor_onboarding_stream(history):
                yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps('Something went wrong. Please try again.')}\n\n"
        yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Auth routes ────────────────────────────────────────────────

@app.route("/auth/me")
def auth_me():
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "not authenticated"}), 401
    user = get_user_by_id(uid)
    if not user:
        session.clear()
        return jsonify({"error": "not authenticated"}), 401
    return jsonify(_public(user))


def _public(user):
    """Serialize user fields safe to send to the browser."""
    return {
        "id":             user["id"],
        "email":          user["email"],
        "username":       user["username"],
        "college":        user.get("college", ""),
        "major":          user.get("major", ""),
        "target_schools": user.get("target_schools", ""),
        "onboarded":      bool(user.get("onboarded", 0)),
    }


@app.route("/auth/register", methods=["POST"])
def auth_register():
    data     = request.json or {}
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password", "")
    username = (data.get("username") or "").strip()

    if not email or "@" not in email:
        return jsonify({"error": "Enter a valid email address."}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400
    if email_exists(email):
        return jsonify({"error": "An account with that email already exists."}), 409

    try:
        user = create_user(email, password, username or None)
        session["user_id"] = user["id"]
        return jsonify(_public(user))
    except Exception:
        return jsonify({"error": "Could not create account. Please try again."}), 500


@app.route("/auth/login", methods=["POST"])
def auth_login():
    data     = request.json or {}
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password", "")

    user = get_user_by_email(email)
    if not user or not verify_password(user, password):
        return jsonify({"error": "Incorrect email or password."}), 401

    session["user_id"] = user["id"]
    return jsonify(_public(user))


@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return ("", 204)


@app.route("/auth/forgot-password", methods=["POST"])
def auth_forgot():
    email = ((request.json or {}).get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "Enter your email address."}), 400
    token, user = create_reset_token(email)
    if not token:
        # Don't reveal whether account exists — return success either way
        return jsonify({"ok": True, "hint": "If that email has an account, a reset token was generated."})
    # In production, email the token. Without SMTP, return the token directly
    # so the user can paste it into the reset form.
    return jsonify({"ok": True, "token": token, "username": user["username"]})


@app.route("/auth/reset-password", methods=["POST"])
def auth_reset():
    data     = request.json or {}
    token    = (data.get("token") or "").strip()
    password = data.get("password", "")
    if not token:
        return jsonify({"error": "Reset token is required."}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400
    if not redeem_reset_token(token, password):
        return jsonify({"error": "Invalid or expired reset token."}), 400
    return jsonify({"ok": True})


# ── Profile ────────────────────────────────────────────────────────

@app.route("/api/profile", methods=["GET"])
def api_profile_get():
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Not authenticated"}), 401
    user = get_user_by_id(uid)
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    return jsonify(_public(user))


@app.route("/api/profile", methods=["PUT"])
def api_profile_put():
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Not authenticated"}), 401
    data = request.json or {}
    fields = {}
    for k in ("username", "college", "major", "target_schools", "onboarded"):
        if k in data:
            fields[k] = data[k]
    if "username" in fields and not str(fields["username"]).strip():
        return jsonify({"error": "Username cannot be blank."}), 400
    update_profile(uid, **fields)
    return jsonify(_public(get_user_by_id(uid)))


# ── Chat sessions ──────────────────────────────────────────────────

@app.route("/api/sessions", methods=["GET"])
def api_sessions_list():
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Not authenticated"}), 401
    return jsonify(get_user_sessions(uid))


@app.route("/api/sessions", methods=["POST"])
def api_sessions_create():
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Not authenticated"}), 401
    title = ((request.json or {}).get("title") or "New chat")[:80]
    sess  = create_session(uid, title)
    return jsonify(sess), 201


@app.route("/api/sessions/<int:sid>", methods=["PATCH"])
def api_sessions_update(sid):
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Not authenticated"}), 401
    title = ((request.json or {}).get("title") or "")[:80].strip()
    if title:
        update_session_title(sid, uid, title)
    return jsonify(get_session(sid, uid) or {})


@app.route("/api/sessions/<int:sid>", methods=["DELETE"])
def api_sessions_delete(sid):
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Not authenticated"}), 401
    delete_session(sid, uid)
    return ("", 204)


# ── Chat messages ──────────────────────────────────────────────────

@app.route("/api/sessions/<int:sid>/messages", methods=["GET"])
def api_messages_get(sid):
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Not authenticated"}), 401
    msgs = get_session_messages(sid, uid)
    if msgs is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify(msgs)


@app.route("/api/sessions/<int:sid>/messages", methods=["POST"])
def api_messages_post(sid):
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Not authenticated"}), 401
    data = request.json or {}
    msgs = data.get("messages", [])
    if not isinstance(msgs, list) or not msgs:
        return jsonify({"error": "messages list required"}), 400
    # Validate shape
    for m in msgs:
        if m.get("role") not in ("user", "assistant") or not m.get("content"):
            return jsonify({"error": "Each message needs role and content"}), 400
    if not add_messages(sid, uid, msgs):
        return jsonify({"error": "Not found"}), 404
    return ("", 204)


# ── Feedback ───────────────────────────────────────────────────────

@app.route("/api/feedback", methods=["POST"])
def api_feedback():
    uid  = session.get("user_id")
    data = request.json or {}
    sid  = data.get("session_id")
    rating = data.get("rating")
    if rating not in (1, -1):
        return jsonify({"error": "rating must be 1 or -1"}), 400
    save_feedback(uid, sid, rating)
    return ("", 204)


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
