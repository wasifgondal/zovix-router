# ZOVIX SLACK → TELEGRAM ROUTER
## Complete Setup Guide

---

## WHAT THIS DOES

Client messages on Slack → Claude reads & filters → Correct Telegram group

- EDITOR tasks → Zovix Editors Telegram group
- WRITER tasks → Zovix Writers Telegram group  
- SENSITIVE/MANAGEMENT → Zovix Management Telegram group
- Payment/invoice messages → BLOCKED from employees

---

## STEP 1 — CREATE TELEGRAM BOT (5 minutes)

1. Open Telegram → search @BotFather
2. Send: /newbot
3. Name: Zovix Router
4. Username: zovix_router_bot (or similar)
5. Copy the TOKEN it gives you

### Create 3 Telegram Groups:
- "Zovix Editors" → add the bot + all editors
- "Zovix Writers" → add the bot + all writers
- "Zovix Management" → add the bot + you only

### Get Group Chat IDs:
1. Add @userinfobot to each group
2. Send any message in the group
3. It shows the Chat ID (negative number like -1001234567890)
4. Copy all 3 IDs
5. Remove @userinfobot after

---

## STEP 2 — CREATE SLACK APP (10 minutes)

1. Go to: api.slack.com/apps
2. Click "Create New App" → "From scratch"
3. Name: Zovix Router
4. Select your workspace → Create App

### Add Bot Permissions:
1. Left menu → "OAuth & Permissions"
2. Scroll to "Bot Token Scopes"
3. Add these scopes:
   - channels:history
   - channels:read
   - chat:write
   - groups:history (for private channels)
4. Click "Install to Workspace"
5. Copy the "Bot OAuth Token" (starts with xoxb-)

### Get Signing Secret:
1. Left menu → "Basic Information"
2. Scroll to "App Credentials"
3. Copy "Signing Secret"

### Add Bot to Channels:
In Slack, go to each client channel and type:
/invite @Zovix Router

---

## STEP 3 — GET CLAUDE API KEY (2 minutes)

1. Go to: console.anthropic.com
2. Sign up / log in
3. Click "API Keys" → "Create Key"
4. Copy the key (starts with sk-ant-)
5. You get $5 free credit (~5,000+ messages)

---

## STEP 4 — DEPLOY TO RAILWAY (10 minutes)

1. Go to: railway.app
2. Sign up with GitHub
3. Click "New Project" → "Deploy from GitHub repo"
4. Upload this code to a GitHub repo first:
   - Create repo at github.com
   - Upload all files from this folder
5. Select the repo in Railway
6. Railway auto-detects Python and deploys

### Add Environment Variables in Railway:
Click your project → Variables → Add these:

```
SLACK_BOT_TOKEN=xoxb-your-token
SLACK_SIGNING_SECRET=your-secret
ANTHROPIC_API_KEY=sk-ant-your-key
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_EDITOR_GROUP=-100xxxxxxxxx
TELEGRAM_WRITER_GROUP=-100xxxxxxxxx
TELEGRAM_MANAGEMENT_GROUP=-100xxxxxxxxx
```

7. After deploy, Railway gives you a URL like:
   https://zovix-router-production.up.railway.app

---

## STEP 5 — CONNECT SLACK TO YOUR APP (5 minutes)

1. Go back to api.slack.com/apps → Your app
2. Left menu → "Event Subscriptions"
3. Toggle ON
4. Request URL: https://YOUR-RAILWAY-URL/slack
5. Slack will verify it (your app must be running)
6. Under "Subscribe to Bot Events" add:
   - message.channels
   - message.groups (for private channels)
7. Save Changes
8. Reinstall the app if prompted

---

## STEP 6 — TEST IT

1. Run the local test first:
   ```
   pip install anthropic
   ANTHROPIC_API_KEY=your-key python test.py
   ```

2. Then test live:
   - Go to a Slack client channel
   - Make sure the bot is in the channel
   - Send: "Can you edit the video and add captions"
   - Check Zovix Editors Telegram group
   - Should receive a formatted task message

---

## WHAT EACH MESSAGE LOOKS LIKE ON TELEGRAM

### Editor Task:
```
🟡 ✂️ EDITOR TASK
━━━━━━━━━━━━━━━━━━━
📁 Client: #peak-performance
📝 Task: Edit supplement video to 60 seconds and add captions
⏰ Deadline: Friday
━━━━━━━━━━━━━━━━━━━
— Zovix System
```

### Writer Task:
```
🟡 ✍️ WRITER TASK
━━━━━━━━━━━━━━━━━━━
📁 Client: #monday-muse-skin
📝 Task: Write new hook for skincare ad about clearing skin in 30 days
━━━━━━━━━━━━━━━━━━━
— Zovix System
```

### Sensitive (Management only):
```
🔒 SENSITIVE MESSAGE BLOCKED
━━━━━━━━━━━━━━━━━━━
📁 Channel: #grounding-of-sweden
⚠️ Message contained sensitive keywords
📌 Check Slack for the full message
━━━━━━━━━━━━━━━━━━━
— Zovix System
```

---

## TROUBLESHOOTING

### Bot not receiving messages:
→ Make sure bot is invited to the channel (/invite @Zovix Router)
→ Check Event Subscriptions are saved in Slack

### Telegram not receiving messages:
→ Make sure bot is added to all 3 groups
→ Check group Chat IDs are correct (must be negative)
→ Try sending /start to the bot first

### Wrong routing:
→ Claude makes the decision - edit SENSITIVE_KEYWORDS in app.py
→ Add more keywords to the sensitive list if needed

---

## COST

- Railway: Free tier (500 hours/month)
- Claude API: $5 free credit (~5,000 messages)
- Telegram: Free forever
- Total: $0 to start
