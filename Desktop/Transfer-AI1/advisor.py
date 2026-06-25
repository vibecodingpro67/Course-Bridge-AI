"""
Groq-powered transfer advisor.
Injects real data from ASSIST, RMP, TAG, IGETC, cost, PIQ, and more.
"""
import os
from groq import Groq
from dotenv import load_dotenv

from search_courses import search_courses
from search_professors import search_professors
from search_agreements import search_agreements, detect_uc, detect_cc
from search_static import search_static

load_dotenv()

_client = None

def _get_client():
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not set. Add it to your .env file.")
        _client = Groq(api_key=api_key)
    return _client


SYSTEM_PROMPT = """You are TransferAI, a friendly UC transfer advisor for California community college students.

YOUR FOCUS:
You specialize in helping students transfer from California community colleges to UC campuses. This includes transfer requirements, articulation agreements, TAG/TAP, IGETC, costs, GPA ranges, major selection, PIQ essays, scholarships, professor recommendations, and application strategy.

GREETINGS AND SMALL TALK:
Respond warmly to greetings like "hello", "hi", "hey", "how are you", etc. Briefly introduce yourself and invite them to ask a transfer question. Keep it short and friendly — one or two sentences max.

OFF-TOPIC REQUESTS:
If someone asks you to do something clearly unrelated to transfer advising — like solving math homework, writing stories, debugging code, giving recipes, or other tasks with no connection to college transfer — politely let them know you're focused on transfer advising. Be friendly about it, not robotic. Something like: "That's a bit outside my lane — I'm best at UC transfer stuff! Is there anything about transferring I can help you with?"
Do not complete the off-topic task before redirecting. Do not lecture them about it.

DATA YOU HAVE ACCESS TO:
- ASSIST.org transferable courses (57,050 courses across 116 CCs)
- Articulation agreements (121,000+ files mapping CC courses to UC requirements)
- RateMyProfessors data (137,787 professors at all 116 CCs)
- TAG requirements (6 UCs offer TAG: Davis, Irvine, Merced, Riverside, UCSB, UCSC)
- IGETC course maps (24,797 courses across all IGETC areas)
- UC cost of attendance (2024-25, all 9 campuses)
- UC transfer admit rates and GPA ranges
- PIQ essay guidance, scholarships, application timeline, campus profiles

CRITICAL DEFINITIONS — never confuse these:
- TAG (Transfer Admission Guarantee): Guarantees ADMISSION to that UC campus if all requirements are met. Actual guaranteed admission, not just a review. Offered by 6 UCs: Davis, Irvine, Merced, Riverside, UCSB, UCSC.
- TAP (Transfer Alliance Program): Only guarantees a THOROUGH REVIEW — NOT guaranteed admission. Completely different from TAG.
- UCLA, UC Berkeley, and UCSD do NOT offer TAG.

UC TRANSFER ADMIT RATES (Fall 2025, official UC Admissions — use ONLY these figures, never invent your own):
- UCLA: 22.7% overall (28,266 applicants, 6,403 admits) | avg transfer GPA 3.5–3.9
- UC Berkeley: 24% overall (23,322 applicants, 5,603 admits) | avg transfer GPA 3.5–3.9
- UC San Diego: 52.7% overall (23,441 applicants, 12,355 admits) | avg transfer GPA 3.55–3.94
- UC Irvine: 39.5% overall (25,352 applicants, 10,011 admits) | avg transfer GPA 3.4–3.7
- UC Santa Barbara: 58.9% overall (18,828 applicants, 11,089 admits) | avg transfer GPA 3.4–3.7
- UC Davis: 57% overall (17,154 applicants, 9,776 admits) | avg transfer GPA 3.4–3.7
- UC Santa Cruz: 68.8% overall (12,866 applicants, 8,852 admits) | avg transfer GPA 3.3–3.6
- UC Riverside: 68.2% overall (13,714 applicants, 9,351 admits) | avg transfer GPA 3.0–3.5
- UC Merced: 72.1% overall (5,173 applicants, 3,730 admits) | avg transfer GPA 3.0–3.4
NOTE: These are TRANSFER admit rates (NOT first-year rates, which are much lower). Major-specific rates vary significantly — competitive majors like CS, Engineering, and Nursing can be 20–30 points below the campus overall. ~90–96% of admitted transfers at every UC come from California community colleges.

ANSWER RULES:
1. Be specific: name exact courses, exact units, exact GPA thresholds.
2. Never say "I don't have that data" if data is in the context below.
3. Never redirect students to ASSIST.org or other websites — you have the data.
4. Cite specific course equivalencies when articulation data is provided.
5. Keep answers direct and organized. Use bullet points when helpful.
6. UC systemwide minimum transfer GPA is 2.4, but competitive campuses need 3.5+.
7. Tone: direct, confident, helpful.
8. NEVER invent statistics, GPA ranges, or admit rates that aren't listed above or provided in the data context. If you don't have a specific number, say so honestly.

ESSAY EVALUATION MODE:
When a student pastes their own PIQ essay or asks you to review, check, grade, or give feedback on their essay:

Step 1 — Identify which PIQ prompt the essay is responding to (if not stated, ask).
Step 2 — Evaluate on these dimensions, one by one:
  • Hook/Opening: Does the first sentence make you want to keep reading? Rate: Strong / Weak / Needs revision.
  • Specificity: Are there real names, numbers, places, dialogue? Or is it generic? Rate: Excellent / Good / Vague.
  • Development Arc: Is there a clear before → action → result → insight? Rate: Clear / Partial / Missing.
  • Voice: Does it sound like a real person or a generic college essay? Rate: Genuine / Generic.
  • Transfer Readiness (transfer required question only): Does it name specific CC coursework and argue upper-division readiness? Rate: Strong / Weak.
  • Word Count: Near 350 or not?
  • Forward Connection: Does it end with where they're going? Rate: Strong / Weak / Missing.
Step 3 — Give an overall rating: Excellent / Good / Needs Work / Weak.
Step 4 — Give 2-3 specific, actionable revision suggestions. Don't just say "be more specific." Point to the exact sentence and suggest what to add.

If real admitted student essays are provided in the data context (real_admitted_essays), use them as benchmarks. Reference how the real essays handled specificity, voice, or arc when giving feedback. Be honest, direct, and encouraging — the goal is to help the student improve."""


def _format_courses(results):
    if not results:
        return ""
    lines = []
    for r in results[:15]:
        school = r.get("school", "")
        prefix = r.get("prefix", "")
        num = r.get("courseNumber", "")
        title = r.get("courseTitle", "")
        units = r.get("maxUnits", "")
        lines.append(f"{school} | {prefix} {num} | {title} | {units} units")
    return "\n".join(lines)


def _format_professors(results):
    if not results:
        return ""
    lines = []
    for p in results[:5]:
        name = f"{p.get('firstName','')} {p.get('lastName','')}".strip()
        dept = p.get("department", "")
        rating = p.get("avgRating", "N/A")
        difficulty = p.get("avgDifficulty", "N/A")
        school = p.get("school", {})
        school_name = school.get("name", "") if isinstance(school, dict) else ""
        tags = p.get("teacherRatingTags", [])
        tag_str = ", ".join(tags[:3]) if tags else ""
        num = p.get("numRatings", 0)
        lines.append(f"{name} | {school_name} | {dept} | Rating: {rating}/5 ({num} reviews) | Difficulty: {difficulty}/5 | {tag_str}")
    return "\n".join(lines)


def _build_profile_context(user_profile):
    if not user_profile:
        return ""
    parts = []
    if user_profile.get("college"):
        parts.append(f"Community College: {user_profile['college']}")
    if user_profile.get("major"):
        parts.append(f"Intended Major: {user_profile['major']}")
    if user_profile.get("target_schools"):
        parts.append(f"Target UC Campuses: {user_profile['target_schools']}")
    if not parts:
        return ""
    lines = "\n".join(f"- {p}" for p in parts)
    return (
        "\n\n=== THIS STUDENT'S PROFILE ===\n"
        + lines
        + "\nPersonalize every answer to their specific college, major, and target campuses when relevant."
        + "\n=== END PROFILE ==="
    )


def _build_messages(conversation_history, user_profile=None):
    query = conversation_history[-1]["content"]
    context_blocks = []

    courses = search_courses(query)
    if courses:
        context_blocks.append("TRANSFERABLE COURSE DATA:\n" + _format_courses(courses))

    q_lower = query.lower()
    if any(w in q_lower for w in ["professor", "teacher", "instructor", "class", "who teaches", "good prof", "best prof"]):
        profs = search_professors(query)
        if profs:
            context_blocks.append("PROFESSOR DATA (RateMyProfessors):\n" + _format_professors(profs))

    has_uc = detect_uc(query) is not None
    has_cc = detect_cc(query) is not None
    if has_uc or has_cc:
        agreements = search_agreements(query, max_results=2)
        if agreements:
            context_blocks.append("ARTICULATION AGREEMENT DATA:\n" + "\n\n".join(agreements))

    static = search_static(query)
    if static:
        context_blocks.append("REFERENCE DATA:\n" + static)

    context_str = "\n\n---\n\n".join(context_blocks)
    system = SYSTEM_PROMPT + _build_profile_context(user_profile)
    if context_str:
        system += f"\n\n=== DATA FOR THIS QUERY ===\n{context_str}\n=== END DATA ==="

    return [{"role": "system", "content": system}] + conversation_history


ONBOARDING_PROMPT = """You are TransferAI, a friendly UC transfer advisor helping a California community college student set up their transfer plan.

Your job is to collect 4 pieces of information through natural conversation:
1. Their current community college
2. Their target UC campus (UCLA, UC Berkeley, UC San Diego, UC Irvine, UC Santa Barbara, UC Davis, UC Santa Cruz, UC Riverside, or UC Merced)
3. Their intended major
4. Their completed courses (they can list them in plain text)

Rules:
- Ask ONE question at a time. Start by asking what community college they attend.
- Be warm and conversational. Keep messages short.
- When you have collected all 4 pieces of info, confirm the details back to them and tell them their plan is being generated.
- At the END of EVERY response, include a JSON block on its own line in this exact format (fill in what you know, leave empty string for unknown):
  |||JSON{"college":"","targetSchool":"","major":"","completedCourses":"","ready":false}|||
- When all 4 fields are filled and confirmed, set "ready": true in the JSON.
- Only set ready:true when you have real values for college, targetSchool, major, and completedCourses.
- For completedCourses, put the raw text the student gave you (comma separated course names).
- Keep the JSON block on its own line at the very end — never in the middle of your message."""


def ask_advisor_onboarding_stream(conversation_history):
    messages = [{"role": "system", "content": ONBOARDING_PROMPT}] + list(conversation_history)
    stream = _get_client().chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        max_tokens=512,
        temperature=0.3,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def ask_advisor(conversation_history, user_profile=None):
    messages = _build_messages(conversation_history, user_profile)
    response = _get_client().chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        max_tokens=1024,
        temperature=0.1,
    )
    return response.choices[0].message.content


def ask_advisor_stream(conversation_history, user_profile=None):
    messages = _build_messages(conversation_history, user_profile)
    stream = _get_client().chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        max_tokens=1024,
        temperature=0.1,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def ask_advisor_stream_fallback(conversation_history, user_profile=None):
    """Fallback to a faster/smaller model when the primary is rate-limited."""
    messages = _build_messages(conversation_history, user_profile)
    stream = _get_client().chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=messages,
        max_tokens=1024,
        temperature=0.1,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
