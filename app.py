import os
import hmac
import hashlib
import time
import json
import requests
from flask import Flask, request, jsonify
import anthropic

app = Flask(__name__)

# ── CONFIG ──────────────────────────────────────────────
SLACK_BOT_TOKEN      = os.environ.get("SLACK_BOT_TOKEN")       # xoxb-...
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET")  # from Basic Info
ANTHROPIC_API_KEY    = os.environ.get("ANTHROPIC_API_KEY")     # sk-ant-...
TELEGRAM_BOT_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN")    # from BotFather

# Telegram Group Chat IDs (negative numbers)
TELEGRAM_EDITOR_GROUP     = os.environ.get("TELEGRAM_EDITOR_GROUP")     # -100...
TELEGRAM_WRITER_GROUP     = os.environ.get("TELEGRAM_WRITER_GROUP")     # -100...
TELEGRAM_MANAGEMENT_GROUP = os.environ.get("TELEGRAM_MANAGEMENT_GROUP") # -100...

# ── CLIENTS ─────────────────────────────────────────────
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── SENSITIVE KEYWORDS (hard block — never forward) ─────
SENSITIVE_KEYWORDS = [
    "invoice", "payment", "paid", "pay", "bank", "transfer",
    "contract", "price", "pricing", "rate", "rates", "cost",
    "budget", "discount", "refund", "charge", "billing",
    "dollar", "pound", "usd", "gbp", "pkr", "salary",
    "deposit", "wire", "paypal", "wise", "stripe",
    "confidential", "private", "personal",
]

def is_definitely_sensitive(text):
    """Hard keyword check before even calling Claude."""
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in SENSITIVE_KEYWORDS)

# ── SLACK VERIFICATION ───────────────────────────────────
def verify_slack_signature(request_body, timestamp, signature):
    """Verify the request actually comes from Slack."""
    if abs(time.time() - int(timestamp)) > 60 * 5:
        return False
    sig_basestring = f"v0:{timestamp}:{request_body}"
    computed = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, signature)

# ── TELEGRAM SENDER ──────────────────────────────────────
def send_telegram(chat_id, message):
    """Send a message to a Telegram group."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Telegram send error: {e}")
        return None

# ── CLAUDE ROUTER ────────────────────────────────────────
def route_with_claude(message_text, channel_name):
    """
    Ask Claude to:
    1. Classify the message
    2. Extract the task cleanly
    3. Decide which team gets it
    """
    system_prompt = """You are a smart message router for Zovix, a video ads agency.

Your job is to read a Slack message from a client and:
1. Decide if it contains sensitive information
2. If it is a task, decide which team should handle it
3. Extract ONLY the task-related content — strip all sensitive info

SENSITIVE (never forward, mark as MANAGEMENT):
- Payment, invoices, pricing, costs, rates, contracts
- Salary, budget, billing, bank details
- Personal opinions about team members
- Confidential business information
- Anything with $ £ € or currency symbols in a payment context

EDITOR tasks (forward to EDITOR group):
- Video editing requests
- Adding captions, subtitles
- Cutting footage, trimming videos
- Adding music, sound design
- Format changes (9:16, 1:1, 4:5)
- Any video production task

WRITER tasks (forward to WRITER group):
- Script writing
- Hook writing
- Ad copy
- Caption writing for posts
- Content strategy
- Any writing or scripting task

MANAGEMENT (forward to management group only):
- General questions not specific to a task
- Approvals that need owner decision
- Complaints or issues
- Anything sensitive
- Anything unclear

Respond ONLY with valid JSON in this exact format:
{
  "destination": "EDITOR" | "WRITER" | "MANAGEMENT" | "SENSITIVE",
  "task_summary": "Clean 1-2 sentence summary of the task only",
  "priority": "URGENT" | "NORMAL" | "LOW",
  "deadline": "extracted deadline or null",
  "sensitive_detected": true | false,
  "reason": "one line explaining your routing decision"
}

If SENSITIVE, set task_summary to null."""

    user_prompt = f"""Client channel: #{channel_name}

Client message:
\"\"\"{message_text}\"\"\"""

Analyze this message and respond with JSON only."""

    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
        raw = response.content[0].text.strip()
        # Strip markdown code blocks if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        print(f"Claude routing error: {e}")
        # Default to management on any error
        return {
            "destination": "MANAGEMENT",
            "task_summary": message_text[:200],
            "priority": "NORMAL",
            "deadline": None,
            "sensitive_detected": False,
            "reason": "Routing error — defaulted to management"
        }

# ── FORMAT MESSAGE FOR TELEGRAM ──────────────────────────
def format_telegram_message(routing, channel_name, destination):
    """Format a clean task card for Telegram."""

    priority_emoji = {
        "URGENT": "🔴",
        "NORMAL": "🟡",
        "LOW":    "🟢"
    }.get(routing.get("priority", "NORMAL"), "🟡")

    team_label = {
        "EDITOR":     "✂️ EDITOR TASK",
        "WRITER":     "✍️ WRITER TASK",
        "MANAGEMENT": "📋 MANAGEMENT",
    }.get(destination, "📋 NEW TASK")

    deadline_line = ""
    if routing.get("deadline"):
        deadline_line = f"\n⏰ <b>Deadline:</b> {routing['deadline']}"

    message = (
        f"{priority_emoji} <b>{team_label}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📁 <b>Client:</b> #{channel_name}\n"
        f"📝 <b>Task:</b> {routing.get('task_summary', 'See Slack for details')}"
        f"{deadline_line}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"<i>— Zovix System</i>"
    )
    return message

# ── MAIN SLACK ENDPOINT ──────────────────────────────────
@app.route("/slack", methods=["POST"])
def slack_events():
    # Handle URL verification challenge from Slack
    if request.content_type == "application/json":
        data = request.get_json()
        if data and data.get("type") == "url_verification":
            return jsonify({"challenge": data["challenge"]})

    # Verify Slack signature
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    body_raw   = request.get_data(as_text=True)

    if not verify_slack_signature(body_raw, timestamp, signature):
        return jsonify({"error": "Invalid signature"}), 403

    data = request.get_json()
    if not data:
        return jsonify({"ok": True})

    # URL verification (form-encoded sometimes)
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data["challenge"]})

    # Process message events
    event = data.get("event", {})

    # Only process actual user messages (ignore bot messages)
    if (event.get("type") == "message"
            and not event.get("subtype")
            and not event.get("bot_id")):

        message_text = event.get("text", "").strip()
        channel_id   = event.get("channel", "")

        if not message_text or len(message_text) < 5:
            return jsonify({"ok": True})

        # Get channel name from Slack API
        channel_name = get_channel_name(channel_id)

        # Hard keyword check first (saves API calls)
        if is_definitely_sensitive(message_text):
            notify = (
                f"🔒 <b>SENSITIVE MESSAGE BLOCKED</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"📁 <b>Channel:</b> #{channel_name}\n"
                f"⚠️ Message contained sensitive keywords\n"
                f"📌 Check Slack for the full message\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"<i>— Zovix System</i>"
            )
            send_telegram(TELEGRAM_MANAGEMENT_GROUP, notify)
            return jsonify({"ok": True})

        # Use Claude for intelligent routing
        routing = route_with_claude(message_text, channel_name)
        destination = routing.get("destination", "MANAGEMENT")

        # If sensitive detected by Claude
        if destination == "SENSITIVE" or routing.get("sensitive_detected"):
            notify = (
                f"🔒 <b>SENSITIVE MESSAGE DETECTED</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"📁 <b>Channel:</b> #{channel_name}\n"
                f"⚠️ Claude detected sensitive content\n"
                f"📌 Check Slack for the full message\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"<i>— Zovix System</i>"
            )
            send_telegram(TELEGRAM_MANAGEMENT_GROUP, notify)
            return jsonify({"ok": True})

        # Format and send to correct group
        formatted = format_telegram_message(routing, channel_name, destination)

        if destination == "EDITOR":
            send_telegram(TELEGRAM_EDITOR_GROUP, formatted)
        elif destination == "WRITER":
            send_telegram(TELEGRAM_WRITER_GROUP, formatted)
        else:
            # MANAGEMENT or anything else
            send_telegram(TELEGRAM_MANAGEMENT_GROUP, formatted)

    return jsonify({"ok": True})

# ── HEALTH CHECK ─────────────────────────────────────────
@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "running",
        "service": "Zovix Slack → Telegram Router",
        "version": "1.0"
    })

# ── CHANNEL NAME CACHE ────────────────────────────────────
channel_cache = {}

def get_channel_name(channel_id):
    """Get channel name from Slack API with caching."""
    if channel_id in channel_cache:
        return channel_cache[channel_id]
    try:
        headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
        resp = requests.get(
            f"https://slack.com/api/conversations.info?channel={channel_id}",
            headers=headers,
            timeout=5
        )
        data = resp.json()
        if data.get("ok"):
            name = data["channel"].get("name", channel_id)
            channel_cache[channel_id] = name
            return name
    except Exception as e:
        print(f"Channel name fetch error: {e}")
    return channel_id

# ── RUN ───────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=False)
