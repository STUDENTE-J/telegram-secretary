#!/usr/bin/env python3
"""
Cleanup script to remove old messages from muted chats and large groups.

This script:
1. Connects to the database
2. Gets the list of muted chats and large groups
3. Deletes messages from those chats
4. Shows statistics about what was deleted

Run this script to clean up historical messages that would now be filtered.
"""

import asyncio
import logging
from datetime import datetime
from typing import Set

from sqlalchemy import delete, select, func

from config import get_config
from database import get_session, init_database
from models import Message
from userbot import get_muted_chats, get_large_group_ids, start_userbot

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def get_message_counts_by_chat(chat_ids: Set[int]) -> dict:
    """
    Get message counts for specific chat IDs.

    Args:
        chat_ids: Set of chat IDs to count

    Returns:
        Dictionary mapping chat_id to message count
    """
    if not chat_ids:
        return {}

    counts = {}
    async with get_session() as session:
        result = await session.execute(
            select(Message.chat_id, func.count(Message.id))
            .where(Message.chat_id.in_(chat_ids))
            .group_by(Message.chat_id)
        )
        counts = dict(result.all())

    return counts


async def delete_messages_from_chats(chat_ids: Set[int], reason: str) -> int:
    """
    Delete all messages from specified chat IDs.

    Args:
        chat_ids: Set of chat IDs to delete messages from
        reason: Reason for deletion (for logging)

    Returns:
        Number of messages deleted
    """
    if not chat_ids:
        return 0

    async with get_session() as session:
        result = await session.execute(
            delete(Message).where(Message.chat_id.in_(chat_ids))
        )
        deleted_count = result.rowcount
        await session.commit()

    logger.info(f"Deleted {deleted_count} messages from {len(chat_ids)} chats ({reason})")
    return deleted_count


async def cleanup_filtered_messages():
    """
    Main cleanup function.
    """
    logger.info("=" * 60)
    logger.info("Starting cleanup of filtered messages")
    logger.info("=" * 60)

    # Initialize database
    await init_database()

    # Get configuration
    config = get_config()

    # Start userbot to populate caches
    logger.info("Starting userbot to load filtering caches...")
    await start_userbot()

    # Wait for caches to populate (may take longer due to flood waits)
    logger.info("Waiting for caches to populate (up to 60 seconds, includes flood waits)...")
    await asyncio.sleep(60)

    # Check if caches are populated
    muted_test = get_muted_chats()
    if len(muted_test) == 0 and config.filter.ignore_muted_chats:
        logger.warning("Muted chats cache is still empty - may need more time")
        logger.info("Waiting additional 30 seconds...")
        await asyncio.sleep(30)

    # Get total message count before cleanup
    async with get_session() as session:
        result = await session.execute(select(func.count(Message.id)))
        total_messages_before = result.scalar()

    logger.info(f"Total messages in database: {total_messages_before}")

    # Get muted chats
    muted_chats = set()
    if config.filter.ignore_muted_chats:
        muted_chats = get_muted_chats()
        logger.info(f"Found {len(muted_chats)} muted chats")
    else:
        logger.info("Muted chat filtering is disabled - skipping")

    # Get large groups
    large_groups = set()
    if config.filter.ignore_large_groups:
        large_groups = get_large_group_ids(config.filter.max_group_size)
        logger.info(f"Found {len(large_groups)} large groups (> {config.filter.max_group_size} members)")
    else:
        logger.info("Large group filtering is disabled - skipping")

    # Combine excluded chats
    excluded_chats = muted_chats | large_groups

    if not excluded_chats:
        logger.warning("No chats to filter - nothing to clean up")
        return

    logger.info(f"Total chats to clean up: {len(excluded_chats)}")

    # Get message counts before deletion
    logger.info("Analyzing messages to be deleted...")
    message_counts = await get_message_counts_by_chat(excluded_chats)
    total_to_delete = sum(message_counts.values())

    if total_to_delete == 0:
        logger.info("No messages found in filtered chats - database is already clean!")
        return

    logger.info(f"Will delete {total_to_delete} messages from {len(message_counts)} chats")

    # Show top 10 chats by message count
    if message_counts:
        logger.info("\nTop 10 chats by message count:")
        sorted_counts = sorted(message_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        for chat_id, count in sorted_counts:
            logger.info(f"  Chat {chat_id}: {count} messages")

    # Confirm deletion
    logger.info("\n" + "=" * 60)
    logger.info(f"READY TO DELETE {total_to_delete} MESSAGES")
    logger.info("=" * 60)

    try:
        response = input("\nProceed with deletion? (yes/no): ").strip().lower()
    except EOFError:
        # Running non-interactively, default to yes
        response = "yes"

    if response != "yes":
        logger.info("Deletion cancelled by user")
        return

    # Delete messages
    logger.info("\nDeleting messages...")
    deleted_count = await delete_messages_from_chats(excluded_chats, "filtered chats")

    # Get total message count after cleanup
    async with get_session() as session:
        result = await session.execute(select(func.count(Message.id)))
        total_messages_after = result.scalar()

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("CLEANUP COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Messages before:  {total_messages_before:,}")
    logger.info(f"Messages deleted: {deleted_count:,}")
    logger.info(f"Messages after:   {total_messages_after:,}")
    logger.info(f"Space saved:      {(deleted_count / total_messages_before * 100):.1f}%")
    logger.info("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(cleanup_filtered_messages())
    except KeyboardInterrupt:
        logger.info("\nCleanup interrupted by user")
    except Exception as e:
        logger.error(f"Cleanup failed: {e}", exc_info=True)
