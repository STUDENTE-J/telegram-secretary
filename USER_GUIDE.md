# 📖 Telegram Secretary Bot - User Guide

**Version:** 1.0 (January 2026)
**Purpose:** Complete guide to using your personal Telegram secretary

---

## 🎯 What Does This Bot Do?

The Telegram Secretary Bot is your personal assistant that:
- **Monitors** all your Telegram messages (private chats, groups, channels)
- **Scores** each message by importance (0-10 scale)
- **Alerts** you immediately for high-priority messages
- **Summarizes** the rest in periodic digests (every 4 hours by default)
- **Learns** from your classifications to improve over time

**Think of it as:** An intelligent inbox that ensures you never miss what matters while reducing notification fatigue.

---

## 🚀 Getting Started

### First Time Setup

After the bot is deployed and running, you'll receive a welcome message. Here's what to do:

1. **Set Your Profile** (Recommended)
   ```
   /profile
   ```
   Tell the bot about your work, interests, and what's important to you. This helps with AI-powered priority scoring.

   **Example:**
   > "I'm a software engineer working on web apps. Important topics: work deadlines, bug reports, client requests, team meetings. Personal interests: family messages, close friends. Ignore: crypto spam, promotional messages."

2. **Configure Settings** (Optional)
   ```
   /config
   ```
   Adjust:
   - Warning threshold (default: 8/10 - only very important messages alert you)
   - Muted chat filtering (on/off)
   - Large group filtering (on/off)

3. **Start Receiving Messages**

   That's it! The bot is now working silently in the background.

---

## 📱 Bot Commands

### Essential Commands

| Command | What It Does | When to Use |
|---------|-------------|-------------|
| `/summary` | Get summary of recent messages NOW | When you want to catch up immediately |
| `/stats` | View message statistics | Check how many messages you're receiving |
| `/settings` | See current configuration | Review your settings |

### Configuration Commands

| Command | What It Does | When to Use |
|---------|-------------|-------------|
| `/config` | Interactive settings menu | Adjust warning threshold, toggle filters |
| `/profile` | Set your context for AI scoring | Tell the bot what matters to you |

### Monitoring Commands

| Command | What It Does | When to Use |
|---------|-------------|-------------|
| `/health` | Check if bot is running properly | Troubleshooting or status check |
| `/start` | Show welcome message | First time or to see overview |

---

## 🎛️ Interactive Features

### Priority Classification Buttons

Every message in summaries and warnings has buttons:

**🔴 High** - Important messages you don't want to miss
**🟡 Medium** - Moderately important, worth reviewing
**🟢 Low** - Not important, can be ignored

**Why classify?** The bot collects this data for future machine learning improvements. Your classifications help it learn what matters to you.

### Mute/Unmute Chats

#### Muting a Chat

When you see a message you want to ignore:

1. Click **🚫 Ignore Chat** button
2. Select duration:
   - **1 hour** - Temporary mute (meeting, focus time)
   - **8 hours** - Workday mute
   - **1 day** - Daily mute (noisy group)
   - **1 week** - Weekly mute (event group)
   - **Forever** - Permanent mute (spam, abandoned groups)
3. Done! Messages from this chat are now filtered out

**What happens:**
- Existing messages in database stay (for stats)
- Future messages are automatically ignored
- Mute syncs with Telegram's native mute settings
- Takes ~30 seconds to fully propagate

#### Unmuting a Chat

When you see a message from an already-muted chat:

1. Click **🔊 Unmute Chat** button
2. Confirmed! Chat is unmuted

**Smart Detection:** The bot automatically shows the right button:
- Muted chats → Shows "🔊 Unmute Chat"
- Unmuted chats → Shows "🚫 Ignore Chat"

---

## 📊 Understanding Message Scores

Every message gets a score from 0-10 based on:

### AI Scoring (If Ollama Enabled)

The bot analyzes:
- **Content urgency** - Questions, requests, time-sensitive info
- **Relevance to your profile** - Related to your work/interests?
- **Sender importance** - From high-priority contacts?
- **Context** - Thread importance, conversation flow

**Profile-Based Filtering:**
- Messages unrelated to your profile: MAX score 3/10
- On-topic messages: Scored 0-10 based on urgency

### Rule-Based Scoring (Default/Fallback)

If AI is unavailable, uses simple rules:

| Criteria | Points | Example |
|----------|--------|---------|
| Contains @mention | +3 | "Hey @you, check this out" |
| Is a question | +2 | "Can you help with this?" |
| Long message (>100 chars) | +1 | Detailed explanations |
| High-priority sender | +2 | From your important contacts list |

**Score Interpretation:**
- **8-10** = 🚨 Real-time warning (immediate alert)
- **5-7** = ⚠️ High priority (top of summary)
- **3-4** = 🔵 Medium priority (middle of summary)
- **0-2** = ⚪ Low priority (bottom of summary)

---

## 📝 Periodic Summaries

### What Are Summaries?

Every 4 hours (configurable), the bot sends you a digest of messages scored above your minimum threshold (default: 1).

**Example Summary:**

```
📊 Message Summary (Last 4 hours)

Showing top 15 messages (filtered 143 muted/large groups)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1️⃣ Priority: 🔴 9/10 | 2 hours ago
From: John Smith
Chat: Work Team
Topic: urgent deadline
Message: "@you We need the report by 5 PM today, client is waiting!"

[🔴 High] [🟡 Medium] [🟢 Low] [🚫 Ignore Chat]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

2️⃣ Priority: ⚠️ 7/10 | 3 hours ago
From: Sarah
Chat: Private
Topic: project question
Message: "Hey! Quick question about the API integration, can you help?"

[🔴 High] [🟡 Medium] [🟢 Low] [🚫 Ignore Chat]

...
```

### Summary Features

- **Smart Ordering** - Highest priority first
- **Context** - Shows sender, chat, time, topic
- **Interactive** - Classify each message or mute chats
- **Filtered Count** - See how many messages were auto-filtered
- **Compact** - Only shows top N messages (default: 15)

### Customizing Summaries

Use `/config` to adjust:

**Summary Interval**
- Default: 4 hours
- Range: 1-24 hours
- Change via environment variable: `SUMMARY_INTERVAL_HOURS`

**Messages Per Summary**
- Default: 15 messages
- Shows top N by priority
- Change via environment variable: `MAX_MESSAGES_PER_SUMMARY`

**Minimum Score**
- Default: 1 (show almost everything)
- Range: 0-10
- Increase to see only higher priority messages
- Change via `/config` command

---

## 🚨 Real-Time Warnings

### What Are Warnings?

When a message scores ≥ 8/10, you get an **immediate alert**.

**Example Warning:**

```
🚨 HIGH PRIORITY MESSAGE

From: Boss
Chat: Private
Priority: 🔴 9/10
Topic: urgent deadline

"@you Client called - they need the demo deployed NOW. Can you push it live?"

Sent: Just now

[🔴 High] [🟡 Medium] [🟢 Low] [🚫 Ignore Chat]
```

### Preventing Warning Spam

**Default threshold:** 8/10 (strict - only truly urgent messages)

If you're getting too many warnings:
1. Use `/config`
2. Increase warning threshold to 9/10 (very strict)
3. Or disable by setting to 11/10 (only summaries)

**Filtering also helps:**
- Muted chats never trigger warnings
- Large groups can be auto-filtered
- Adjust via `/config`

---

## 🔇 Smart Filtering

The bot automatically filters messages to reduce noise:

### Muted Chats Filter

**What it does:**
- Checks Telegram's native mute settings
- Filters any chat you've muted in Telegram
- Applies to both bot mutes and manual Telegram mutes

**How to toggle:**
```
/config → Muted Chat Filtering → On/Off
```

**Default:** ON (recommended)

### Large Groups Filter

**What it does:**
- Filters groups with more than N members (default: 20)
- Useful for massive community groups that are too noisy

**How to configure:**
```
/config → Large Group Filtering → On/Off
/config → Max Group Size → Set threshold (10-500)
```

**Default:** OFF (you can enable it)

**Why filter large groups?**
- Reduces message volume by 20-35%
- Focuses on smaller, more relevant conversations
- You can always check Telegram directly for these groups

---

## 📈 Statistics

Use `/stats` to see:

**Message Counts:**
- Total messages captured
- Messages in last 24 hours
- Messages by chat type (private, groups, channels)

**Label Distribution:**
- High priority labels: X messages
- Medium priority labels: Y messages
- Low priority labels: Z messages
- Unlabeled: N messages

**Use cases:**
- Track communication patterns
- See if filtering is working
- Understand message volume

---

## 💡 Tips & Best Practices

### Getting the Most Out of Your Bot

1. **Set Your Profile Early**
   - More accurate AI scoring
   - Better relevance filtering
   - Update it when your focus changes

2. **Classify Messages Regularly**
   - Future ML will learn from your classifications
   - Takes 1 second per message
   - Improves long-term accuracy

3. **Use Mute Liberally**
   - Better than ignoring in Telegram
   - Bot respects your mutes
   - Easy to unmute later

4. **Adjust Warning Threshold**
   - Start at 8/10 (default)
   - Too many warnings? Increase to 9/10
   - Too few? Lower to 7/10

5. **Check Summaries Regularly**
   - Don't let them pile up
   - Review at natural breaks (lunch, end of day)
   - Use `/summary` to get on-demand

### Common Workflows

**📱 Daily Usage:**
- Morning: Check overnight summary
- Throughout day: Respond to real-time warnings
- Evening: Review day summary, classify important messages

**🎯 Focus Time:**
- Mute noisy groups for 8 hours
- Only respond to warnings (8+ priority)
- Catch up with summary later

**🌴 Vacation Mode:**
- Increase warning threshold to 9 or 10
- Mute all work groups for 1 week
- Let summaries accumulate, review when back

---

## 🔧 Troubleshooting

### "Not receiving summaries"

**Check:**
1. Is bot running? Use `/health`
2. Are all chats muted? Check `/stats`
3. Is minimum score too high? Use `/config` to lower it
4. Wait for next interval (max 4 hours)
5. Force immediate summary with `/summary`

### "Too many warnings"

**Solution:**
1. Use `/config`
2. Increase warning threshold to 9/10
3. Mute noisy groups
4. Enable large group filtering

### "Bot not catching important messages"

**Check:**
1. Is sender in high-priority users? (Future feature)
2. Does message have @mention or question?
3. Set your `/profile` for better AI scoring
4. Lower minimum score in `/config`

### "Mute not working"

**Common causes:**
1. Takes ~30 seconds to propagate
2. Wait for next message from that chat
3. Check if large group filtering is interfering
4. Verify with `/stats` that messages stopped

### "Bot is slow to start"

**Expected:**
- Startup: ~3-5 seconds
- Cache population: Additional 30-45 seconds
- During cache population, filtering may not be active yet

If startup takes longer than 1 minute, check Railway logs.

---

## 🔐 Privacy & Security

### What Data is Stored?

**In Database:**
- Message text, sender, chat name, timestamp
- Priority scores and classifications
- Your profile context
- Settings and preferences

**Not Stored:**
- Media files (photos, videos, documents)
- Voice messages or calls
- Location data
- Payment information

### Where is Data Stored?

**Local Deployment:**
- SQLite database on your machine
- Full privacy - never leaves your device

**Railway Deployment:**
- PostgreSQL database in Railway's cloud
- Encrypted at rest
- GDPR compliant
- SOC 2 Type II certified

### AI Privacy

**Ollama (Optional):**
- Runs locally only (localhost)
- Never sends data externally
- Disabled by default on Railway
- Bot works perfectly without it

**No External AI Calls:**
- If Ollama is unavailable, uses rule-based scoring
- No OpenAI, Claude, or other cloud AI services
- Your messages stay private

---

## 🎓 Advanced Features

### High-Priority Users (Coming Soon)

Mark specific contacts as high priority:
- Messages from them always get +2 score
- More likely to trigger warnings
- Never filtered out

### Quiet Hours (Schema Ready)

Schedule no-disturb times:
- No summaries during sleep hours
- Warnings still come through
- Configuration saved in database

### Machine Learning (Future)

The bot collects labeled data for:
- Training personalized ML models
- Learning your preferences over time
- Replacing rule-based scoring

---

## 📞 Support

### Getting Help

**Check Documentation:**
- This user guide
- [README.md](README.md) for setup
- Railway logs for errors

**Common Issues:**
- Most problems resolve within 30-60 seconds (cache refresh)
- Use `/health` to check status
- Restart bot if needed (Railway: automatic)

**Report Bugs:**
- Check GitHub issues
- Provide: command used, expected behavior, actual behavior
- Include relevant log snippets (sanitize sensitive info)

---

## 🚀 Quick Reference

### One-Line Command Guide

```bash
/start      # Welcome message
/summary    # Get summary now
/stats      # View statistics
/settings   # See configuration
/config     # Change settings
/profile    # Set your context
/health     # System status check
```

### Button Quick Guide

```
🔴 High     → Mark as high priority
🟡 Medium   → Mark as medium priority
🟢 Low      → Mark as low priority
🚫 Ignore   → Mute chat (select duration)
🔊 Unmute   → Unmute chat
```

### Score Reference

```
0-2  ⚪ Low       → Background noise
3-4  🔵 Medium    → Worth reviewing
5-7  ⚠️ High      → Important
8-10 🚨 Critical  → Immediate alert
```

---

**Last Updated:** January 29, 2026
**Bot Version:** 1.0 (Production)
**Questions?** Check `/help` in the bot or consult [README.md](README.md)

---

## 📝 Changelog

### Version 1.0 (January 2026)
- Initial release
- Native Telegram mute/unmute
- AI-powered + rule-based scoring
- Interactive classification
- Smart filtering
- 3-second startup time
- Railway deployment ready
