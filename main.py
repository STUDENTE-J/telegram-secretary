"""
Main entry point for Telegram Secretary Bot.
Initializes and runs all components: userbot, bot, scheduler, database.
"""

import asyncio
import logging
import signal
import sys
from typing import Optional

from config import get_config

# Configure logging before importing other modules
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)

# Reduce noise from external libraries
logging.getLogger("telethon").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Import error handling after logging is configured
from errors import (
    log_error,
    log_warning,
    log_info,
    ErrorCategory,
)


class SecretaryBot:
    """
    Main application class that orchestrates all components.
    """
    
    def __init__(self):
        self._running = False
        self._shutdown_event: Optional[asyncio.Event] = None
    
    async def startup(self) -> None:
        """Initialize all components."""
        logger.info("=" * 50)
        logger.info("🤖 Telegram Secretary Bot - Starting Up")
        logger.info("=" * 50)

        # Load and validate config
        try:
            config = get_config()
            log_info(
                ErrorCategory.CONFIGURATION,
                "Configuration loaded successfully",
                context={
                    "summary_interval_hours": config.scheduler.summary_interval_hours,
                    "max_messages_per_summary": config.scheduler.max_messages_per_summary,
                    "timezone": config.scheduler.timezone,
                    "ai_enabled": config.ai.enabled
                }
            )
        except Exception as e:
            log_error(
                ErrorCategory.CONFIGURATION,
                "Failed to load configuration",
                error=e,
                include_trace=True
            )
            raise

        # Initialize database (must be first - everything depends on it)
        log_info(ErrorCategory.DATABASE, "Initializing database")
        from database import init_database, create_tables
        await init_database()
        await create_tables()
        log_info(ErrorCategory.DATABASE, "Database initialized successfully")

        # Start all components in parallel for fast startup
        log_info(ErrorCategory.TELEGRAM_API, "Starting all components in parallel")
        from bot import start_bot
        from userbot import start_userbot, refresh_high_priority_users
        from scheduler import start_scheduler

        await asyncio.gather(
            start_bot(),
            start_userbot(),
            start_scheduler(),
            refresh_high_priority_users()
        )

        log_info(ErrorCategory.TELEGRAM_API, "All components started successfully")

        logger.info("=" * 50)
        logger.info("🚀 All systems operational!")
        logger.info("=" * 50)

        # Send startup notification
        try:
            from bot import send_simple_message
            await send_simple_message(
                "🤖 *Secretary Bot Online*\n\n"
                "I'm now monitoring your messages and will send summaries "
                f"every {config.scheduler.summary_interval_hours} hours.\n\n"
                "Use /summary to get a summary now."
            )
        except Exception as e:
            log_warning(
                ErrorCategory.TELEGRAM_API,
                "Could not send startup notification",
                context={"error": str(e)}
            )
    
    async def shutdown(self) -> None:
        """Gracefully shutdown all components."""
        logger.info("=" * 50)
        logger.info("🛑 Shutting down...")
        logger.info("=" * 50)

        # Stop scheduler first
        try:
            from scheduler import stop_scheduler
            await stop_scheduler()
        except Exception as e:
            log_error(
                ErrorCategory.SCHEDULING,
                "Error stopping scheduler during shutdown",
                error=e,
                include_trace=True
            )

        # Stop userbot
        try:
            from userbot import stop_userbot
            await stop_userbot()
        except Exception as e:
            log_error(
                ErrorCategory.TELEGRAM_API,
                "Error stopping userbot during shutdown",
                error=e,
                include_trace=True
            )

        # Stop bot
        try:
            from bot import stop_bot
            await stop_bot()
        except Exception as e:
            log_error(
                ErrorCategory.TELEGRAM_API,
                "Error stopping bot during shutdown",
                error=e,
                include_trace=True
            )

        # Close database
        try:
            from database import close_database
            await close_database()
        except Exception as e:
            log_error(
                ErrorCategory.DATABASE,
                "Error closing database during shutdown",
                error=e,
                include_trace=True
            )

        logger.info("=" * 50)
        logger.info("👋 Goodbye!")
        logger.info("=" * 50)
    
    async def run(self) -> None:
        """Run the application until shutdown signal."""
        self._running = True
        self._shutdown_event = asyncio.Event()
        
        # Set up signal handlers
        loop = asyncio.get_running_loop()
        
        def signal_handler():
            log_info(ErrorCategory.UNKNOWN, "Received shutdown signal (SIGINT/SIGTERM)")
            self._running = False
            if self._shutdown_event:
                self._shutdown_event.set()
        
        # Handle SIGINT (Ctrl+C) and SIGTERM (Docker/Railway stop)
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, signal_handler)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass
        
        try:
            await self.startup()
            
            # Get the userbot client to keep it running
            from userbot import get_userbot_client
            client = await get_userbot_client()
            
            # Run until shutdown signal
            logger.info("Running... Press Ctrl+C to stop")
            
            # Wait for either shutdown event or client disconnect
            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(self._shutdown_event.wait()),
                    asyncio.create_task(client.run_until_disconnected()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            
            # Cancel pending tasks
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            
        except Exception as e:
            log_error(
                ErrorCategory.UNKNOWN,
                "Fatal error in main application loop",
                error=e,
                include_trace=True
            )
            raise
        finally:
            await self.shutdown()


async def main() -> None:
    """Main entry point."""
    bot = SecretaryBot()
    await bot.run()


def run() -> None:
    """
    Synchronous entry point for running the bot.
    
    Usage:
        python main.py
    """
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass  # Graceful shutdown handled in run()


if __name__ == "__main__":
    run()

