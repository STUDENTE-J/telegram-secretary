"""
Telethon userbot for capturing all incoming Telegram messages.
Logs into the client's Telegram account and monitors all chats.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Set, Dict

from telegram.constants import ParseMode
from telethon import TelegramClient, events
from telethon.tl.types import User, Chat, Channel
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.errors import FloodWaitError
from sqlalchemy.exc import OperationalError

from config import get_config
from database import get_session
from models import Message, HighPriorityUser
from utils import (
    MUTE_FOREVER_TIMESTAMP,
    WARNING_PREVIEW_LENGTH,
    calculate_ai_priority_score,
    calculate_priority_score,
    detect_mention,
    detect_question,
    escape_markdown,
    generate_topic_summary,
    get_chat_type,
    sanitize_for_logging,
    truncate_text,
)
from errors import (
    log_error,
    log_warning,
    log_info,
    ErrorCategory,
    DatabaseError,
    TelegramAPIError,
    MessageProcessingError,
)

logger = logging.getLogger(__name__)

# Global client instance
_userbot_client: Optional[TelegramClient] = None

# Cache of high priority user IDs (refreshed periodically)
_high_priority_users: Set[int] = set()

# Cache of muted chat IDs (refreshed periodically)
_muted_chats: Set[int] = set()

# Cache of group sizes (chat_id -> participant_count, refreshed periodically)
_group_sizes: Dict[int, int] = {}


def _get_bot_user_id() -> int:
    """Extract bot user ID from bot token (format: BOT_ID:SECRET)."""
    config = get_config()
    return int(config.telegram.bot_token.split(":")[0])


async def get_userbot_client() -> TelegramClient:
    """Get or create the Telethon userbot client."""
    global _userbot_client
    
    if _userbot_client is None:
        import os
        import base64
        
        config = get_config()
        session_name = "secretary_session"
        
        # Support SESSION_DATA environment variable (base64-encoded session file)
        # This makes Railway deployment easier - can store session as env var
        session_data_env = os.getenv("SESSION_DATA")
        if session_data_env:
            try:
                # Decode base64 session data and write to file
                session_bytes = base64.b64decode(session_data_env)
                with open(f"{session_name}.session", "wb") as f:
                    f.write(session_bytes)
                log_info(ErrorCategory.CONFIGURATION, "Session file created from SESSION_DATA environment variable")
            except Exception as e:
                log_warning(
                    ErrorCategory.CONFIGURATION,
                    "Failed to decode SESSION_DATA, will use file-based session",
                    context={"error": str(e)}
                )
        
        _userbot_client = TelegramClient(
            session_name,  # Session file name
            config.telegram.api_id,
            config.telegram.api_hash,
        )
    
    return _userbot_client


async def send_warning_for_message(
    message_id: int,
    chat_id: int,
    message_text: Optional[str],
    user_name: Optional[str],
    chat_title: Optional[str],
    chat_type: str,
    priority_score: int,
    has_mention: bool,
    is_question: bool,
    topic_summary: Optional[str],
) -> None:
    """
    Send a real-time warning to the client for high-priority messages.

    This sends an immediate alert when a message meets the warning threshold.
    """
    try:
        from bot import send_simple_message, create_priority_keyboard, get_bot_app
        from datetime import datetime
        from sqlalchemy import update as sql_update
        
        bot_app = get_bot_app()
        if not bot_app:
            log_warning(
                ErrorCategory.TELEGRAM_API,
                "Bot app not available, cannot send warning",
                context={"message_id": message_id}
            )
            return
        
        config = get_config()
        bot = bot_app.bot

        # Store original chat_id for keyboard (the chat to mute)
        original_chat_id = chat_id

        # Overwrite chat_id for sending TO the user
        chat_id = config.telegram.client_user_id

        # Format chat info
        if chat_type == "private":
            chat_info = "💬 Private chat"
        else:
            chat_title_safe = escape_markdown(chat_title or 'Unknown Group')
            chat_info = f"💬 {chat_title_safe}"

        # Escape all user-provided text to prevent Markdown parsing errors
        sender = escape_markdown(user_name or "Unknown User")
        text_preview = escape_markdown(truncate_text(message_text, WARNING_PREVIEW_LENGTH))

        # Build indicators
        indicators = []
        if has_mention:
            indicators.append("📢 Mention")
        if is_question:
            indicators.append("❓ Question")

        indicator_line = f"\n📌 {' | '.join(indicators)}" if indicators else ""

        # Escape topic summary if present
        if topic_summary:
            topic_safe = escape_markdown(topic_summary)
            topic_line = f"\n🏷️ Topic: {topic_safe}"
        else:
            topic_line = ""

        # Create warning message
        warning_text = f"""
🚨 *IMPORTANT MESSAGE ALERT*

👤 *{sender}*
{chat_info}{topic_line}
📝 "{text_preview}"
{indicator_line}
📈 Priority Score: {priority_score}
⏰ {datetime.utcnow().strftime('%H:%M - %d/%m')}

*Please classify this message:*
        """.strip()

        # Send warning with classification buttons
        # Use original_chat_id (the chat to mute), not chat_id (where to send)
        keyboard = create_priority_keyboard(message_id, original_chat_id, chat_title or "Unknown")
        await bot.send_message(
            chat_id=chat_id,
            text=warning_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )
        
        # Mark warning as sent in database (with retry for SQLite concurrency)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with get_session() as session:
                    await session.execute(
                        sql_update(Message)
                        .where(Message.id == message_id)
                        .values(
                            warning_sent=True,
                            warning_sent_at=datetime.utcnow()
                        )
                    )
                break  # Success - exit retry loop
            except OperationalError as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.1)  # Wait 100ms before retry
                    log_warning(
                        ErrorCategory.DATABASE,
                        f"Database locked, retrying ({attempt + 2}/{max_retries})",
                        context={"message_id": message_id, "error": str(e)}
                    )
                else:
                    # Final attempt failed, re-raise the error
                    log_error(
                        ErrorCategory.DATABASE,
                        f"Failed to mark warning as sent after {max_retries} attempts",
                        error=e,
                        context={"message_id": message_id}
                    )
                    raise
        
        log_info(
            ErrorCategory.TELEGRAM_API,
            f"Warning sent for high-priority message",
            context={
                "message_id": message_id,
                "chat_id": original_chat_id,  # Use original_chat_id, not overwritten chat_id
                "chat_title": chat_title,
                "score": priority_score
            }
        )

    except Exception as e:
        log_error(
            ErrorCategory.TELEGRAM_API,
            f"Failed to send warning for message",
            error=e,
            context={"message_id": message_id, "score": priority_score},
            include_trace=True
        )


async def refresh_high_priority_users() -> None:
    """Refresh the cache of high priority user IDs."""
    global _high_priority_users

    from sqlalchemy import select

    try:
        async with get_session() as session:
            result = await session.execute(
                select(HighPriorityUser.user_id)
            )
            _high_priority_users = {row[0] for row in result.fetchall()}

        log_info(
            ErrorCategory.DATABASE,
            "Refreshed high priority users cache",
            context={"count": len(_high_priority_users)}
        )
    except Exception as e:
        log_error(
            ErrorCategory.DATABASE,
            "Failed to refresh high priority users cache",
            error=e,
            include_trace=True
        )


async def refresh_muted_chats() -> None:
    """
    Refresh the cache of muted chat IDs using iter_dialogs().
    This is the RELIABLE way to check mute status according to Telethon docs.
    """
    global _muted_chats

    try:
        client = await get_userbot_client()
        if not client or not client.is_connected():
            log_warning(
                ErrorCategory.TELEGRAM_API,
                "Cannot refresh muted chats - client not connected"
            )
            return

        muted_set = set()
        current_timestamp = datetime.now(timezone.utc).timestamp()

        # Iterate through all dialogs to get notification settings
        async for dialog in client.iter_dialogs():
            try:
                # Access raw dialog notify_settings (MOST RELIABLE METHOD)
                notify_settings = dialog.dialog.notify_settings

                if not notify_settings:
                    continue

                chat_id = dialog.id
                is_muted = False

                # Check silent flag first
                if hasattr(notify_settings, 'silent') and notify_settings.silent:
                    is_muted = True

                # Check mute_until field
                if hasattr(notify_settings, 'mute_until') and notify_settings.mute_until is not None:
                    mute_until = notify_settings.mute_until

                    # Handle different types of mute_until
                    if mute_until is True or mute_until == MUTE_FOREVER_TIMESTAMP:
                        # Muted forever
                        is_muted = True
                    elif isinstance(mute_until, int):
                        # Unix timestamp - check if in future
                        is_muted = mute_until > current_timestamp
                    elif isinstance(mute_until, datetime):
                        # Datetime object - check if in future
                        is_muted = mute_until > datetime.now(timezone.utc)

                if is_muted:
                    muted_set.add(chat_id)

            except Exception as e:
                # Log but continue - don't let one dialog break everything
                logger.debug(f"Error checking dialog {dialog.id}: {e}")
                continue

        # Update global cache
        _muted_chats = muted_set

        log_info(
            ErrorCategory.FILTERING,
            "Refreshed muted chats cache",
            context={"muted_count": len(_muted_chats)}
        )

    except Exception as e:
        log_error(
            ErrorCategory.TELEGRAM_API,
            "Failed to refresh muted chats cache",
            error=e,
            include_trace=True
        )


async def refresh_group_sizes() -> None:
    """
    Refresh the cache of group sizes using iter_dialogs() and GetFullChannelRequest.
    This is the RELIABLE way to get participant counts according to Telethon docs.
    """
    global _group_sizes

    try:
        client = await get_userbot_client()
        if not client or not client.is_connected():
            log_warning(
                ErrorCategory.TELEGRAM_API,
                "Cannot refresh group sizes - client not connected"
            )
            return

        sizes_dict = {}

        # Iterate through all dialogs to get group/supergroup sizes
        async for dialog in client.iter_dialogs():
            try:
                # Only process groups and supergroups
                if not dialog.is_group:
                    continue

                entity = dialog.entity
                chat_id = dialog.id
                participant_count = None

                # Method based on entity type (from user's research)
                if isinstance(entity, Chat):
                    # Regular group - participants_count is directly available
                    participant_count = getattr(entity, 'participants_count', None)

                    # Fallback: try GetFullChatRequest if not available
                    if participant_count is None:
                        try:
                            full = await client(GetFullChatRequest(entity.id))
                            participant_count = full.full_chat.participants_count
                        except FloodWaitError as e:
                            # Hit rate limit - stop refreshing
                            log_warning(
                                ErrorCategory.TELEGRAM_API,
                                f"Hit flood wait during group size refresh (need to wait {e.seconds}s)",
                                context={
                                    "groups_cached_so_far": len(sizes_dict),
                                    "wait_seconds": e.seconds
                                }
                            )
                            break
                        except Exception:
                            pass

                elif isinstance(entity, Channel) and entity.megagroup:
                    # Supergroup - use GetFullChannelRequest for RELIABLE count
                    try:
                        full = await client(GetFullChannelRequest(entity))
                        participant_count = full.full_chat.participants_count
                    except FloodWaitError as e:
                        # Hit rate limit - stop refreshing and use what we have so far
                        log_warning(
                            ErrorCategory.TELEGRAM_API,
                            f"Hit flood wait during group size refresh (need to wait {e.seconds}s)",
                            context={
                                "groups_cached_so_far": len(sizes_dict),
                                "wait_seconds": e.seconds
                            }
                        )
                        # Break out of dialog loop - we'll try again in next scheduled refresh
                        break
                    except Exception:
                        # Fallback to entity attribute (may be None)
                        participant_count = getattr(entity, 'participants_count', None)

                # Store in cache if we got a count
                if participant_count is not None:
                    sizes_dict[chat_id] = participant_count

            except FloodWaitError:
                # Caught at outer level - break out of loop
                break
            except Exception as e:
                # Log but continue - don't let one dialog break everything
                logger.debug(f"Error getting size for dialog {dialog.id}: {e}")
                continue

        # Update global cache (even if partial due to flood wait)
        if sizes_dict:
            _group_sizes = sizes_dict

            log_info(
                ErrorCategory.FILTERING,
                "Refreshed group sizes cache",
                context={
                    "groups_cached": len(_group_sizes),
                    "total_participants": sum(_group_sizes.values())
                }
            )
        else:
            log_warning(
                ErrorCategory.FILTERING,
                "Group size refresh returned no results (may have hit flood wait immediately)"
            )

    except Exception as e:
        log_error(
            ErrorCategory.TELEGRAM_API,
            "Failed to refresh group sizes cache",
            error=e,
            include_trace=True
        )


def get_muted_chats() -> Set[int]:
    """
    Get the current set of muted chat IDs.

    Returns:
        Set of chat IDs that are muted
    """
    return _muted_chats.copy()


def add_muted_chat(chat_id: int) -> None:
    """
    Add a chat ID to the muted chats cache (optimistic update).

    Args:
        chat_id: Chat ID to add
    """
    global _muted_chats
    _muted_chats.add(chat_id)
    log_info(
        ErrorCategory.FILTERING,
        "Added chat to muted cache",
        context={"chat_id": chat_id, "total_muted": len(_muted_chats)}
    )


def remove_muted_chat(chat_id: int) -> None:
    """
    Remove a chat ID from the muted chats cache (optimistic update).

    Args:
        chat_id: Chat ID to remove
    """
    global _muted_chats
    _muted_chats.discard(chat_id)
    log_info(
        ErrorCategory.FILTERING,
        "Removed chat from muted cache",
        context={"chat_id": chat_id, "total_muted": len(_muted_chats)}
    )


def get_large_group_ids(max_size: int) -> Set[int]:
    """
    Get chat IDs of groups that exceed the maximum size.

    Args:
        max_size: Maximum group size threshold

    Returns:
        Set of chat IDs for groups larger than max_size
    """
    return {chat_id for chat_id, size in _group_sizes.items() if size > max_size}


async def save_message(
    telegram_message_id: int,
    chat_id: int,
    chat_title: Optional[str],
    chat_type: str,
    user_id: int,
    user_name: Optional[str],
    message_text: Optional[str],
    timestamp: datetime,
    client_username: Optional[str] = None,
) -> None:
    """
    Save a captured message to the database.
    
    Extracts metadata, calculates priority score, and stores.
    """
    try:
        config = get_config()

        # Detect metadata (used for both AI and rule-based scoring)
        has_mention = detect_mention(message_text, client_username)
        is_question = detect_question(message_text)
        message_length = len(message_text) if message_text else 0
        is_high_priority = user_id in _high_priority_users

        # Calculate priority score with AI (if enabled) or rule-based fallback
        priority_score = None

        if config.ai.enabled:
            # Try AI scoring first
            logger.debug(f"Attempting AI scoring for message from {user_name}")
            priority_score = await calculate_ai_priority_score(
                message_text=message_text,
                user_name=user_name,
                chat_title=chat_title,
                chat_type=chat_type,
                ollama_host=config.ai.ollama_host,
                model=config.ai.model,
                timeout=config.ai.timeout_seconds,
            )

            if priority_score is not None:
                logger.info(f"AI scored message as {priority_score}/10")
            else:
                logger.debug("AI scoring failed, falling back to rule-based")

        # Fallback to rule-based scoring if AI disabled or failed
        if priority_score is None:
            priority_score = calculate_priority_score(
                message_text=message_text,
                has_mention=has_mention,
                is_question=is_question,
                is_high_priority_user=is_high_priority,
            )
            logger.debug(f"Rule-based score: {priority_score}/8")

        # Generate AI topic summary (non-blocking, with fallback)
        topic_summary = await generate_topic_summary(message_text)
        
        # Create message record
        message = Message(
            telegram_message_id=telegram_message_id,
            chat_id=chat_id,
            chat_title=chat_title,
            chat_type=chat_type,
            user_id=user_id,
            user_name=user_name,
            message_text=message_text,
            timestamp=timestamp,
            has_mention=has_mention,
            is_question=is_question,
            message_length=message_length,
            priority_score=priority_score,
            topic_summary=topic_summary,
        )
        
        async with get_session() as session:
            session.add(message)
            await session.flush()  # Flush to get the message ID
            message_id = message.id
            # Commit happens automatically via context manager
        
        # Check if we should send a real-time warning
        # Load user preferences to get their warning threshold
        from sqlalchemy import select
        from models import UserPreferences

        warning_threshold = config.scheduler.warning_threshold_score  # Default from env
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(UserPreferences.warning_threshold_score)
                    .where(UserPreferences.user_id == config.telegram.client_user_id)
                )
                user_threshold = result.scalar_one_or_none()
                if user_threshold is not None:
                    warning_threshold = user_threshold
        except Exception as e:
            log_warning(
                ErrorCategory.DATABASE,
                "Could not load user warning threshold, using default",
                context={"error": str(e)}
            )

        if priority_score >= warning_threshold:
            await send_warning_for_message(
                message_id=message_id,
                chat_id=chat_id,
                message_text=message_text,
                user_name=user_name,
                chat_title=chat_title,
                chat_type=chat_type,
                priority_score=priority_score,
                has_mention=has_mention,
                is_question=is_question,
                topic_summary=topic_summary,
            )
        
        # Log safely (no message content!)
        logger.debug(
            f"Saved message {telegram_message_id} from chat {chat_id}, "
            f"user {user_id}, score={priority_score}, "
            f"text={sanitize_for_logging(message_text)}"
        )

    except Exception as e:
        log_error(
            ErrorCategory.MESSAGE_PROCESSING,
            "Failed to save message to database",
            error=e,
            context={
                "telegram_message_id": telegram_message_id,
                "chat_id": chat_id,
                "user_id": user_id,
            },
            include_trace=True
        )


async def start_userbot() -> None:
    """
    Start the userbot client and begin monitoring messages.
    
    This will:
    1. Connect to Telegram (may require phone code on first run)
    2. Register message handler
    3. Start receiving events
    """
    config = get_config()
    client = await get_userbot_client()
    
    # Get the client's own user info for mention detection
    client_username: Optional[str] = None
    client_user_id: Optional[int] = None
    
    @client.on(events.NewMessage(incoming=True))
    async def handle_new_message(event):
        """Handle incoming messages from all chats."""
        try:
            message = event.message
            chat = await event.get_chat()
            sender = await event.get_sender()

            # Skip messages from ourselves
            if sender and sender.id == client_user_id:
                return

            # Skip messages from our own bot
            bot_user_id = _get_bot_user_id()
            if sender and sender.id == bot_user_id:
                return

            # Skip messages without text (media-only, etc.)
            # Future: could extract captions from media
            # Use raw_text for reliability (message.text can be None in some cases)
            if not message.raw_text:
                return

            # Get user preferences for filtering settings
            from sqlalchemy import select
            from models import UserPreferences

            user_prefs = None
            try:
                async with get_session() as session:
                    result = await session.execute(
                        select(UserPreferences)
                        .where(UserPreferences.user_id == config.telegram.client_user_id)
                    )
                    user_prefs = result.scalar_one_or_none()
            except Exception as e:
                log_warning(
                    ErrorCategory.DATABASE,
                    "Could not load user preferences for filtering, using defaults",
                    context={"error": str(e)}
                )

            # Apply group chat filters
            chat_type = get_chat_type(chat)
            if chat_type in ["group", "supergroup", "gigagroup"]:
                # Check if we should ignore large groups (use user preference if available)
                ignore_large_groups = user_prefs.ignore_large_groups if user_prefs else config.filter.ignore_large_groups
                max_group_size = user_prefs.max_group_size if user_prefs else config.filter.max_group_size

                if ignore_large_groups:
                    # Use cached group sizes (RELIABLE method via iter_dialogs + GetFullChannelRequest)
                    # Cache is refreshed periodically and on startup
                    participant_count = _group_sizes.get(chat.id)

                    if participant_count is not None and participant_count >= max_group_size:
                        chat_name = chat.title if hasattr(chat, 'title') else str(chat.id)
                        log_info(
                            ErrorCategory.FILTERING,
                            f"Filtered large group '{chat_name}'",
                            context={
                                "chat_id": chat.id,
                                "participant_count": participant_count,
                                "threshold": max_group_size
                            }
                        )
                        return
                    elif participant_count is None:
                        # Not in cache yet (new group or cache not populated)
                        # Process the message, will be filtered after next cache refresh
                        logger.debug(f"Group {chat.id} not in cache yet, processing message")

            # Check if we should ignore muted chats (use user preference if available)
            # NOTE: Moved outside group-only check to support muted private chats too
            ignore_muted_chats = user_prefs.ignore_muted_chats if user_prefs else config.filter.ignore_muted_chats

            if ignore_muted_chats:
                # Use cached muted chats list (RELIABLE method via iter_dialogs)
                # Cache is refreshed periodically and on startup
                # For private chats, check sender.id (the OTHER person)
                # For groups, check chat.id
                check_id = sender.id if chat_type == "private" else chat.id

                if check_id in _muted_chats:
                    chat_name = chat.title if hasattr(chat, 'title') else str(check_id)
                    log_info(
                        ErrorCategory.FILTERING,
                        f"Filtered muted/silenced chat '{chat_name}'",
                        context={
                            "chat_id": check_id,
                            "chat_type": chat_type
                        }
                    )
                    return

            # Get sender info
            if isinstance(sender, User):
                user_name = sender.first_name
                if sender.last_name:
                    user_name += f" {sender.last_name}"
                user_id = sender.id
            else:
                user_name = None
                user_id = sender.id if sender else 0

            # Get chat info
            chat_title = None
            if isinstance(chat, (Chat, Channel)):
                chat_title = chat.title
            elif isinstance(chat, User):
                chat_title = f"{chat.first_name} {chat.last_name or ''}".strip()

            # Determine correct chat_id for muting:
            # - For private chats: use sender.id (the OTHER person's ID)
            # - For groups/channels: use chat.id (the group/channel ID)
            # (chat_type already computed earlier on line 710)
            if chat_type == "private":
                actual_chat_id = user_id  # sender.id - the OTHER person
            else:
                actual_chat_id = chat.id  # group/channel ID

            # Save to database
            await save_message(
                telegram_message_id=message.id,
                chat_id=actual_chat_id,  # Correct ID for muting
                chat_title=chat_title,
                chat_type=chat_type,
                user_id=user_id,
                user_name=user_name,
                message_text=message.raw_text,  # Use raw_text for reliability
                timestamp=message.date.replace(tzinfo=None),  # IMPORTANT: Storing as naive UTC!
                client_username=client_username,
            )

        except Exception as e:
            # Try to use chat.id if available, fall back to event.chat_id
            try:
                error_chat_id = chat.id if 'chat' in locals() else event.chat_id
            except:
                error_chat_id = None

            log_error(
                ErrorCategory.MESSAGE_PROCESSING,
                "Error handling incoming message",
                error=e,
                context={"chat_id": error_chat_id},
                include_trace=True
            )
    
    # Start the client
    log_info(ErrorCategory.TELEGRAM_API, "Starting userbot client")

    await client.start(
        phone=config.telegram.phone,
        password=config.telegram.password  # Will prompt if 2FA enabled and password not provided
    )

    # Get client info after connecting
    me = await client.get_me()
    client_username = me.username
    client_user_id = me.id

    log_info(
        ErrorCategory.TELEGRAM_API,
        "Userbot connected successfully",
        context={"username": client_username, "user_id": client_user_id}
    )

    # Cache refreshes are handled by the scheduler (starting after 30-45 seconds)
    # This allows for fast startup without blocking on slow API calls
    log_info(
        ErrorCategory.FILTERING,
        "Filter caches will be populated by scheduler in 30-45 seconds"
    )

    # Keep running - this is handled by the main event loop
    log_info(ErrorCategory.MESSAGE_PROCESSING, "Userbot is now monitoring all incoming messages")


async def stop_userbot() -> None:
    """Stop the userbot client gracefully."""
    global _userbot_client

    if _userbot_client:
        log_info(ErrorCategory.TELEGRAM_API, "Stopping userbot client")
        await _userbot_client.disconnect()
        _userbot_client = None
        log_info(ErrorCategory.TELEGRAM_API, "Userbot client stopped successfully")


async def run_userbot_standalone() -> None:
    """
    Run userbot as standalone (for testing).
    
    Usage:
        python userbot.py
    """
    from database import init_database, create_tables
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Initialize database
    await init_database()
    await create_tables()
    
    # Start userbot
    client = await get_userbot_client()
    await start_userbot()
    
    # Run until disconnected
    await client.run_until_disconnected()


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_userbot_standalone())

