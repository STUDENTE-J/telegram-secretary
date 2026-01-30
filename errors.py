"""
Centralized error handling and logging for Telegram Secretary Bot.
Provides structured error messages and consistent logging format.
"""

import logging
import traceback
from typing import Optional, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)


class ErrorCategory(str, Enum):
    """Error categories for better organization in logs."""
    DATABASE = "DATABASE"
    TELEGRAM_API = "TELEGRAM_API"
    CONFIGURATION = "CONFIGURATION"
    MESSAGE_PROCESSING = "MESSAGE_PROCESSING"
    AI_SCORING = "AI_SCORING"
    SCHEDULING = "SCHEDULING"
    FILTERING = "FILTERING"
    CALLBACK = "CALLBACK"
    UNKNOWN = "UNKNOWN"


def log_error(
    category: ErrorCategory,
    message: str,
    error: Optional[Exception] = None,
    context: Optional[Dict[str, Any]] = None,
    include_trace: bool = True
) -> None:
    """
    Log an error with structured formatting.

    Args:
        category: Error category for classification
        message: Human-readable error description
        error: The exception object (if any)
        context: Additional context (user_id, chat_id, etc.)
        include_trace: Whether to include full stack trace
    """
    # Build error message
    error_parts = [f"[{category.value}]", message]

    # Add context if provided
    if context:
        context_str = ", ".join(f"{k}={v}" for k, v in context.items())
        error_parts.append(f"Context: {{{context_str}}}")

    # Add error details
    if error:
        error_parts.append(f"Error: {type(error).__name__}: {str(error)}")

    error_msg = " | ".join(error_parts)

    # Log with appropriate level and trace
    if include_trace and error:
        logger.error(error_msg, exc_info=True)
    else:
        logger.error(error_msg)


def log_warning(
    category: ErrorCategory,
    message: str,
    context: Optional[Dict[str, Any]] = None
) -> None:
    """
    Log a warning with structured formatting.

    Args:
        category: Warning category
        message: Human-readable warning description
        context: Additional context
    """
    warning_parts = [f"[{category.value}]", message]

    if context:
        context_str = ", ".join(f"{k}={v}" for k, v in context.items())
        warning_parts.append(f"Context: {{{context_str}}}")

    logger.warning(" | ".join(warning_parts))


def log_info(
    category: ErrorCategory,
    message: str,
    context: Optional[Dict[str, Any]] = None
) -> None:
    """
    Log an informational message with structured formatting.

    Args:
        category: Info category
        message: Human-readable info description
        context: Additional context
    """
    info_parts = [f"[{category.value}]", message]

    if context:
        context_str = ", ".join(f"{k}={v}" for k, v in context.items())
        info_parts.append(f"Context: {{{context_str}}}")

    logger.info(" | ".join(info_parts))


def format_exception(error: Exception) -> str:
    """
    Format exception with traceback for logging.

    Args:
        error: The exception to format

    Returns:
        Formatted string with exception details and traceback
    """
    tb_lines = traceback.format_exception(type(error), error, error.__traceback__)
    return "".join(tb_lines)


class SecretaryBotError(Exception):
    """Base exception for Telegram Secretary Bot errors."""

    def __init__(self, category: ErrorCategory, message: str, context: Optional[Dict[str, Any]] = None):
        self.category = category
        self.context = context or {}
        super().__init__(message)

    def log(self) -> None:
        """Log this error with full context."""
        log_error(
            category=self.category,
            message=str(self),
            error=self,
            context=self.context,
            include_trace=True
        )


class DatabaseError(SecretaryBotError):
    """Database operation failed."""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(ErrorCategory.DATABASE, message, context)


class TelegramAPIError(SecretaryBotError):
    """Telegram API call failed."""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(ErrorCategory.TELEGRAM_API, message, context)


class ConfigurationError(SecretaryBotError):
    """Configuration validation or loading failed."""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(ErrorCategory.CONFIGURATION, message, context)


class MessageProcessingError(SecretaryBotError):
    """Message processing failed."""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(ErrorCategory.MESSAGE_PROCESSING, message, context)


class AIScoringError(SecretaryBotError):
    """AI scoring failed."""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(ErrorCategory.AI_SCORING, message, context)
