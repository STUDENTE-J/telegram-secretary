"""
Utility functions for Telegram Secretary Bot.
Includes scoring system, message formatting, and helper functions.
"""

import logging
import re
from datetime import datetime
from typing import Optional

from models import Message
from errors import (
    log_error,
    log_warning,
    log_info,
    ErrorCategory,
)

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

# Priority Scoring Weights (Rule-based system, 0-8 scale)
SCORE_MENTION = 3                    # Points awarded for @mention
SCORE_QUESTION = 2                   # Points awarded for question
SCORE_LONG_MESSAGE = 1               # Points awarded for long message
SCORE_HIGH_PRIORITY_USER = 2         # Points awarded for high-priority sender
MIN_LONG_MESSAGE_LENGTH = 100        # Character threshold for "long message"

# Text Truncation Limits
DEFAULT_TRUNCATE_LENGTH = 200        # Default max length for truncated text
MESSAGE_CARD_PREVIEW_LENGTH = 150    # Max length for message cards in summaries
WARNING_PREVIEW_LENGTH = 200         # Max length for warning message previews

# AI Configuration
AI_MESSAGE_TRUNCATE_LENGTH = 500     # Max characters sent to AI for scoring
AI_TOPIC_SUMMARY_TRUNCATE_LENGTH = 500  # Max characters for topic summary
AI_TOPIC_SUMMARY_TIMEOUT = 5.0       # Timeout in seconds for topic generation
AI_TOPIC_SUMMARY_MAX_WORDS = 5       # Max words returned from topic summary
AI_PRIORITY_SCORE_MIN = 0            # Minimum AI priority score
AI_PRIORITY_SCORE_MAX = 10           # Maximum AI priority score
OLLAMA_NUM_PREDICT_SCORE = 5         # Tokens for AI scoring response
OLLAMA_NUM_PREDICT_TOPIC = 20        # Tokens for topic summary response
OLLAMA_TEMPERATURE_SCORE = 0.1       # Temperature for consistent scoring
OLLAMA_TEMPERATURE_TOPIC = 0.3       # Temperature for topic summary

# Topic Summary Configuration
MIN_TEXT_LENGTH_FOR_TOPIC = 10       # Minimum characters needed for topic summary

# Muted Chat Detection
MUTE_FOREVER_TIMESTAMP = 2147483647  # Telegram's "mute forever" value


def calculate_priority_score(
    message_text: Optional[str],
    has_mention: bool,
    is_question: bool,
    is_high_priority_user: bool = False
) -> int:
    """
    Calculate priority score for a message based on simple rules.
    
    Scoring:
        - Has @mention: +3 points
        - Is a question (ends with ?): +2 points
        - Text length > 100 chars: +1 point
        - Sender is marked high priority: +2 points
    
    Returns:
        Integer priority score
    """
    score = 0
    
    if has_mention:
        score += SCORE_MENTION
    
    if is_question:
        score += SCORE_QUESTION
    
    if message_text and len(message_text) > MIN_LONG_MESSAGE_LENGTH:
        score += SCORE_LONG_MESSAGE
    
    if is_high_priority_user:
        score += SCORE_HIGH_PRIORITY_USER
    
    return score


def detect_mention(text: Optional[str], username: Optional[str] = None) -> bool:
    """
    Detect if message contains an @mention.
    
    Args:
        text: Message text
        username: Optional specific username to check for
    
    Returns:
        True if mention detected
    """
    if not text:
        return False
    
    # General @mention pattern
    mention_pattern = r"@\w+"
    
    if username:
        # Check for specific username mention
        return f"@{username}" in text.lower() or bool(re.search(mention_pattern, text))
    
    return bool(re.search(mention_pattern, text))


def detect_question(text: Optional[str]) -> bool:
    """
    Detect if message is a question.
    
    Checks for:
        - Ends with ?
        - Contains question words (optional enhancement)
    
    Returns:
        True if message appears to be a question
    """
    if not text:
        return False
    
    text = text.strip()
    
    # Primary check: ends with question mark
    if text.endswith("?"):
        return True
    
    # Secondary check: starts with common question words
    question_starters = [
        "what", "when", "where", "why", "how", "who", "which",
        "is ", "are ", "do ", "does ", "can ", "could ", "would ", "will ",
        "should ", "have ", "has ", "did ",
        # Portuguese question words
        "que ", "qual ", "quem ", "quando ", "onde ", "como ", "por que",
        "você ", "vocês ",
    ]
    
    text_lower = text.lower()
    for starter in question_starters:
        if text_lower.startswith(starter):
            return True
    
    return False


def truncate_text(text: Optional[str], max_length: int = DEFAULT_TRUNCATE_LENGTH) -> str:
    """Truncate text to max length with ellipsis."""
    if not text:
        return "[No text]"

    if len(text) <= max_length:
        return text

    return text[:max_length - 3] + "..."


def get_priority_emoji(label: Optional[str]) -> str:
    """Get emoji for priority label."""
    return {
        "high": "🔴",
        "medium": "🟡",
        "low": "🟢",
    }.get(label, "⚪")


def get_priority_from_score(score: int) -> str:
    """Suggest initial priority based on score."""
    if score >= 5:
        return "high"
    elif score >= 3:
        return "medium"
    else:
        return "low"


def format_summary_header(
    total_messages: int,
    total_chats: int,
    time_range_hours: int
) -> str:
    """Format the header for a summary message."""
    return (
        f"📊 *Summary of last {time_range_hours} hours*\n"
        f"You received *{total_messages}* messages in *{total_chats}* conversations.\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )


def format_message_card(
    message: Message,
    index: int,
    suggested_priority: Optional[str] = None
) -> str:
    """
    Format a single message for the summary.
    
    Returns:
        Formatted message card string
    """
    # Determine chat type display
    if message.chat_type == "private":
        chat_info = "💬 Private chat"
    else:
        chat_info = f"💬 Group: {message.chat_title or 'Unknown'}"
    
    # Format sender name
    sender = message.user_name or f"User {message.user_id}"
    
    # Truncate message text
    text = truncate_text(message.message_text, 150)
    
    # Build indicators
    indicators = []
    if message.has_mention:
        indicators.append("📢 Mention")
    if message.is_question:
        indicators.append("❓ Question")
    
    indicator_str = " | ".join(indicators) if indicators else ""
    
    # Suggested priority based on score
    if suggested_priority:
        priority_indicator = f"{get_priority_emoji(suggested_priority)} Suggested: {suggested_priority.title()}"
    else:
        priority_indicator = ""
    
    # Build card
    lines = [
        f"\n*{index}.* 👤 *{sender}*",
        chat_info,
        f"📝 \"{text}\"",
    ]
    
    if indicator_str:
        lines.append(f"📌 {indicator_str}")
    
    if priority_indicator:
        lines.append(priority_indicator)
    
    lines.append(f"⏰ {message.timestamp.strftime('%H:%M')}")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    
    return "\n".join(lines)


def format_summary_footer(labeled_count: int, pending_count: int) -> str:
    """Format the footer for a summary message."""
    if pending_count > 0:
        return f"\n⏳ {pending_count} messages waiting for your review"
    else:
        return f"\n✅ All {labeled_count} messages have been labeled!"


def format_labeling_confirmation(label: str, message_preview: str) -> str:
    """Format confirmation message after labeling."""
    emoji = get_priority_emoji(label)
    return f"{emoji} Marked as *{label.title()}* Priority\n\n_{truncate_text(message_preview, 50)}_"


def get_chat_type(chat) -> str:
    """
    Determine chat type from Telethon chat object.

    Returns one of: 'private', 'group', 'supergroup', 'gigagroup', 'channel'

    Note: Channel's broadcast, megagroup, and gigagroup attributes are mutually exclusive.
    - Chat: Regular group (legacy, <200 members originally)
    - Channel with broadcast=True: Broadcast channel
    - Channel with megagroup=True: Supergroup (most common)
    - Channel with gigagroup=True: Broadcast group (50k+ members)
    """
    from telethon.tl.types import (
        Channel,
        Chat,
        User,
    )

    if isinstance(chat, User):
        return "private"
    elif isinstance(chat, Chat):
        return "group"  # Legacy small group
    elif isinstance(chat, Channel):
        # Check mutually exclusive flags in order of specificity
        if getattr(chat, 'gigagroup', False):
            return "gigagroup"  # Very large broadcast group (50k+ members)
        elif chat.megagroup:
            return "supergroup"  # Regular supergroup
        elif chat.broadcast:
            return "channel"  # Broadcast channel
        else:
            return "channel"  # Fallback to channel
    
    return "unknown"


def sanitize_for_logging(text: Optional[str]) -> str:
    """
    Sanitize message text for logging.
    Returns a safe representation without actual content.
    
    SECURITY: Never log actual message content.
    """
    if not text:
        return "[empty]"
    return f"[{len(text)} chars]"


def escape_markdown(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text


async def calculate_ai_priority_score(
    message_text: Optional[str],
    user_name: Optional[str],
    chat_title: Optional[str],
    chat_type: str,
    ollama_host: str = "http://localhost:11434",
    model: str = "llama3.2:3b",
    timeout: float = 3.0
) -> Optional[int]:
    """
    Calculate priority score using AI (0-10 scale).

    Uses local Ollama LLM to intelligently score messages based on:
    - Urgency (time-sensitive, deadlines)
    - Importance (actionable requests, questions needing answers)
    - Sentiment (anger, excitement, frustration)
    - Context (follow-ups, confirmations)

    Args:
        message_text: The message content
        user_name: Who sent it
        chat_title: Chat name/title
        chat_type: 'private', 'group', 'supergroup', or 'channel'
        ollama_host: Ollama server URL (default: localhost)
        model: Model to use (default: llama3.2:3b)
        timeout: Maximum seconds to wait (default: 3.0)

    Returns:
        Integer score 0-10, or None if AI fails (fallback to rule-based)
    """
    if not message_text or len(message_text) < 1:
        return AI_PRIORITY_SCORE_MIN

    try:
        import ollama
        import asyncio

        # Truncate very long messages
        truncated = (
            message_text[:AI_MESSAGE_TRUNCATE_LENGTH]
            if len(message_text) > AI_MESSAGE_TRUNCATE_LENGTH
            else message_text
        )

        # Build context
        chat_context = "private conversation" if chat_type == "private" else f"group chat '{chat_title}'"
        sender = user_name or "Unknown"

        # Get user context/profile for personalization
        user_context_text = ""
        user_profile_instruction = ""
        try:
            from config import get_config
            from database import get_session
            from models import UserPreferences
            from sqlalchemy import select

            config = get_config()
            async with get_session() as session:
                result = await session.execute(
                    select(UserPreferences.user_context)
                    .where(UserPreferences.user_id == config.telegram.client_user_id)
                )
                user_context = result.scalar_one_or_none()

                if user_context:
                    user_context_text = f"\n\n📋 USER PROFILE:\n{user_context}\n"
                    user_profile_instruction = f"\n🚨 PROFILE FILTERING (MOST IMPORTANT):\n- If message topic is UNRELATED to user's stated work/priorities → MAX score 3\n- If message is OFF-TOPIC or about different industry/technology → score 0-2\n- ONLY score 4+ if message is DIRECTLY relevant to user's profile"
        except Exception:
            # If we can't get user context, continue without it
            pass

        # Prompt for AI scoring - ULTRA STRICT WITH PROFILE FILTERING
        prompt = f"""You are an EXTREMELY STRICT message priority classifier. Score this Telegram message from 0-10.{user_context_text}{user_profile_instruction}

🚨 CRITICAL RULES (in order of importance):
1. **PROFILE RELEVANCE CHECK FIRST**: If user has a profile, check if message relates to their work. If OFF-TOPIC → MAX score 3
2. DEFAULT TO 0-3 for 90% of messages
3. Score 4-6 ONLY if actionable, time-sensitive AND on-topic
4. Score 7+ ONLY for genuine urgency with deadlines AND on-topic
5. Score 10 ONLY for true emergencies related to user's work

ULTRA-STRICT SCORING GUIDE:

0-1 = OFF-TOPIC or minimal response
    Examples: Topics unrelated to user's work, emojis, "👍", "ok", "lol", "thanks"
    Rule: If message is about different industry/tech than user's profile → 0-1
    Rule: If no action needed and no information value → 0-1

2-3 = Casual or somewhat related
    Examples: General announcements in related field, "how are you?", small talk
    Rule: Tangentially related to user's work but no action needed → 2-3
    Rule: Off-topic invitations or announcements → 2-3

4-5 = ON-TOPIC discussion or general questions
    Examples: Questions about user's specific field, relevant discussions
    Rule: MUST be directly related to user's work area
    Rule: Needs response eventually but NO deadline → 4-5

6-7 = ON-TOPIC specific requests
    Examples: Requests related to user's work, coordination in user's field
    Rule: MUST be relevant to user's profile AND require specific action
    Rule: Flexible timing, no hard deadline → 6-7

8-9 = URGENT AND ON-TOPIC with deadline
    Examples: Deadlines in user's work, client waiting for user's specific expertise
    Rule: MUST be relevant to user's work AND have explicit urgency
    Rule: "need by EOD", "client waiting", "meeting in 30min" → 8-9

10 = EMERGENCY in user's domain
    Examples: Critical issues in user's specific area of work
    Rule: Only genuine emergencies directly impacting user's responsibilities

SCORING RULES:
❌ Messages about topics OUTSIDE user's profile → MAX score 3
❌ Different industry/technology than user's work → score 0-2
❌ NO greeting/small talk above 3
❌ NO off-topic requests above 3 (even if urgent-sounding)
❌ NO general questions above 5
❌ NO requests without deadlines above 7
❌ NO score 8+ unless BOTH urgent AND on-topic
✅ When in doubt → score LOWER
✅ Off-topic = automatically score ≤ 3
✅ Casual tone = automatically score ≤ 3
✅ No question mark + no deadline = score ≤ 4

MESSAGE TO SCORE:
From: {sender}
Chat: {chat_context}
Message: "{truncated}"

Respond with ONLY ONE NUMBER (0-10). No text. Be EXTREMELY strict - most messages score 0-3.
Score:"""

        # Run in thread to not block async loop
        def call_ollama():
            client = ollama.Client(host=ollama_host)
            response = client.chat(
                model=model,
                messages=[{'role': 'user', 'content': prompt}],
                options={
                    'num_predict': OLLAMA_NUM_PREDICT_SCORE,
                    'temperature': OLLAMA_TEMPERATURE_SCORE,
                }
            )
            return response['message']['content'].strip()

        # Run with timeout
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, call_ollama),
            timeout=timeout
        )

        # Parse the score
        # Extract first number from response
        import re
        numbers = re.findall(r'\d+', result)
        if numbers:
            score = int(numbers[0])
            # Clamp to valid range
            score = max(AI_PRIORITY_SCORE_MIN, min(AI_PRIORITY_SCORE_MAX, score))
            logger.debug(f"AI scored message as {score}/{AI_PRIORITY_SCORE_MAX}: {sanitize_for_logging(message_text)}")
            return score
        else:
            log_warning(
                ErrorCategory.AI_SCORING,
                "AI returned non-numeric response, falling back to rule-based scoring",
                context={"response": result[:50], "model": model}
            )
            return None

    except ImportError:
        logger.debug("Ollama not installed, skipping AI scoring")
        return None
    except asyncio.TimeoutError:
        logger.debug(f"AI scoring timeout after {timeout}s, falling back to rule-based scoring")
        return None
    except Exception as e:
        log_warning(
            ErrorCategory.AI_SCORING,
            "AI scoring failed, falling back to rule-based scoring",
            context={"error": str(e), "model": model, "host": ollama_host}
        )
        return None


async def generate_topic_summary(text: Optional[str]) -> Optional[str]:
    """
    Generate a 3-word topic summary using local Ollama LLM.

    Args:
        text: Message text to summarize

    Returns:
        3-word topic summary or None if Ollama unavailable
    """
    if not text or len(text) < MIN_TEXT_LENGTH_FOR_TOPIC:
        return None

    try:
        import ollama
        import asyncio
        import os

        # SECURITY: By default, use localhost to ensure no external data transmission
        # Allow Railway internal service URLs (e.g., http://ollama-service:11434)
        # for same-network communication within Railway
        ollama_host = os.getenv('OLLAMA_HOST', 'http://localhost:11434')

        # Allow localhost, 127.0.0.1, or Railway internal service URLs
        # Railway services can communicate via service names (e.g., ollama-service:11434)
        allowed_hosts = (
            'http://localhost', 'http://127.0.0.1',
            'http://ollama-service',  # Railway service name
            'https://localhost', 'https://127.0.0.1'
        )

        if not any(ollama_host.startswith(host) for host in allowed_hosts):
            # Check if it's a Railway internal URL (service name without http://)
            if ':' in ollama_host and not ollama_host.startswith('http'):
                # Assume it's a Railway service name, add http://
                ollama_host = f'http://{ollama_host}'
                log_info(
                    ErrorCategory.CONFIGURATION,
                    "Using Railway internal service for Ollama",
                    context={"host": ollama_host}
                )
            else:
                log_warning(
                    ErrorCategory.CONFIGURATION,
                    "OLLAMA_HOST may send data externally, falling back to localhost",
                    context={
                        "configured_host": ollama_host,
                        "fallback_host": "http://localhost:11434"
                    }
                )
                ollama_host = 'http://localhost:11434'

        # Truncate very long messages to avoid slow processing
        truncated = (
            text[:AI_TOPIC_SUMMARY_TRUNCATE_LENGTH]
            if len(text) > AI_TOPIC_SUMMARY_TRUNCATE_LENGTH
            else text
        )

        prompt = f"""Summarize this message in EXACTLY 3 words. Be specific about the topic.

Message: "{truncated}"

Reply with ONLY 3 words, nothing else. Example: "Meeting schedule request" or "Christmas party invitation" or "Project deadline reminder"

3-word summary:"""

        # Run in thread to not block async loop
        def call_ollama():
            # Use explicit localhost client to ensure privacy
            client = ollama.Client(host=ollama_host)
            response = client.chat(
                model='llama3.2:3b',
                messages=[{'role': 'user', 'content': prompt}],
                options={
                    'num_predict': OLLAMA_NUM_PREDICT_TOPIC,
                    'temperature': OLLAMA_TEMPERATURE_TOPIC,
                }
            )
            return response['message']['content'].strip()

        # Run with timeout
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, call_ollama),
            timeout=AI_TOPIC_SUMMARY_TIMEOUT
        )

        # Clean up result - take only first few words
        words = result.split()[:AI_TOPIC_SUMMARY_MAX_WORDS]
        return ' '.join(words)

    except ImportError:
        # Ollama not installed
        return None
    except asyncio.TimeoutError:
        # Ollama too slow
        return None
    except Exception:
        # Ollama not running or other error
        return None

