"""
Run this to test Claude routing before deploying.
python test.py
"""
import json
import anthropic
import os

# Paste your key here just for testing
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_KEY_HERE")

client = anthropic.Anthropic(api_key=API_KEY)

TEST_MESSAGES = [
    {
        "text": "Hey can you edit the new supplement video, make it 60 seconds and add captions please",
        "channel": "peak-performance",
        "expected": "EDITOR"
    },
    {
        "text": "Can you write a new hook for the skincare ad? Something about clearing skin in 30 days",
        "channel": "monday-muse-skin",
        "expected": "WRITER"
    },
    {
        "text": "The invoice you sent last week was wrong, the amount should be $2500 not $2000",
        "channel": "grounding-of-sweden",
        "expected": "SENSITIVE"
    },
    {
        "text": "Can you write a script for the new VSL and also edit the existing UGC ad with new captions",
        "channel": "skinnify",
        "expected": "MANAGEMENT (mixed task)"
    },
    {
        "text": "Urgent! The ad account got flagged, one of the creatives violated policy. Need to fix ASAP",
        "channel": "oricle-hearing",
        "expected": "MANAGEMENT"
    },
    {
        "text": "Please add subtitles to all 4 videos we sent and export in 9:16 format",
        "channel": "better-root",
        "expected": "EDITOR"
    },
]

def route_test(message_text, channel_name):
    system_prompt = """You are a smart message router for Zovix, a video ads agency.

Your job is to read a Slack message from a client and:
1. Decide if it contains sensitive information
2. If it is a task, decide which team should handle it
3. Extract ONLY the task-related content

SENSITIVE: payment, invoices, pricing, costs, rates, contracts, salary, bank details, anything with currency

EDITOR tasks: video editing, captions, subtitles, cutting, music, sound design, format changes

WRITER tasks: script writing, hook writing, ad copy, content strategy, writing tasks

MANAGEMENT: general questions, approvals, complaints, anything sensitive, anything unclear

Respond ONLY with valid JSON:
{
  "destination": "EDITOR" | "WRITER" | "MANAGEMENT" | "SENSITIVE",
  "task_summary": "Clean summary or null if sensitive",
  "priority": "URGENT" | "NORMAL" | "LOW",
  "deadline": "deadline or null",
  "sensitive_detected": true | false,
  "reason": "one line explanation"
}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=system_prompt,
        messages=[{"role": "user", "content": f"Channel: #{channel_name}\nMessage: {message_text}"}]
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())

print("=" * 50)
print("ZOVIX ROUTER — CLAUDE ROUTING TEST")
print("=" * 50)

for test in TEST_MESSAGES:
    print(f"\n📨 MESSAGE: {test['text'][:60]}...")
    print(f"📁 CHANNEL: #{test['channel']}")
    print(f"✅ EXPECTED: {test['expected']}")

    result = route_test(test['text'], test['channel'])

    dest = result.get('destination', '?')
    summary = result.get('task_summary', 'N/A')
    priority = result.get('priority', '?')
    reason = result.get('reason', '?')

    print(f"🤖 ROUTED TO: {dest}")
    print(f"📝 SUMMARY: {summary}")
    print(f"⚡ PRIORITY: {priority}")
    print(f"💭 REASON: {reason}")

    match = "✅ CORRECT" if test['expected'].startswith(dest) else "⚠️ CHECK THIS"
    print(f"RESULT: {match}")
    print("-" * 50)

print("\n✅ Test complete")
