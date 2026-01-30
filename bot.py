"""
Telegram Bot API interface for client communication.
Sends summaries and handles labeling interactions via inline keyboards.
"""

import asyncio
import logging
from typing import Optional

from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)
from telegram.constants import ParseMode
from sqlalchemy.exc import OperationalError

from config import get_config
from database import get_session
from models import Message
from utils import (
    MESSAGE_CARD_PREVIEW_LENGTH,
    escape_markdown,
    format_labeling_confirmation,
    get_priority_emoji,
    truncate_text,
)
from errors import (
    log_error,
    log_warning,
    log_info,
    ErrorCategory,
    DatabaseError,
    TelegramAPIError,
)

logger = logging.getLogger(__name__)

# Global bot application
_bot_app: Optional[Application] = None


def create_priority_keyboard(message_id: int, chat_id: int, chat_title: str) -> InlineKeyboardMarkup:
    """
    Create inline keyboard with priority buttons for a message.

    Layout:
    Row 1: [🔴 High] [🟡 Medium] [🟢 Low]
    Row 2: [🚫 Ignore Chat] or [🔊 Unmute Chat] (if already muted)
    """
    # Check if chat is already muted
    from userbot import get_muted_chats
    muted_chats = get_muted_chats()
    is_muted = chat_id in muted_chats

    keyboard = [
        [
            InlineKeyboardButton(
                "🔴 High",
                callback_data=f"label:{message_id}:high"
            ),
            InlineKeyboardButton(
                "🟡 Medium",
                callback_data=f"label:{message_id}:medium"
            ),
            InlineKeyboardButton(
                "🟢 Low",
                callback_data=f"label:{message_id}:low"
            ),
        ],
        [
            InlineKeyboardButton(
                "🔊 Unmute Chat" if is_muted else "🚫 Ignore Chat",
                callback_data=f"unmute:{message_id}:{chat_id}" if is_muted else f"ignore:{message_id}:{chat_id}"
            ),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


async def handle_label_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle callback when user clicks a priority button.

    Callback data format: "label:{message_id}:{priority}"
    """
    query = update.callback_query
    await query.answer()  # Acknowledge the callback

    try:
        # Validate and parse callback data
        if not query.data:
            log_error(
                ErrorCategory.CALLBACK,
                "Label callback received with no data",
                context={"user_id": update.effective_user.id}
            )
            await query.edit_message_text("❌ Error: Invalid callback data")
            return

        parts = query.data.split(":")

        # Validate format: must have exactly 3 parts
        if len(parts) != 3:
            log_error(
                ErrorCategory.CALLBACK,
                "Invalid label callback format",
                context={
                    "user_id": update.effective_user.id,
                    "callback_data": query.data,
                    "parts_count": len(parts)
                }
            )
            await query.edit_message_text(
                "❌ Error: Invalid callback format\n"
                "Expected format: label:message_id:priority"
            )
            return

        # Validate action type
        if parts[0] != "label":
            log_error(
                ErrorCategory.CALLBACK,
                f"Invalid callback action type",
                context={
                    "user_id": update.effective_user.id,
                    "action": parts[0],
                    "expected": "label"
                }
            )
            await query.edit_message_text(
                f"❌ Error: Unknown action '{parts[0]}'\n"
                "Expected: 'label'"
            )
            return

        # Validate message ID is an integer
        _, message_id_str, label = parts
        try:
            message_id = int(message_id_str)
        except ValueError:
            log_error(
                ErrorCategory.CALLBACK,
                "Invalid message ID format",
                context={
                    "user_id": update.effective_user.id,
                    "message_id_str": message_id_str
                }
            )
            await query.edit_message_text(
                f"❌ Error: Invalid message ID '{message_id_str}'\n"
                "Message ID must be a number"
            )
            return

        # Validate message ID is positive
        if message_id <= 0:
            log_error(
                ErrorCategory.CALLBACK,
                "Message ID must be positive",
                context={
                    "user_id": update.effective_user.id,
                    "message_id": message_id
                }
            )
            await query.edit_message_text(
                f"❌ Error: Invalid message ID {message_id}\n"
                "Message ID must be positive"
            )
            return

        # Validate priority label
        valid_labels = ("high", "medium", "low")
        if label not in valid_labels:
            log_error(
                ErrorCategory.CALLBACK,
                "Invalid priority label",
                context={
                    "user_id": update.effective_user.id,
                    "label": label,
                    "valid_labels": valid_labels
                }
            )
            await query.edit_message_text(
                f"❌ Error: Invalid priority '{label}'\n"
                f"Must be one of: {', '.join(valid_labels)}"
            )
            return
        
        # Update database (with retry for SQLite concurrency)
        from sqlalchemy import select, update as sql_update
        from datetime import datetime

        max_retries = 3
        message_preview = None

        for attempt in range(max_retries):
            try:
                async with get_session() as session:
                    # Get the message
                    result = await session.execute(
                        select(Message).where(Message.id == message_id)
                    )
                    message = result.scalar_one_or_none()

                    if not message:
                        await query.edit_message_text("❌ Message not found in database")
                        return

                    # Update the label
                    await session.execute(
                        sql_update(Message)
                        .where(Message.id == message_id)
                        .values(
                            label=label,
                            labeled_at=datetime.utcnow()
                        )
                    )

                    message_preview = message.message_text
                break  # Success - exit retry loop
            except OperationalError as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.1)  # Wait 100ms before retry
                    log_warning(
                        ErrorCategory.DATABASE,
                        f"Database locked during label update, retrying ({attempt + 2}/{max_retries})",
                        context={"message_id": message_id, "label": label}
                    )
                else:
                    # Final attempt failed
                    log_error(
                        ErrorCategory.DATABASE,
                        f"Failed to update label after {max_retries} attempts",
                        error=e,
                        context={"message_id": message_id, "label": label}
                    )
                    await query.edit_message_text("❌ Database error. Please try again.")
                    return
        
        # Update the message to show confirmation
        emoji = get_priority_emoji(label)
        confirmation = f"{emoji} Marked as *{label.title()}* Priority"
        
        # Edit to remove buttons and show confirmation
        await query.edit_message_text(
            f"{query.message.text}\n\n{confirmation}",
            parse_mode=ParseMode.MARKDOWN,
        )
        
        log_info(
            ErrorCategory.CALLBACK,
            f"Message labeled successfully",
            context={"message_id": message_id, "label": label}
        )

    except Exception as e:
        log_error(
            ErrorCategory.CALLBACK,
            "Failed to process label callback",
            error=e,
            context={
                "user_id": update.effective_user.id,
                "callback_data": query.data if query.data else "None"
            },
            include_trace=True
        )
        await query.edit_message_text(
            f"❌ Error processing label: {str(e)}"
        )


async def handle_ignore_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle callback when user clicks "Ignore Chat" button.
    Shows duration selection options.

    Callback data format: "ignore:{message_id}:{chat_id}"
    """
    query = update.callback_query

    # Try to acknowledge callback (may timeout if user took too long)
    try:
        await query.answer()
    except Exception:
        pass  # Continue regardless

    try:
        # Parse callback data
        parts = query.data.split(":")
        if len(parts) != 3:
            await query.edit_message_text("❌ Error: Invalid callback format")
            return

        message_id = int(parts[1])
        chat_id = int(parts[2])

        # Get chat info from database
        from sqlalchemy import select
        async with get_session() as session:
            result = await session.execute(
                select(Message).where(Message.id == message_id)
            )
            message = result.scalar_one_or_none()

            if not message:
                await query.edit_message_text("❌ Message not found")
                return

            chat_title = message.chat_title or "Unknown Chat"
            chat_type = message.chat_type

        # Show duration selection
        chat_type_display = "group" if chat_type in ["group", "supergroup", "gigagroup"] else "chat"
        chat_title_safe = escape_markdown(chat_title)

        duration_text = f"""
{query.message.text}

🔇 *Mute {chat_type_display}: {chat_title_safe}*

How long should this chat be muted?
        """.strip()

        # Duration options keyboard
        duration_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⏰ 1 hour", callback_data=f"mute_1h:{message_id}:{chat_id}"),
                InlineKeyboardButton("⏰ 8 hours", callback_data=f"mute_8h:{message_id}:{chat_id}"),
            ],
            [
                InlineKeyboardButton("⏰ 1 day", callback_data=f"mute_1d:{message_id}:{chat_id}"),
                InlineKeyboardButton("⏰ 1 week", callback_data=f"mute_1w:{message_id}:{chat_id}"),
            ],
            [
                InlineKeyboardButton("🔇 Forever", callback_data=f"mute_forever:{message_id}:{chat_id}"),
            ],
            [
                InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_mute:{message_id}"),
            ]
        ])

        await query.edit_message_text(
            duration_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=duration_keyboard
        )

    except Exception as e:
        log_error(
            ErrorCategory.CALLBACK,
            "Failed to show ignore duration selector",
            error=e,
            include_trace=True
        )
        await query.edit_message_text(f"❌ Error: {str(e)}")


async def handle_mute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle mute action with specific duration.

    Callback data format: "mute_{duration}:{message_id}:{chat_id}"
    where duration is: 1h, 8h, 1d, 1w, forever
    """
    query = update.callback_query

    # Try to acknowledge callback (may timeout if user took too long)
    try:
        await query.answer()
    except Exception:
        pass  # Continue regardless - we can still edit the message

    try:
        # Parse callback data
        parts = query.data.split(":")
        if len(parts) != 3:
            await query.edit_message_text("❌ Error: Invalid callback format")
            return

        action = parts[0]  # mute_1h, mute_8h, mute_1d, mute_1w, mute_forever
        message_id = int(parts[1])
        chat_id = int(parts[2])

        # Parse duration from action
        from datetime import datetime, timedelta

        duration_map = {
            "mute_1h": (timedelta(hours=1), "1 hour"),
            "mute_8h": (timedelta(hours=8), "8 hours"),
            "mute_1d": (timedelta(days=1), "1 day"),
            "mute_1w": (timedelta(weeks=1), "1 week"),
            "mute_forever": (None, "forever")
        }

        if action not in duration_map:
            await query.edit_message_text("❌ Error: Unknown duration")
            return

        duration_timedelta, duration_display = duration_map[action]

        # Get chat info from database
        from sqlalchemy import select
        async with get_session() as session:
            result = await session.execute(
                select(Message).where(Message.id == message_id)
            )
            message = result.scalar_one_or_none()

            if not message:
                await query.edit_message_text("❌ Message not found")
                return

            chat_title = message.chat_title or "Unknown Chat"
            chat_type = message.chat_type

        # Mute the chat in Telegram using Telethon
        from userbot import get_userbot_client, refresh_muted_chats
        from telethon.tl.functions.account import UpdateNotifySettingsRequest
        from telethon.tl.types import InputNotifyPeer, InputPeerNotifySettings

        try:
            client = await get_userbot_client()

            log_info(
                ErrorCategory.CALLBACK,
                f"Starting mute operation",
                context={
                    "chat_id": chat_id,
                    "chat_title": chat_title,
                    "duration": duration_display
                }
            )

            # Get input entity and wrap it in InputNotifyPeer
            input_peer = await client.get_input_entity(chat_id)
            notify_peer = InputNotifyPeer(peer=input_peer)

            # Calculate mute_until as Unix timestamp (integer)
            # Telegram API expects integer timestamps, not datetime objects
            if duration_timedelta is None:
                # Mute forever - use max timestamp (year 2038)
                mute_until = int(datetime(2038, 1, 1).timestamp())
            else:
                mute_until = int((datetime.now() + duration_timedelta).timestamp())

            log_info(
                ErrorCategory.CALLBACK,
                f"Sending mute request to Telegram",
                context={
                    "chat_id": chat_id,
                    "mute_until_timestamp": mute_until,
                    "mute_until_datetime": datetime.fromtimestamp(mute_until).isoformat(),
                    "duration_display": duration_display,
                    "peer_type": type(input_peer).__name__,
                    "notify_peer_type": type(notify_peer).__name__
                }
            )

            # Mute the chat - MUST wrap peer in InputNotifyPeer!
            result = await client(UpdateNotifySettingsRequest(
                peer=notify_peer,  # FIXED: Must be wrapped in InputNotifyPeer!
                settings=InputPeerNotifySettings(
                    mute_until=mute_until,  # Integer Unix timestamp
                    silent=True,
                    show_previews=False
                )
            ))

            log_info(
                ErrorCategory.CALLBACK,
                f"Telegram API returned",
                context={
                    "chat_id": chat_id,
                    "result": str(result),
                    "result_type": type(result).__name__
                }
            )

            # Add to muted chats cache immediately (optimistic update)
            # This ensures instant filtering without waiting for scheduled refresh
            from userbot import add_muted_chat, get_muted_chats
            muted_before = len(get_muted_chats())
            add_muted_chat(chat_id)
            muted_after = len(get_muted_chats())

            log_info(
                ErrorCategory.CALLBACK,
                f"Updated muted cache (optimistic)",
                context={
                    "chat_id": chat_id,
                    "muted_count_before": muted_before,
                    "muted_count_after": muted_after,
                    "increased": muted_after > muted_before
                }
            )

            # NOTE: Don't refresh immediately - Telegram API takes ~30 seconds to propagate
            # The scheduled refresh (every 30-45s) will sync it eventually

            log_info(
                ErrorCategory.CALLBACK,
                f"Chat muted successfully",
                context={
                    "chat_id": chat_id,
                    "chat_title": chat_title,
                    "duration": duration_display
                }
            )

        except Exception as e:
            log_error(
                ErrorCategory.TELEGRAM_API,
                "Failed to mute chat",
                error=e,
                include_trace=True
            )
            await query.edit_message_text(f"❌ Error: Could not mute chat: {str(e)}")
            return

        # Show confirmation
        chat_type_display = "group" if chat_type in ["group", "supergroup", "gigagroup"] else "chat"
        chat_title_safe = escape_markdown(chat_title)

        confirmation_text = f"""
{query.message.text.split('🔇')[0].strip()}

✅ *Chat Muted*
🔇 {chat_type_display.title()}: *{chat_title_safe}*
⏰ Duration: *{duration_display}*

Future messages will be filtered automatically.
        """.strip()

        # Add unmute button
        unmute_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ Unmute Now", callback_data=f"unmute:{message_id}:{chat_id}")]
        ])

        try:
            await query.edit_message_text(
                confirmation_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=unmute_keyboard
            )
        except Exception as e:
            # If message hasn't changed (user clicked mute multiple times), just ignore
            if "Message is not modified" in str(e):
                pass
            else:
                raise

    except Exception as e:
        log_error(
            ErrorCategory.CALLBACK,
            "Failed to process mute callback",
            error=e,
            include_trace=True
        )
        await query.edit_message_text(f"❌ Error: {str(e)}")


async def handle_unmute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle unmute action.

    Callback data format: "unmute:{message_id}:{chat_id}"
    """
    query = update.callback_query

    # Try to acknowledge callback (may timeout if user took too long)
    try:
        await query.answer()
    except Exception:
        pass  # Continue regardless

    try:
        # Parse callback data
        parts = query.data.split(":")
        if len(parts) != 3:
            await query.edit_message_text("❌ Error: Invalid callback format")
            return

        message_id = int(parts[1])
        chat_id = int(parts[2])

        # Get chat info from database
        from sqlalchemy import select
        async with get_session() as session:
            result = await session.execute(
                select(Message).where(Message.id == message_id)
            )
            message = result.scalar_one_or_none()

            if not message:
                await query.edit_message_text("❌ Message not found")
                return

            chat_title = message.chat_title or "Unknown Chat"

        # Unmute the chat in Telegram using Telethon
        from userbot import get_userbot_client, refresh_muted_chats
        from telethon.tl.functions.account import UpdateNotifySettingsRequest
        from telethon.tl.types import InputNotifyPeer, InputPeerNotifySettings

        try:
            client = await get_userbot_client()

            # Get input entity and wrap it in InputNotifyPeer
            input_peer = await client.get_input_entity(chat_id)
            notify_peer = InputNotifyPeer(peer=input_peer)

            # Unmute (mute_until=0)
            await client(UpdateNotifySettingsRequest(
                peer=notify_peer,  # FIXED: Must be wrapped in InputNotifyPeer!
                settings=InputPeerNotifySettings(
                    mute_until=0,  # Unmute
                    silent=False,
                    show_previews=True
                )
            ))

            # Remove from muted chats cache immediately (optimistic update)
            from userbot import remove_muted_chat, get_muted_chats
            muted_before = len(get_muted_chats())
            remove_muted_chat(chat_id)
            muted_after = len(get_muted_chats())

            # NOTE: Don't refresh immediately - Telegram API takes ~30 seconds to propagate
            # The scheduled refresh (every 30-45s) will sync it eventually

            log_info(
                ErrorCategory.CALLBACK,
                f"Chat unmuted successfully (optimistic)",
                context={
                    "chat_id": chat_id,
                    "chat_title": chat_title,
                    "muted_count_before": muted_before,
                    "muted_count_after": muted_after,
                    "decreased": muted_after < muted_before
                }
            )

        except Exception as e:
            log_error(
                ErrorCategory.TELEGRAM_API,
                "Failed to unmute chat",
                error=e,
                include_trace=True
            )
            await query.edit_message_text(f"❌ Error: Could not unmute chat: {str(e)}")
            return

        # Show confirmation (remove buttons)
        chat_title_safe = escape_markdown(chat_title)
        confirmation_text = f"""
{query.message.text.split('🔇')[0].strip()}

↩️ *Chat Unmuted*
✅ Chat *{chat_title_safe}* has been unmuted.

Messages from this chat will now appear in summaries again.
        """.strip()

        try:
            await query.edit_message_text(
                confirmation_text,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            # If message hasn't changed (user clicked unmute multiple times), just ignore
            if "Message is not modified" in str(e):
                pass
            else:
                raise

    except Exception as e:
        log_error(
            ErrorCategory.CALLBACK,
            "Failed to process unmute callback",
            error=e,
            include_trace=True
        )
        await query.edit_message_text(f"❌ Error: {str(e)}")


async def handle_cancel_mute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle cancel action - restore original message.

    Callback data format: "cancel_mute:{message_id}"
    """
    query = update.callback_query
    await query.answer("Cancelled")

    try:
        # Just restore the original message with priority buttons
        parts = query.data.split(":")
        message_id = int(parts[1])

        # Get message info
        from sqlalchemy import select
        async with get_session() as session:
            result = await session.execute(
                select(Message).where(Message.id == message_id)
            )
            message = result.scalar_one_or_none()

            if message:
                # Restore original keyboard
                keyboard = create_priority_keyboard(message_id, message.chat_id, message.chat_title or "Unknown")

                # Get original message text (before duration selector)
                original_text = query.message.text.split('\n\n🔇')[0]

                await query.edit_message_text(
                    original_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard
                )
            else:
                await query.edit_message_text("❌ Message not found")

    except Exception as e:
        log_error(
            ErrorCategory.CALLBACK,
            "Failed to cancel mute",
            error=e,
            include_trace=True
        )


async def handle_start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    config = get_config()

    # Only respond to the authorized client
    if update.effective_user.id != config.telegram.client_user_id:
        await update.message.reply_text(
            "⛔ Sorry, this bot is private and only responds to its owner."
        )
        return

    welcome_message = """
🤖 *Telegram Secretary Bot*

I'm your personal message assistant! Here's what I do:

📥 *Capture* all your incoming messages
🚨 *Warn* you immediately about important messages
📊 *Analyze* and prioritize them with AI
📝 *Summarize* messages every few hours
🏷️ *Learn* from your classifications to improve over time

*Quick Setup:*
1️⃣ Use `/profile` to describe what you use Telegram for
2️⃣ Use `/config` to adjust alert thresholds
3️⃣ Start receiving smart, personalized summaries!

*How it works:*
• I'll send you real-time alerts for high-priority messages
• You can classify each message as: 🔴 High, 🟡 Medium, or 🟢 Low
• I'll send periodic summaries every {hours} hours
• Your profile and classifications help me learn what's important to YOU

📖 Type `/help` to see all available commands and detailed instructions.
    """.format(hours=config.scheduler.summary_interval_hours)

    await update.message.reply_text(
        welcome_message,
        parse_mode=ParseMode.MARKDOWN
    )


async def handle_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command - show detailed instructions."""
    config = get_config()

    # Only respond to the authorized client
    if update.effective_user.id != config.telegram.client_user_id:
        return

    help_message = """
📖 *HELP*

*⚡ QUICK ACTIONS*
/summary - Get a summary now
/stats - View message statistics
/datacheck - Check data quality

*⚙️ CONFIGURATION*
/profile <text> - Set your Telegram usage context for AI
/config - Adjust thresholds and filters interactively
/health - System status and current settings

*🏷️ LABELING GUIDE*
🔴 High - Urgent, needs immediate action
🟡 Medium - Important but not urgent
🟢 Low - Casual, can wait

*💡 HOW IT WORKS*
1. Bot captures ALL messages
2. AI scores each 0-10 based on your profile
3. Alerts sent for score ≥ {threshold}
4. Summaries every {hours}hrs
5. Your labels train future ML model

*✨ TIPS*
• Set /profile first for better AI
• Label 30%+ messages for quality data
• Use /config to reduce noise
• Use /health to check current settings
    """.format(
        hours=config.scheduler.summary_interval_hours,
        threshold=config.scheduler.warning_threshold_score
    )

    await update.message.reply_text(
        help_message,
        parse_mode=ParseMode.MARKDOWN
    )


async def handle_summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /summary command - trigger manual summary."""
    config = get_config()
    
    # Only respond to the authorized client
    if update.effective_user.id != config.telegram.client_user_id:
        return
    
    await update.message.reply_text("⏳ Generating summary...")
    
    # Import here to avoid circular imports
    from scheduler import generate_and_send_summary
    await generate_and_send_summary()


async def handle_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stats command - show message statistics."""
    config = get_config()
    
    # Only respond to the authorized client
    if update.effective_user.id != config.telegram.client_user_id:
        return
    
    from sqlalchemy import func, select
    from datetime import datetime, timedelta
    
    try:
        async with get_session() as session:
            # Total messages
            total_result = await session.execute(
                select(func.count(Message.id))
            )
            total = total_result.scalar()
            
            # Messages in last 24 hours
            day_ago = datetime.utcnow() - timedelta(hours=24)
            recent_result = await session.execute(
                select(func.count(Message.id))
                .where(Message.timestamp >= day_ago)
            )
            recent = recent_result.scalar()
            
            # Labeled messages
            labeled_result = await session.execute(
                select(func.count(Message.id))
                .where(Message.label.isnot(None))
            )
            labeled = labeled_result.scalar()
            
            # Label breakdown
            high_count = (await session.execute(
                select(func.count(Message.id)).where(Message.label == "high")
            )).scalar()
            
            medium_count = (await session.execute(
                select(func.count(Message.id)).where(Message.label == "medium")
            )).scalar()
            
            low_count = (await session.execute(
                select(func.count(Message.id)).where(Message.label == "low")
            )).scalar()
        
        stats_message = f"""
📊 *Message Statistics*

*Total Messages:* {total}
*Last 24 Hours:* {recent}
*Labeled:* {labeled}

*Label Breakdown:*
🔴 High: {high_count}
🟡 Medium: {medium_count}
🟢 Low: {low_count}
⚪ Unlabeled: {total - labeled}
        """
        
        await update.message.reply_text(
            stats_message,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"Error generating stats: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ Error generating statistics: {str(e)}"
        )


async def handle_datacheck_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /datacheck command - validate data collection quality."""
    config = get_config()

    # Only respond to the authorized client
    if update.effective_user.id != config.telegram.client_user_id:
        return

    from sqlalchemy import func, select
    from datetime import datetime, timedelta

    await update.message.reply_text("🔍 Running data validation checks...")

    try:
        validation_report = []
        validation_report.append("📊 *DATA VALIDATION REPORT*\n")

        async with get_session() as session:
            # 1. Total message count
            total_result = await session.execute(select(func.count(Message.id)))
            total_messages = total_result.scalar() or 0
            validation_report.append(f"✅ *Total Messages:* {total_messages}")

            if total_messages == 0:
                await update.message.reply_text(
                    "⚠️ No messages in database!\n\nBot may not be capturing messages."
                )
                return

            # 2. Labeling status (MOST IMPORTANT)
            labeled_result = await session.execute(
                select(func.count(Message.id)).where(Message.label.isnot(None))
            )
            labeled_count = labeled_result.scalar() or 0
            label_pct = (labeled_count / total_messages * 100) if total_messages > 0 else 0

            validation_report.append(f"\n🏷️ *LABELING (Training Data):*")
            validation_report.append(f"Labeled: {labeled_count}/{total_messages} ({label_pct:.1f}%)")

            # Label distribution
            high_c = (await session.execute(select(func.count(Message.id)).where(Message.label == "high"))).scalar() or 0
            med_c = (await session.execute(select(func.count(Message.id)).where(Message.label == "medium"))).scalar() or 0
            low_c = (await session.execute(select(func.count(Message.id)).where(Message.label == "low"))).scalar() or 0

            validation_report.append(f"🔴 High: {high_c} | 🟡 Medium: {med_c} | 🟢 Low: {low_c}")

            if label_pct < 20 and total_messages > 50:
                validation_report.append(f"⚠️ *LOW LABELING RATE!* Only {label_pct:.1f}% labeled")

            # 3. Data integrity checks
            null_score = (await session.execute(
                select(func.count(Message.id)).where(Message.priority_score.is_(None))
            )).scalar() or 0
            null_text = (await session.execute(
                select(func.count(Message.id)).where(Message.message_text.is_(None))
            )).scalar() or 0

            validation_report.append(f"\n🔍 *DATA INTEGRITY:*")
            if null_score == 0 and null_text == 0:
                validation_report.append("✅ No missing critical fields")
            else:
                if null_score > 0:
                    validation_report.append(f"⚠️ Missing priority_score: {null_score}")
                if null_text > 0:
                    validation_report.append(f"⚠️ Missing message_text: {null_text}")

            # 4. AI score distribution
            score_low = (await session.execute(
                select(func.count(Message.id)).where(Message.priority_score.between(0, 3))
            )).scalar() or 0
            score_mid = (await session.execute(
                select(func.count(Message.id)).where(Message.priority_score.between(4, 6))
            )).scalar() or 0
            score_high = (await session.execute(
                select(func.count(Message.id)).where(Message.priority_score >= 7)
            )).scalar() or 0

            validation_report.append(f"\n📈 *AI SCORES:*")
            validation_report.append(f"0-3: {score_low} | 4-6: {score_mid} | 7-10: {score_high}")

            # 5. User profile
            prefs = await get_or_create_user_preferences(config.telegram.client_user_id)
            validation_report.append(f"\n👤 *USER PROFILE:*")
            if prefs.user_context:
                preview = prefs.user_context[:40] + "..." if len(prefs.user_context) > 40 else prefs.user_context
                validation_report.append(f'✅ Set: "{preview}"')
            else:
                validation_report.append("❌ Not set - use /profile")

            # 6. Quality score
            quality = 0
            if total_messages > 0:
                quality += 25
            quality += min(40, int(label_pct * 0.4))  # 40 points max for labeling
            if null_score == 0 and null_text == 0:
                quality += 20
            if prefs.user_context:
                quality += 15

            validation_report.append(f"\n🎯 *QUALITY SCORE:* {quality}/100")

            if quality >= 75:
                validation_report.append("✅ Excellent!")
            elif quality >= 50:
                validation_report.append("✅ Good")
            elif quality >= 30:
                validation_report.append("⚠️ Needs improvement")
            else:
                validation_report.append("❌ Action required")

            # 7. Recommendations
            validation_report.append(f"\n💡 *NEXT STEPS:*")
            if label_pct < 30:
                validation_report.append(f"• Label more messages (target: 30%+)")
            if not prefs.user_context:
                validation_report.append("• Set profile with /profile")
            if total_messages < 100:
                validation_report.append(f"• Keep collecting ({total_messages}/100)")
            if null_score > 0 or null_text > 0:
                validation_report.append("• Fix data integrity issues")

        report_text = "\n".join(validation_report)
        await update.message.reply_text(report_text, parse_mode=ParseMode.MARKDOWN)

        logger.info(f"Data validation: quality={quality}/100, labeled={label_pct:.1f}%")

    except Exception as e:
        logger.error(f"Data validation error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def handle_health_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /health command - show system component health status."""
    config = get_config()

    # Only respond to the authorized client
    if update.effective_user.id != config.telegram.client_user_id:
        return

    from datetime import datetime
    from scheduler import get_scheduler
    from userbot import get_userbot_client
    from database import _engine

    status_lines = []
    status_lines.append("🏥 *System Health Check*\n")

    # Check userbot status
    try:
        userbot_client = await get_userbot_client()
        if userbot_client and userbot_client.is_connected():
            status_lines.append("✅ *Userbot:* Connected")
        else:
            status_lines.append("❌ *Userbot:* Disconnected")
    except Exception as e:
        status_lines.append(f"❌ *Userbot:* Error - {str(e)[:50]}")

    # Check scheduler status
    scheduler = get_scheduler()
    if scheduler and scheduler.running:
        status_lines.append("✅ *Scheduler:* Running")

        # Get next summary time
        job = scheduler.get_job("summary_job")
        if job and job.next_run_time:
            next_run = job.next_run_time.strftime("%H:%M %d/%m")
            status_lines.append(f"   └ Next summary: {next_run}")
    else:
        status_lines.append("❌ *Scheduler:* Not running")

    # Check Ollama availability (if enabled)
    if config.ai.enabled:
        try:
            import ollama
            import asyncio

            def check_ollama():
                client = ollama.Client(host=config.ai.ollama_host)
                # Try to list models as a health check
                client.list()
                return True

            loop = asyncio.get_event_loop()
            await asyncio.wait_for(
                loop.run_in_executor(None, check_ollama),
                timeout=2.0
            )
            status_lines.append(f"✅ *Ollama:* Available ({config.ai.model})")
        except ImportError:
            status_lines.append("⚠️ *Ollama:* Not installed")
        except asyncio.TimeoutError:
            status_lines.append("❌ *Ollama:* Timeout")
        except Exception as e:
            status_lines.append(f"❌ *Ollama:* Unavailable")
    else:
        status_lines.append("⚪ *Ollama:* Disabled")

    # Check database
    if _engine:
        db_type = "SQLite" if "sqlite" in config.database.url.lower() else "PostgreSQL"
        status_lines.append(f"✅ *Database:* {db_type} connected")
    else:
        status_lines.append("❌ *Database:* Not initialized")

    status_lines.append("\n💡 Use /config to view and change settings")

    health_message = "\n".join(status_lines)

    await update.message.reply_text(
        health_message,
        parse_mode=ParseMode.MARKDOWN
    )


async def get_or_create_user_preferences(user_id: int):
    """Get user preferences or create default ones using env vars."""
    from sqlalchemy import select
    from models import UserPreferences

    async with get_session() as session:
        result = await session.execute(
            select(UserPreferences).where(UserPreferences.user_id == user_id)
        )
        prefs = result.scalar_one_or_none()

        if not prefs:
            # Create default preferences from environment variables
            config = get_config()
            prefs = UserPreferences(
                user_id=user_id,
                min_priority_score=config.scheduler.min_priority_score,
                warning_threshold_score=config.scheduler.warning_threshold_score,
                ignore_large_groups=config.filter.ignore_large_groups,
                max_group_size=config.filter.max_group_size,
                ignore_muted_chats=config.filter.ignore_muted_chats,
            )
            session.add(prefs)
            await session.flush()

        return prefs


async def handle_profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /profile command - set user context for AI personalization."""
    config = get_config()

    # Only respond to the authorized client
    if update.effective_user.id != config.telegram.client_user_id:
        return

    # Check if user provided context
    if not context.args or len(context.args) == 0:
        # Show current profile
        prefs = await get_or_create_user_preferences(config.telegram.client_user_id)

        if prefs.user_context:
            profile_text = f"""
📝 *Your Current Profile:*

"{prefs.user_context}"

*This helps the AI understand what's important to you.*

To update your profile, use:
`/profile <your description>`

Example:
`/profile I use Telegram mainly for work coordination with my team, client communication, and some personal chats with family`
            """
        else:
            profile_text = """
📝 *Set Your Telegram Usage Profile*

Help the AI learn what's important to you!

Describe what you use Telegram for. This helps the AI score messages more accurately based on YOUR priorities.

*Usage:*
`/profile <your description>`

*Examples:*
• `/profile I use Telegram mainly for work - project updates, client meetings, team coordination`
• `/profile Personal use only - family group chats, friends, and hobby communities`
• `/profile Mix of work and personal - startup team communication and social groups`
• `/profile Freelance work - client projects, payment discussions, and deliverable coordination`

The more specific you are, the better the AI can personalize priority scoring!
            """

        await update.message.reply_text(
            profile_text,
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # User provided context - save it
    user_context = " ".join(context.args)

    from sqlalchemy import update as sql_update
    from models import UserPreferences

    async with get_session() as session:
        await session.execute(
            sql_update(UserPreferences)
            .where(UserPreferences.user_id == config.telegram.client_user_id)
            .values(user_context=user_context)
        )

    await update.message.reply_text(
        f"""
✅ *Profile Updated!*

Your Telegram usage profile:
"{user_context}"

The AI will now use this context to better understand which messages are important to YOU.

You can update your profile anytime with `/profile <new description>`
        """,
        parse_mode=ParseMode.MARKDOWN
    )

    logger.info(f"User profile set: {user_context[:100]}...")


def build_config_message_and_keyboard(prefs, config):
    """Build the config display message and keyboard from current preferences."""
    config_text = f"""
⚙️ *Interactive Configuration*

Tap any button below to change settings instantly:

*Priority Settings:*
🚨 Warning Threshold: `{prefs.warning_threshold_score}`/10
   _Real-time alerts for scores ≥ this_

📊 Min Priority Score: `{prefs.min_priority_score}`/10
   _Minimum score to include in summaries_

*Filter Settings:*
🏢 Ignore Large Groups: `{'✅ ON' if prefs.ignore_large_groups else '❌ OFF'}`
   _Skip groups with >{config.filter.max_group_size} members_

🔇 Ignore Muted Chats: `{'✅ ON' if prefs.ignore_muted_chats else '❌ OFF'}`
   _Skip chats you've muted in Telegram_

━━━━━━━━━━━━━━━━━━━━
💡 For advanced settings (summary interval, max messages, etc.), use environment variables and restart the bot.
    """

    # Create inline keyboard with only editable settings
    keyboard = [
        [
            InlineKeyboardButton("🚨 Warning Threshold", callback_data="config:warning_threshold"),
            InlineKeyboardButton("📊 Min Priority", callback_data="config:min_priority"),
        ],
        [
            InlineKeyboardButton(
                f"🏢 Large Groups: {'ON' if prefs.ignore_large_groups else 'OFF'}",
                callback_data="config:toggle_large_groups"
            ),
        ],
        [
            InlineKeyboardButton(
                f"🔇 Muted Chats: {'ON' if prefs.ignore_muted_chats else 'OFF'}",
                callback_data="config:toggle_muted"
            ),
        ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    return config_text, reply_markup


async def handle_configure_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /config command - interactive settings editor."""
    config = get_config()

    # Only respond to the authorized client
    if update.effective_user.id != config.telegram.client_user_id:
        return

    # Get current preferences
    prefs = await get_or_create_user_preferences(config.telegram.client_user_id)

    config_text, reply_markup = build_config_message_and_keyboard(prefs, config)

    await update.message.reply_text(
        config_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )


async def handle_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle configuration button callbacks."""
    query = update.callback_query
    await query.answer()

    config = get_config()

    try:
        # Validate callback data format (accept both "config:" and "set_" prefixes)
        if not query.data:
            log_error(
                ErrorCategory.CALLBACK,
                "Config callback received with no data",
                context={"user_id": update.effective_user.id}
            )
            await query.edit_message_text("❌ Invalid configuration action (no data)")
            return

        if not (query.data.startswith("config:") or query.data.startswith("set_")):
            log_error(
                ErrorCategory.CALLBACK,
                f"Invalid callback prefix",
                context={
                    "user_id": update.effective_user.id,
                    "callback_data": query.data
                }
            )
            await query.edit_message_text(f"❌ Invalid configuration action: {query.data}")
            return

        # Keep the full callback data for proper parsing
        callback_data = query.data

        # Extract action (everything after first colon)
        if ":" in callback_data:
            action = callback_data.split(":", 1)[1]
        else:
            action = callback_data

        log_info(ErrorCategory.CALLBACK, f"Processing config callback: {callback_data}")

        # Get current preferences
        prefs = await get_or_create_user_preferences(config.telegram.client_user_id)

        # Handle toggle actions
        if action == "toggle_large_groups":
            from sqlalchemy import update as sql_update
            from models import UserPreferences

            new_value = not prefs.ignore_large_groups

            async with get_session() as session:
                await session.execute(
                    sql_update(UserPreferences)
                    .where(UserPreferences.user_id == config.telegram.client_user_id)
                    .values(ignore_large_groups=new_value)
                )

            # Re-fetch updated preferences and show config page
            updated_prefs = await get_or_create_user_preferences(config.telegram.client_user_id)
            config_text, reply_markup = build_config_message_and_keyboard(updated_prefs, config)

            await query.edit_message_text(
                config_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            return

        if action == "toggle_muted":
            from sqlalchemy import update as sql_update
            from models import UserPreferences

            new_value = not prefs.ignore_muted_chats

            async with get_session() as session:
                await session.execute(
                    sql_update(UserPreferences)
                    .where(UserPreferences.user_id == config.telegram.client_user_id)
                    .values(ignore_muted_chats=new_value)
                )

            # Re-fetch updated preferences and show config page
            updated_prefs = await get_or_create_user_preferences(config.telegram.client_user_id)
            config_text, reply_markup = build_config_message_and_keyboard(updated_prefs, config)

            await query.edit_message_text(
                config_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            return

        # Handle numeric input actions - show options
        if action == "warning_threshold":
            keyboard = []
            for i in range(0, 11, 2):
                row = []
                row.append(InlineKeyboardButton(str(i), callback_data=f"set_warning:{i}"))
                if i + 1 <= 10:  # Only add if within range 0-10
                    row.append(InlineKeyboardButton(str(i+1), callback_data=f"set_warning:{i+1}"))
                keyboard.append(row)

            # Add back button
            keyboard.append([InlineKeyboardButton("« Back to Config", callback_data="config:back")])

            await query.edit_message_text(
                f"🚨 *Set Warning Threshold*\n\n"
                f"Current: {prefs.warning_threshold_score}/10\n\n"
                f"Choose the minimum score for real-time alerts:\n"
                f"• 0-4 = You'll get MANY alerts\n"
                f"• 5-7 = Moderate alerts\n"
                f"• 8-10 = Only urgent messages",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        if action == "min_priority":
            keyboard = []
            for i in range(0, 11, 2):
                row = []
                row.append(InlineKeyboardButton(str(i), callback_data=f"set_min:{i}"))
                if i + 1 <= 10:  # Only add if within range 0-10
                    row.append(InlineKeyboardButton(str(i+1), callback_data=f"set_min:{i+1}"))
                keyboard.append(row)

            # Add back button
            keyboard.append([InlineKeyboardButton("« Back to Config", callback_data="config:back")])

            await query.edit_message_text(
                f"📊 *Set Minimum Priority Score*\n\n"
                f"Current: {prefs.min_priority_score}/10\n\n"
                f"Choose minimum score for summaries:\n"
                f"• 0-2 = Include almost everything\n"
                f"• 3-5 = Skip casual chat, include questions\n"
                f"• 6-10 = Only important/urgent messages",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # Handle back button
        if action == "back":
            # Re-fetch current preferences and show config page
            updated_prefs = await get_or_create_user_preferences(config.telegram.client_user_id)
            config_text, reply_markup = build_config_message_and_keyboard(updated_prefs, config)

            await query.edit_message_text(
                config_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            return

        if callback_data.startswith("set_warning:"):
            value = int(callback_data.split(":")[1])
            from sqlalchemy import update as sql_update
            from models import UserPreferences

            async with get_session() as session:
                await session.execute(
                    sql_update(UserPreferences)
                    .where(UserPreferences.user_id == config.telegram.client_user_id)
                    .values(warning_threshold_score=value)
                )

            # Re-fetch updated preferences and show config page
            updated_prefs = await get_or_create_user_preferences(config.telegram.client_user_id)
            config_text, reply_markup = build_config_message_and_keyboard(updated_prefs, config)

            await query.edit_message_text(
                config_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            return

        if callback_data.startswith("set_min:"):
            value = int(callback_data.split(":")[1])
            from sqlalchemy import update as sql_update
            from models import UserPreferences

            async with get_session() as session:
                await session.execute(
                    sql_update(UserPreferences)
                    .where(UserPreferences.user_id == config.telegram.client_user_id)
                    .values(min_priority_score=value)
                )

            # Re-fetch updated preferences and show config page
            updated_prefs = await get_or_create_user_preferences(config.telegram.client_user_id)
            config_text, reply_markup = build_config_message_and_keyboard(updated_prefs, config)

            await query.edit_message_text(
                config_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            return

        # If we get here, the action wasn't handled
        log_warning(
            ErrorCategory.CALLBACK,
            f"Unhandled config action",
            context={"action": action, "user_id": config.telegram.client_user_id}
        )
        await query.edit_message_text(
            f"⚠️ Setting '{action}' is not available for interactive configuration.\n\n"
            "Use /config to see available settings or check .env for advanced options."
        )

    except Exception as e:
        log_error(
            ErrorCategory.CALLBACK,
            "Failed to handle config callback",
            error=e,
            context={
                "user_id": update.effective_user.id,
                "callback_data": query.data if query.data else "None"
            },
            include_trace=True
        )
        await query.edit_message_text(f"❌ Error updating configuration: {str(e)}")


async def send_message_card(
    bot: Bot,
    chat_id: int,
    message: Message,
    index: int,
) -> None:
    """
    Send a single message card with inline keyboard.
    
    This is sent as a separate message so each has its own buttons.
    """
    # Determine chat type display
    if message.chat_type == "private":
        chat_info = "💬 Private chat"
    else:
        chat_title_safe = escape_markdown(message.chat_title or 'Unknown Group')
        chat_info = f"💬 {chat_title_safe}"

    # Escape all user-provided text to prevent Markdown parsing errors
    sender = escape_markdown(message.user_name or f"User {message.user_id}")
    text_preview = escape_markdown(truncate_text(message.message_text, MESSAGE_CARD_PREVIEW_LENGTH))

    # Topic summary from AI (if available)
    if message.topic_summary:
        topic_safe = escape_markdown(message.topic_summary)
        topic_line = f"\n🏷️ Topic: {topic_safe}"
    else:
        topic_line = ""

    # Build indicators
    indicators = []
    if message.has_mention:
        indicators.append("📢 Mention")
    if message.is_question:
        indicators.append("❓ Question")

    indicator_line = f"\n📌 {' | '.join(indicators)}" if indicators else ""

    # Score indicator
    score_line = f"📈 Score: {message.priority_score}"

    card_text = f"""
*{index}.* 👤 *{sender}*
{chat_info}{topic_line}
📝 "{text_preview}"
{indicator_line}
{score_line}
⏰ {message.timestamp.strftime('%H:%M - %d/%m')}
    """.strip()

    keyboard = create_priority_keyboard(message.id, message.chat_id, message.chat_title or "Unknown")
    
    await bot.send_message(
        chat_id=chat_id,
        text=card_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )


async def send_summary(
    messages: list[Message],
    total_messages: int,
    total_chats: int,
    time_range_hours: int,
) -> None:
    """
    Send a complete summary to the client.
    
    Sends header, then each message as separate card with buttons.
    """
    config = get_config()
    bot = _bot_app.bot
    chat_id = config.telegram.client_user_id
    
    # Send header
    header = f"""
📊 *Summary of last {time_range_hours} hours*

You received *{total_messages}* messages in *{total_chats}* conversations.
Top *{len(messages)}* messages by priority score:

━━━━━━━━━━━━━━━━━━━━
    """.strip()
    
    await bot.send_message(
        chat_id=chat_id,
        text=header,
        parse_mode=ParseMode.MARKDOWN,
    )
    
    # Send each message as a card
    for i, message in enumerate(messages, 1):
        await send_message_card(bot, chat_id, message, i)
    
    # Send footer
    footer = f"""
━━━━━━━━━━━━━━━━━━━━

🏷️ *Label Guide:*
🔴 High - Needs immediate attention
🟡 Medium - Moderate importance
🟢 Low - Can wait or ignore

Tap the buttons above to classify each message.
    """.strip()
    
    await bot.send_message(
        chat_id=chat_id,
        text=footer,
        parse_mode=ParseMode.MARKDOWN,
    )


async def send_simple_message(text: str) -> None:
    """Send a simple text message to the client."""
    config = get_config()
    
    if _bot_app:
        await _bot_app.bot.send_message(
            chat_id=config.telegram.client_user_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
        )


def get_bot_app() -> Optional[Application]:
    """Get the bot application instance."""
    return _bot_app


async def check_and_prompt_profile_setup() -> None:
    """Check if user has set up their profile, and prompt if not."""
    try:
        config = get_config()
        prefs = await get_or_create_user_preferences(config.telegram.client_user_id)

        if not prefs.user_context:
            # User hasn't set up their profile yet
            setup_message = """
👋 *Welcome to Telegram Secretary Bot!*

To get the best personalized experience, please tell me about your Telegram usage!

*Why is this important?*
The AI uses your profile to understand YOUR priorities and score messages accordingly.

*Set your profile now:*
Use `/profile <description>`

*Examples:*
• `/profile I use Telegram mainly for work - client coordination and team updates`
• `/profile Personal use - family chats and hobby groups`
• `/profile Freelance work - project discussions and client communication`

You can update this anytime with `/profile` or skip with `/config`
            """

            await send_simple_message(setup_message)
            logger.info("Sent profile setup prompt to user")

    except Exception as e:
        logger.warning(f"Could not send profile setup prompt: {e}")


async def start_bot() -> Application:
    """
    Initialize and start the Telegram bot.

    Returns the Application instance (doesn't block).
    """
    global _bot_app

    config = get_config()

    # Create application
    _bot_app = (
        Application.builder()
        .token(config.telegram.bot_token)
        .build()
    )
    
    # Register handlers
    _bot_app.add_handler(CommandHandler("start", handle_start_command))
    _bot_app.add_handler(CommandHandler("help", handle_help_command))
    _bot_app.add_handler(CommandHandler("summary", handle_summary_command))
    _bot_app.add_handler(CommandHandler("stats", handle_stats_command))
    _bot_app.add_handler(CommandHandler("health", handle_health_command))
    _bot_app.add_handler(CommandHandler("datacheck", handle_datacheck_command))
    _bot_app.add_handler(CommandHandler("profile", handle_profile_command))
    _bot_app.add_handler(CommandHandler("config", handle_configure_command))

    # Register callback handlers - order matters, more specific first
    _bot_app.add_handler(CallbackQueryHandler(handle_config_callback, pattern="^config:"))
    _bot_app.add_handler(CallbackQueryHandler(handle_config_callback, pattern="^set_"))
    _bot_app.add_handler(CallbackQueryHandler(handle_label_callback, pattern="^label:"))

    # Mute/Unmute handlers (ignore chat feature)
    _bot_app.add_handler(CallbackQueryHandler(handle_ignore_callback, pattern="^ignore:"))
    _bot_app.add_handler(CallbackQueryHandler(handle_mute_callback, pattern="^mute_"))
    _bot_app.add_handler(CallbackQueryHandler(handle_unmute_callback, pattern="^unmute:"))
    _bot_app.add_handler(CallbackQueryHandler(handle_cancel_mute_callback, pattern="^cancel_mute:"))

    # Initialize the application
    await _bot_app.initialize()
    await _bot_app.start()
    
    # Start polling in background
    await _bot_app.updater.start_polling(drop_pending_updates=True)

    logger.info("Bot started and polling for updates")

    # Check if user needs to set up their profile
    await check_and_prompt_profile_setup()

    return _bot_app


async def stop_bot() -> None:
    """Stop the bot gracefully."""
    global _bot_app
    
    if _bot_app:
        logger.info("Stopping bot...")
        await _bot_app.updater.stop()
        await _bot_app.stop()
        await _bot_app.shutdown()
        _bot_app = None
        logger.info("Bot stopped")


async def run_bot_standalone() -> None:
    """
    Run bot as standalone (for testing).
    
    Usage:
        python bot.py
    """
    from database import init_database, create_tables
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Initialize database
    await init_database()
    await create_tables()
    
    # Start bot
    app = await start_bot()
    
    # Run until stopped
    logger.info("Bot running. Press Ctrl+C to stop.")
    
    try:
        # Keep running
        import asyncio
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await stop_bot()


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_bot_standalone())

