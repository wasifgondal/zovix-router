import os
import hmac
import hashlib
import time
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ── SENSITIVE KEYWORDS ───────────────────────────────────
SENSITIVE_KEYWORDS = [
    "invoice", "payment", "paid", "pay", "bank", "transfer",
    "contract", "price", "pricing", "rate", "rates", "cost",
    "budget", "discount", "refund", "charge", "billing",
    "dollar", "pound", "usd", "gbp", "pkr", "salary",
    "deposit", "wire", "paypal", "wise", "stripe",
    "confidential", "private", "personal",
]

# EDITOR keywords
EDITOR_KEYWORDS = [
    "edit", "editing", "cut", "trim", "footage", "video",
    "caption", "subtitle", "music", "sound", "format",
    "export", "render", "transition", "effect", "color",
    "9:16", "1:1", "4:5", "reel", "short", "clip",
]

# WRITER keywords
WRITER_KEYWORDS = [
    "script", "write", "writing", "hook", "copy", "caption",
    "content", "text", "draft", "story", "angle", "concept",
    "headline", "ad copy", "voiceover", "narration",
]

def is_sensitive(text):
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in SENSITIVE_KEYWORDS)

def route_by_keywords(text):
    """
    Fallback keyword-based routing without Claude.
    Returns a LIST of task dicts to support mixed messages,
    e.g. a message with both editing and writing keywords
    returns two separate tasks.
    """
    text_lower = text.lower()

    editor_score = sum(1 for k in EDITOR_KEYWORDS if k in text_lower)
    writer_score = sum(1 for k in WRITER_KEYWORDS if k in text_lower)

    print(f"Editor score: {editor_score}, Writer score: {writer_score}")

    tasks = []
    if editor_score > 0:
        tasks.append({"destination": "EDITOR", "summary": text[:200]})
    if writer_score > 0:
        tasks.append({"destination": "WRITER", "summary": text[:200]})

    if not tasks:
        tasks.append({"destination": "MANAGEMENT", "summary": text[:200]})

    return tasks

def route_with_claude(text, channel):
    """
    Ask Claude to read the message and return a LIST of tasks.
    A single message can contain multiple distinct tasks
    (e.g. one editing request + one writing request) —
    Claude should split them out rather than picking just one.
    Falls back to keyword routing on any failure.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("No Claude API key — using keyword routing")
        return route_by_keywords(text)

    try:
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 500,
            "system": """You route Slack messages for a video agency.

A single message can contain MULTIPLE distinct tasks — for example, a
client might ask for a video edit AND a new script in the same message.
You must identify EVERY distinct task in the message and return one
entry per task. Do not merge unrelated tasks into a single summary,
and do not drop any task.

Respond ONLY with valid JSON in this exact format:
{
  "tasks": [
    {"destination": "EDITOR"|"WRITER"|"MANAGEMENT"|"SENSITIVE", "summary": "complete task summary"}
  ]
}

Rules:
- EDITOR: video editing, captions, cuts, formats, music/sound, exports
- WRITER: scripts, hooks, ad copy, writing tasks
- SENSITIVE: payments, invoices, pricing, contracts, anything financial
- MANAGEMENT: general questions, approvals, complaints, anything unclear
- If the message has 3+ points for the SAME destination, combine them
  into one task for that destination with a bullet list (using •) in
  the summary — do not omit any point.
- If the message has tasks for DIFFERENT destinations (e.g. one editor
  task and one writer task), return them as SEPARATE entries in the
  "tasks" array so each team only sees their own task.
- Always include every requested change, deadline, or detail the
  client mentioned somewhere in the relevant task's summary.""",
            "messages": [{"role": "user", "content": f"Channel: #{channel}\nMessage: {text}"}]
        }
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=15
        )
        data = resp.json()
        print(f"Claude response: {data}")

        if "content" in data:
            raw = data["content"][0]["text"].strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = json.loads(raw.strip())
            tasks = result.get("tasks", [])
            if not tasks:
                # Claude returned no tasks — fall back safely
                return [{"destination": "MANAGEMENT", "summary": text[:200]}]
            return tasks
        else:
            print(f"Claude error: {data}")
            return route_by_keywords(text)
    except Exception as e:
        print(f"Claude routing failed: {e} — using keywords")
        return route_by_keywords(text)

# ── TELEGRAM ─────────────────────────────────────────────
def send_telegram(chat_id, message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print(f"ERROR: No Telegram token. Would send to {chat_id}: {message}")
        return
    if not chat_id:
        print("ERROR: No chat_id provided — skipping send")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        print(f"Telegram response: {resp.json()}")
    except Exception as e:
        print(f"Telegram error: {e}")

def format_message(destination, channel, summary, priority="NORMAL"):
    emoji = {"EDITOR": "✂️", "WRITER": "✍️", "MANAGEMENT": "📋"}.get(destination, "📋")
    label = {"EDITOR": "EDITOR TASK", "WRITER": "WRITER TASK", "MANAGEMENT": "MANAGEMENT"}.get(destination, "NEW TASK")
    priority_dot = {"URGENT": "🔴", "NORMAL": "🟡", "LOW": "🟢"}.get(priority, "🟡")
    return (
        f"{priority_dot} <b>{emoji} {label}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📁 <b>Client:</b> #{channel}\n"
        f"📝 <b>Task:</b> {summary}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"<i>— Zovix System</i>"
    )

# ── SLACK VERIFICATION ────────────────────────────────────
def verify_slack(body, timestamp, signature):
    secret = os.environ.get("SLACK_SIGNING_SECRET", "")
    if not secret:
        print("No signing secret — skipping verification")
        return True
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False
        base = f"v0:{timestamp}:{body}"
        computed = "v0=" + hmac.new(
            secret.encode(), base.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(computed, signature)
    except Exception as e:
        print(f"Verification error: {e}")
        return True

# ── CHANNEL NAME CACHE ────────────────────────────────────
channel_cache = {}

def get_channel_name(channel_id):
    if channel_id in channel_cache:
        return channel_cache[channel_id]
    try:
        token = os.environ.get("SLACK_BOT_TOKEN", "")
        resp = requests.get(
            f"https://slack.com/api/conversations.info?channel={channel_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5
        )
        data = resp.json()
        if data.get("ok"):
            name = data["channel"].get("name", channel_id)
            channel_cache[channel_id] = name
            return name
    except Exception as e:
        print(f"Channel name error: {e}")
    return channel_id

# ── MAIN SLACK ENDPOINT ───────────────────────────────────
@app.route("/slack", methods=["POST"])
def slack_events():
    # Handle URL verification
    if request.content_type and "json" in request.content_type:
        data = request.get_json(silent=True)
        if data and data.get("type") == "url_verification":
            print("URL verification challenge received")
            return jsonify({"challenge": data["challenge"]})

    body_raw = request.get_data(as_text=True)
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not verify_slack(body_raw, timestamp, signature):
        print("Signature verification failed")
        return jsonify({"error": "Invalid signature"}), 403

    try:
        data = json.loads(body_raw)
    except:
        return jsonify({"ok": True})

    if data.get("type") == "url_verification":
        return jsonify({"challenge": data["challenge"]})

    event = data.get("event", {})
    print(f"Event received: {event.get('type')} | subtype: {event.get('subtype')} | bot: {event.get('bot_id')}")

    if (event.get("type") == "message"
            and not event.get("subtype")
            and not event.get("bot_id")):

        text = event.get("text", "").strip()
        channel_id = event.get("channel", "")

        print(f"Processing message: {text[:100]}")

        if not text or len(text) < 3:
            return jsonify({"ok": True})

        channel_name = get_channel_name(channel_id)

        # Check sensitive first — hard block, never forwarded
        if is_sensitive(text):
            msg = (
                f"🔒 <b>SENSITIVE MESSAGE</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"📁 Channel: #{channel_name}\n"
                f"⚠️ Contains sensitive content\n"
                f"📌 Check Slack directly\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"<i>— Zovix System</i>"
            )
            mgmt = os.environ.get("TELEGRAM_MANAGEMENT_GROUP", "")
            print(f"Sending sensitive alert to management: {mgmt}")
            send_telegram(mgmt, msg)
            return jsonify({"ok": True})

        # Route with Claude (or keyword fallback) — returns a LIST of tasks
        tasks = route_with_claude(text, channel_name)
        print(f"Tasks identified: {tasks}")

        editor_group = os.environ.get("TELEGRAM_EDITOR_GROUP", "")
        writer_group = os.environ.get("TELEGRAM_WRITER_GROUP", "")
        mgmt_group = os.environ.get("TELEGRAM_MANAGEMENT_GROUP", "")

        print(f"Groups — Editor: {editor_group} | Writer: {writer_group} | Mgmt: {mgmt_group}")

        # Send a SEPARATE Telegram message for EACH task to its own group
        for task in tasks:
            destination = task.get("destination", "MANAGEMENT")
            summary = task.get("summary", text[:200])

            # Any task Claude flags as SENSITIVE also gets hard-blocked
            if destination == "SENSITIVE":
                msg = (
                    f"🔒 <b>SENSITIVE MESSAGE</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"📁 Channel: #{channel_name}\n"
                    f"⚠️ Contains sensitive content\n"
                    f"📌 Check Slack directly\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"<i>— Zovix System</i>"
                )
                send_telegram(mgmt_group, msg)
                continue

            formatted = format_message(destination, channel_name, summary)

            if destination == "EDITOR":
                send_telegram(editor_group, formatted)
            elif destination == "WRITER":
                send_telegram(writer_group, formatted)
            else:
                send_telegram(mgmt_group, formatted)

    return jsonify({"ok": True})

# ── HEALTH CHECK ──────────────────────────────────────────
@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "running",
        "service": "Zovix Router",
        "env_check": {
            "slack_token": bool(os.environ.get("SLACK_BOT_TOKEN")),
            "slack_secret": bool(os.environ.get("SLACK_SIGNING_SECRET")),
            "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "telegram_token": bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
            "editor_group": bool(os.environ.get("TELEGRAM_EDITOR_GROUP")),
            "writer_group": bool(os.environ.get("TELEGRAM_WRITER_GROUP")),
            "mgmt_group": bool(os.environ.get("TELEGRAM_MANAGEMENT_GROUP")),
        }
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=False)
