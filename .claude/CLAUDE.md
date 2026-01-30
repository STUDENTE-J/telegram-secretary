# Telegram Secretary Bot

## Project Overview

The Telegram Secretary Bot is an intelligent message prioritization and summarization system that monitors all incoming Telegram messages, scores them by importance, and delivers periodic summaries to help users stay on top of their communications without constant interruptions.

### Core Value Proposition
- **Never miss important messages** - Real-time alerts for high-priority communications
- **Reduce notification fatigue** - Batched summaries instead of constant interruptions
- **Smart prioritization** - AI-powered scoring based on mentions, questions, and sender importance
- **Privacy-first** - All data stays local or in your controlled database
- **Interactive learning** - Classify messages to improve future prioritization

---

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                    Telegram Secretary Bot                    │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Userbot    │  │     Bot      │  │  Scheduler   │      │
│  │  (Telethon)  │  │ (Bot API)    │  │ (APScheduler)│      │
│  │              │  │              │  │              │      │
│  │ Captures all │  │ Sends        │  │ Generates    │      │
│  │ messages     │  │ summaries &  │  │ periodic     │      │
│  │ from chats   │  │ handles      │  │ summaries    │      │
│  │              │  │ commands     │  │ every N hrs  │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                  │                  │              │
│         └──────────────────┼──────────────────┘              │
│                            │                                 │
│                    ┌───────▼────────┐                        │
│                    │   Database     │                        │
│                    │  (SQLAlchemy)  │                        │
│                    │                │                        │
│                    │ SQLite or      │                        │
│                    │ PostgreSQL     │                        │
│                    └────────────────┘                        │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Message Capture** | Telethon 1.34.0 | Userbot for reading all messages |
| **Bot Interface** | python-telegram-bot 21.6 | Official Bot API for sending messages |
| **Database** | SQLAlchemy 2.0.23 | ORM with async support |
| **Storage** | SQLite / PostgreSQL | Local or cloud database |
| **Scheduling** | APScheduler 3.10.4 | Periodic summary generation |
| **AI (Optional)** | Ollama (llama3.2:3b) | Local LLM for topic summaries |
| **Config** | python-dotenv 1.0.0 | Environment variable management |
| **Runtime** | Python 3.11+ | Async/await support |

---

## Project Structure

```
telegram-secretary/
├── main.py                      # Entry point & orchestration
├── config.py                    # Configuration management
├── database.py                  # Database connection & sessions
├── models.py                    # SQLAlchemy ORM models
├── userbot.py                   # Message capture (Telethon)
├── bot.py                       # Commands & interactions (Bot API)
├── scheduler.py                 # Periodic summary generation
├── utils.py                     # Helper functions (scoring, formatting)
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment variables template
├── Procfile                     # Railway deployment config
├── railway.json                 # Railway service schema
├── init_db.sql                  # Database schema reference
├── generate_session_data.py     # Railway deployment helper
└── docs/                        # Documentation files
    ├── README.md
    ├── SETUP_GUIDE.md
    ├── ARCHITECTURE.md
    ├── SECURITY_AUDIT.md
    └── RAILWAY_DEPLOYMENT.md
```

---

## Key Features

### 1. Message Capture
- Monitors ALL incoming Telegram messages (private chats, groups, channels)
- Extracts metadata: sender, chat, timestamp, text
- Filters out self-messages and bot messages
- Non-invasive: read-only access

### 2. Smart Prioritization System

**Scoring Algorithm (0-8 points):**
- `@mention` of your username: **+3 points**
- Question detected (ends with `?` or starts with question words): **+2 points**
- Message length > 100 characters: **+1 point**
- Sender is in high-priority users list: **+2 points**

**Example Scores:**
- "Hey @you, can you help?" → 5 points (mention + question)
- "Quick question about the project..." → 3 points (question + length)
- "@you check this out" → 3 points (mention only)

### 3. Real-Time Priority Warnings
- Immediate alert for messages with score ≥ 5 (configurable)
- Prevents missing critical communications
- Includes inline classification buttons
- Prevents duplicate warnings

### 4. Periodic Summaries
- Scheduled delivery every N hours (default: 4)
- Shows top N messages (default: 15) sorted by priority
- Beautiful formatting with chat context
- Interactive classification buttons on each message
- Smart labeling: High (🔴), Medium (🟡), Low (🟢)

### 5. Interactive Message Classification
- User can label messages as High/Medium/Low priority
- Data stored for future ML improvements
- Labels stored with timestamp
- Enables personalized learning over time

### 6. AI Topic Summarization (Optional)
- Local Ollama LLM generates 3-word topic summaries
- Privacy-preserving: runs on localhost only
- Graceful fallback if Ollama unavailable
- Model: llama3.2:3b (fast, lightweight)

### 7. Bot Commands
- `/start` - Welcome message & feature overview
- `/summary` - Generate and send summary immediately
- `/stats` - View message statistics and label breakdown
- `/settings` - Display current configuration

### 8. Statistics & Analytics
- Total messages captured
- Messages in last 24 hours
- Labeled vs unlabeled counts
- Label distribution breakdown

---

## Database Schema

### Table: `messages`
Primary storage for all captured messages.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INT | Primary key |
| `telegram_message_id` | BIGINT | Original Telegram message ID |
| `chat_id` | BIGINT | Chat identifier |
| `chat_title` | VARCHAR | Group/channel/user name |
| `chat_type` | VARCHAR | private/group/supergroup/channel |
| `user_id` | BIGINT | Sender user ID |
| `user_name` | VARCHAR | Sender display name |
| `message_text` | TEXT | Full message content |
| `timestamp` | DATETIME | Message timestamp |
| `has_mention` | BOOLEAN | Contains @mention |
| `is_question` | BOOLEAN | Detected as question |
| `message_length` | INT | Character count |
| `topic_summary` | VARCHAR | AI-generated 3-word summary |
| `priority_score` | INT | Calculated score (0-8) |
| `label` | VARCHAR | User classification (high/medium/low) |
| `labeled_at` | DATETIME | When user labeled |
| `included_in_summary` | BOOLEAN | Included in a summary |
| `summary_sent_at` | DATETIME | When summary was sent |
| `warning_sent` | BOOLEAN | Real-time warning sent |
| `warning_sent_at` | DATETIME | When warning sent |
| `created_at` | DATETIME | Record creation time |

**Indexes:**
- `idx_messages_label` - Fast filtering by label
- `idx_messages_timestamp` - Chronological queries
- `idx_messages_chat_id` - Per-chat filtering
- `idx_messages_user_id` - Per-user filtering
- `idx_messages_included_summary` - Summary queries
- `idx_messages_unlabeled_recent` - Composite for unlabeled recent messages

### Table: `user_preferences`
User-specific configuration settings.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INT | Primary key |
| `user_id` | BIGINT | User identifier (unique) |
| `summary_interval_hours` | INT | Hours between summaries |
| `max_messages_per_summary` | INT | Max messages per summary |
| `excluded_chat_ids_json` | TEXT | JSON array of excluded chats |
| `quiet_hours_start` | TIME | Do not disturb start time |
| `quiet_hours_end` | TIME | Do not disturb end time |
| `created_at` | DATETIME | Record creation |
| `updated_at` | DATETIME | Last update |

### Table: `high_priority_users`
Whitelist of important contacts.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INT | Primary key |
| `user_id` | BIGINT | User identifier (unique) |
| `user_name` | VARCHAR | Display name |
| `notes` | TEXT | Why this user is important |
| `created_at` | DATETIME | Record creation |

**Index:** `idx_high_priority_user_id` - Fast lookup

---

## Configuration

### Environment Variables

Create a `.env` file in the project root:

```bash
# Telegram API Credentials (from https://my.telegram.org)
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
TELEGRAM_PHONE=+1234567890
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
CLIENT_USER_ID=123456789

# Database
DATABASE_URL=sqlite:///secretary.db  # or postgresql://...

# Scheduler Settings (Optional)
SUMMARY_INTERVAL_HOURS=4
MAX_MESSAGES_PER_SUMMARY=15
MIN_PRIORITY_SCORE=1
WARNING_THRESHOLD_SCORE=5

# Timezone (Optional)
TIMEZONE=America/Sao_Paulo

# Ollama (Optional)
OLLAMA_HOST=http://localhost:11434

# Logging (Optional)
LOG_LEVEL=INFO

# Railway Deployment (Optional)
SESSION_DATA=<base64-encoded-session-file>
```

### Configuration Dataclasses

**TelegramConfig:**
- `api_id` - Telegram API ID
- `api_hash` - Telegram API hash
- `phone` - Phone number with country code
- `bot_token` - Bot token from @BotFather
- `client_user_id` - Your user ID (from @userinfobot)

**DatabaseConfig:**
- `url` - SQLite or PostgreSQL connection string

**SchedulerConfig:**
- `summary_interval_hours` - Hours between summaries (default: 4)
- `max_messages_per_summary` - Max messages in summary (default: 15)
- `min_priority_score` - Minimum score to include (default: 1)
- `warning_threshold_score` - Score for real-time alert (default: 5)
- `timezone` - Timezone for scheduling (default: America/Sao_Paulo)

---

## Code Architecture Patterns

### Async-First Design
All major functions use `async/await` for non-blocking I/O:
```python
async def save_message(...):
    async with get_session() as session:
        # Database operations
        await session.commit()
```

### Global State Management
Single instances stored at module level:
- `_userbot_client` - Telethon TelegramClient
- `_bot_app` - telegram.ext.Application
- `_scheduler` - APScheduler instance
- `_engine` - SQLAlchemy async engine
- `_async_session_factory` - Session factory

### Context Managers
Safe resource management with automatic cleanup:
```python
async with get_session() as session:
    # Auto-commit on success, auto-rollback on error
```

### Error Handling
Try-catch blocks with structured logging:
```python
try:
    # Operation
except Exception as e:
    logger.error(f"Operation failed: {e}")
    # Graceful degradation
```

### Standalone Module Testing
Each module can run independently:
```bash
python main.py      # Full application
python bot.py       # Bot only
python userbot.py   # Userbot only
python scheduler.py # Scheduler only
```

### Graceful Shutdown
Signal handlers for clean exits:
```python
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
```

Shutdown sequence:
1. Stop accepting new messages
2. Complete in-flight operations
3. Close database connections
4. Stop scheduler
5. Disconnect clients
6. Exit cleanly

---

## Security & Privacy

### Authentication
- **Userbot**: Phone-based with encrypted session file
- **Bot**: Token-based authentication
- **2FA Support**: Compatible with Telegram 2FA

### Authorization
All bot commands validate ownership:
```python
if update.effective_user.id != config.telegram.client_user_id:
    await update.message.reply_text("⛔ Access denied")
    return
```

### Data Privacy
- **Local storage default**: SQLite keeps all data on your machine
- **No external AI calls**: Ollama runs localhost-only
- **No content logging**: Console logs sanitize message content
- **Encrypted secrets**: Environment variables, never in code
- **Session security**: Encrypted session file, never committed

### Message Filtering
Excludes:
- Self-sent messages (prevent loops)
- Bot messages (prevent loops)
- Media-only messages (no text to analyze)

### Deployment Security (Railway)
- Encrypted environment variables at rest
- HTTPS/TLS for all connections
- SOC 2 Type II certified
- GDPR compliant
- Team-based access control

---

## Performance Considerations

### Database Optimization
- **Composite indexes** for common query patterns
- **Connection pooling** (NullPool for PostgreSQL, StaticPool for SQLite)
- **Async queries** for non-blocking operations
- **Batch updates** for summary marking

### Memory Management
- **Lazy loading** of high-priority users (cached, refreshed every 5 minutes)
- **Limited query results** (default 15 messages per summary)
- **No in-memory message queue** (database-backed)

### Concurrency
- **Non-blocking polling** for bot and userbot
- **Parallel async operations** where possible
- **No thread blocking** in event handlers

### Scalability
- **Horizontal scaling**: Multiple bots per user account (not recommended)
- **Vertical scaling**: Handles 1000+ messages/day easily
- **Database scaling**: PostgreSQL supports millions of messages

---

## Development Workflow

### Local Development
1. Clone repository
2. Create `.env` from `.env.example`
3. Install dependencies: `pip install -r requirements.txt`
4. Run: `python main.py`

### Testing Modules Independently
```bash
# Test database connection
python database.py

# Test bot commands
python bot.py

# Test userbot message capture
python userbot.py

# Test scheduler
python scheduler.py
```

### Debugging
Enable debug logging:
```bash
LOG_LEVEL=DEBUG python main.py
```

### Database Inspection
```bash
# SQLite
sqlite3 secretary.db
.tables
.schema messages
SELECT * FROM messages LIMIT 10;

# PostgreSQL
psql $DATABASE_URL
\dt
\d messages
SELECT * FROM messages LIMIT 10;
```

---

## Deployment

### Local Deployment
```bash
python main.py
```

### Railway Deployment
1. Install Railway CLI: `npm install -g railway`
2. Login: `railway login`
3. Initialize: `railway init`
4. Add PostgreSQL: `railway add -d postgresql`
5. Set environment variables: `railway variables set KEY=VALUE`
6. Deploy: `railway up`

See [RAILWAY_DEPLOYMENT.md](../telegram-secretary/RAILWAY_DEPLOYMENT.md) for detailed instructions.

### Docker Deployment
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

---

## Future Enhancements

### Planned Features
1. **Machine Learning Priority Model** - Train on labeled data
2. **Quiet Hours** - Do not disturb periods
3. **Chat Exclusion** - Filter specific chats
4. **Custom Scoring Rules** - User-defined priority logic
5. **Web Dashboard** - View and manage messages via web UI
6. **Export Functionality** - Export messages to CSV/JSON
7. **Advanced Analytics** - Insights on communication patterns
8. **Multi-user Support** - Support multiple users per instance

### Possible Improvements
1. **Sentiment Analysis** - Detect urgency from tone
2. **Smart Reply Suggestions** - AI-generated response options
3. **Integration with Calendar** - Context-aware prioritization
4. **Voice Summaries** - Text-to-speech for summaries
5. **Mobile App** - Native mobile interface

---

## Common Issues & Troubleshooting

### Issue: "Phone number not registered"
**Solution:** Ensure you've created a Telegram account with the phone number in `.env`

### Issue: "Bot token invalid"
**Solution:** Generate a new token from @BotFather and update `BOT_TOKEN`

### Issue: "Database locked" (SQLite)
**Solution:** Don't run multiple instances with SQLite. Use PostgreSQL for concurrent access.

### Issue: "Session file missing"
**Solution:** Delete `secretary_session.session` and restart. You'll be prompted to re-authenticate.

### Issue: "Ollama connection failed"
**Solution:** This is optional. Bot works fine without Ollama. To enable, install Ollama and run `ollama pull llama3.2:3b`

### Issue: "No messages in summary"
**Solution:**
- Check `MIN_PRIORITY_SCORE` setting (lower it to include more messages)
- Verify userbot is running and capturing messages
- Check database for stored messages: `SELECT COUNT(*) FROM messages;`

---

## API Reference

### Main Functions

#### `main.py`
- `SecretaryBot.run()` - Main entry point
- `SecretaryBot.startup()` - Initialize all components
- `SecretaryBot.shutdown()` - Graceful shutdown

#### `userbot.py`
- `start_userbot()` - Start Telethon client
- `save_message(...)` - Process and store message
- `send_warning_for_message(...)` - Send real-time alert
- `handle_new_message(event)` - Message event handler

#### `bot.py`
- `start_bot()` - Start bot polling
- `send_summary(...)` - Send formatted summary
- `handle_start_command(...)` - `/start` handler
- `handle_summary_command(...)` - `/summary` handler
- `handle_stats_command(...)` - `/stats` handler
- `handle_label_callback(...)` - Button click handler

#### `scheduler.py`
- `start_scheduler()` - Initialize APScheduler
- `generate_and_send_summary()` - Main summary job
- `get_unlabeled_messages(...)` - Query top messages

#### `utils.py`
- `calculate_priority_score(...)` - Score message (0-8)
- `detect_mention(...)` - Check for @mention
- `detect_question(...)` - Check if question
- `generate_topic_summary(...)` - Call Ollama
- `format_message_card(...)` - Format for display

#### `database.py`
- `init_database()` - Create engine and tables
- `get_session()` - Context manager for sessions
- `create_tables()` - Create database schema

---

## Contributing Guidelines

### Code Style
- Follow PEP 8
- Use type hints
- Document functions with docstrings
- Keep functions focused and single-purpose

### Commit Messages
- Use conventional commits format
- Examples:
  - `feat: add quiet hours feature`
  - `fix: prevent duplicate warnings`
  - `docs: update setup guide`

### Pull Request Process
1. Fork repository
2. Create feature branch
3. Make changes with tests
4. Update documentation
5. Submit PR with description

---

## License

See LICENSE file in repository.

---

## Support & Contact

For issues, questions, or feature requests:
- Open an issue on GitHub
- Check existing documentation
- Review security audit for security concerns

---

## Acknowledgments

Built with:
- [Telethon](https://github.com/LonamiWebs/Telethon) - MTProto Telegram client
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) - Official Bot API wrapper
- [SQLAlchemy](https://www.sqlalchemy.org/) - SQL toolkit and ORM
- [APScheduler](https://apscheduler.readthedocs.io/) - Task scheduling
- [Ollama](https://ollama.ai/) - Local LLM runtime

---

**Last Updated:** January 2026
**Version:** 1.0.0
**Maintainer:** Project Owner
