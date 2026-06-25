import json
import os
import time
from collections import defaultdict
from flask import Flask, request, Response, stream_with_context, session, jsonify
from advisor import ask_advisor_stream, ask_advisor_stream_fallback, ask_advisor_onboarding_stream
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
