"""
Configuration management for Telegram Secretary Bot.
Loads environment variables and provides typed access to settings.
"""

import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


@dataclass
class TelegramConfig:
    """Telegram API configuration."""
    api_id: int
    api_hash: str
    phone: str
    bot_token: str
    client_user_id: int
    password: Optional[str] = None  # 2FA password (optional)


@dataclass
class DatabaseConfig:
    """Database configuration."""
    url: str


@dataclass
class SchedulerConfig:
    """Scheduler configuration."""
    summary_interval_hours: int
    max_messages_per_summary: int
    min_priority_score: int
    timezone: str
    warning_threshold_score: int  # Score threshold for real-time warnings


@dataclass
class AIConfig:
    """AI-based scoring configuration."""
    enabled: bool
    model: str
    timeout_seconds: float
    ollama_host: str


@dataclass
class FilterConfig:
    """Message filtering configuration."""
    ignore_large_groups: bool
    max_group_size: int
    ignore_muted_chats: bool


@dataclass
class Config:
    """Main configuration container."""
    telegram: TelegramConfig
    database: DatabaseConfig
    scheduler: SchedulerConfig
    ai: AIConfig
    filter: FilterConfig
    log_level: str


def _get_required_env(key: str) -> str:
    """Get a required environment variable or raise an error."""
    value = os.getenv(key)
    if not value:
        raise ValueError(
            f"❌ Missing required environment variable: {key}\n"
            f"Please add it to your .env file. See .env.example for reference."
        )
    return value


def _get_optional_env(key: str, default: str) -> str:
    """Get an optional environment variable with a default value."""
    return os.getenv(key, default)


def _get_int_env(key: str, default: Optional[int] = None) -> int:
    """Get an integer environment variable with validation."""
    if default is not None:
        value_str = _get_optional_env(key, str(default))
        is_required = False
    else:
        value_str = _get_required_env(key)
        is_required = True

    try:
        return int(value_str)
    except ValueError:
        if is_required:
            raise ValueError(
                f"❌ {key} must be a valid integer, got: '{value_str}'\n"
                f"Example: {key}=12345"
            )
        else:
            raise ValueError(
                f"❌ {key} must be a valid integer, got: '{value_str}'\n"
                f"Example: {key}={default}"
            )


def _get_float_env(key: str, default: float) -> float:
    """Get a float environment variable with validation."""
    value_str = _get_optional_env(key, str(default))
    try:
        return float(value_str)
    except ValueError:
        raise ValueError(
            f"❌ {key} must be a valid number, got: '{value_str}'\n"
            f"Example: {key}={default}"
        )


def load_config() -> Config:
    """Load and validate all configuration from environment variables."""

    # Validate Telegram configuration
    api_id = _get_int_env("TELEGRAM_API_ID")
    api_hash = _get_required_env("TELEGRAM_API_HASH")
    phone = _get_required_env("TELEGRAM_PHONE")
    bot_token = _get_required_env("BOT_TOKEN")
    client_user_id = _get_int_env("CLIENT_USER_ID")

    # Validate API ID is positive
    if api_id <= 0:
        raise ValueError(
            f"❌ TELEGRAM_API_ID must be positive, got: {api_id}\n"
            f"Get your API ID from https://my.telegram.org"
        )

    # Validate bot token format
    if ":" not in bot_token:
        raise ValueError(
            f"❌ BOT_TOKEN has invalid format\n"
            f"Expected format: 1234567890:ABC-DEF1234ghIkl-zyx57W2v1u123ew11\n"
            f"Get it from @BotFather on Telegram"
        )

    # Validate phone format
    if not phone.startswith("+"):
        raise ValueError(
            f"❌ TELEGRAM_PHONE must include country code with +\n"
            f"Example: +5511999999999\n"
            f"Got: {phone}"
        )

    telegram = TelegramConfig(
        api_id=api_id,
        api_hash=api_hash,
        phone=phone,
        bot_token=bot_token,
        client_user_id=client_user_id,
        password=os.getenv("TELEGRAM_PASSWORD") or None,
    )

    # Validate database configuration
    database_url = _get_required_env("DATABASE_URL")
    if not (database_url.startswith("sqlite") or database_url.startswith("postgresql")):
        raise ValueError(
            f"❌ DATABASE_URL must start with 'sqlite' or 'postgresql'\n"
            f"Got: {database_url[:20]}..."
        )

    database = DatabaseConfig(url=database_url)

    # Validate scheduler configuration
    summary_interval = _get_int_env("SUMMARY_INTERVAL_HOURS", 4)
    max_messages = _get_int_env("MAX_MESSAGES_PER_SUMMARY", 15)
    min_score = _get_int_env("MIN_PRIORITY_SCORE", 1)
    warning_threshold = _get_int_env("WARNING_THRESHOLD_SCORE", 5)

    if summary_interval < 1:
        raise ValueError(
            f"❌ SUMMARY_INTERVAL_HOURS must be at least 1, got: {summary_interval}"
        )

    if max_messages < 1:
        raise ValueError(
            f"❌ MAX_MESSAGES_PER_SUMMARY must be at least 1, got: {max_messages}"
        )

    if min_score < 0:
        raise ValueError(
            f"❌ MIN_PRIORITY_SCORE must be >= 0, got: {min_score}"
        )

    if warning_threshold < 0 or warning_threshold > 10:
        raise ValueError(
            f"❌ WARNING_THRESHOLD_SCORE must be between 0-10, got: {warning_threshold}"
        )

    scheduler = SchedulerConfig(
        summary_interval_hours=summary_interval,
        max_messages_per_summary=max_messages,
        min_priority_score=min_score,
        timezone=_get_optional_env("TIMEZONE", "America/Sao_Paulo"),
        warning_threshold_score=warning_threshold,
    )

    # Validate AI configuration
    ai = AIConfig(
        enabled=_get_optional_env("USE_AI_SCORING", "true").lower() == "true",
        model=_get_optional_env("AI_MODEL", "llama3.2:3b"),
        timeout_seconds=_get_float_env("AI_SCORING_TIMEOUT", 3.0),
        ollama_host=_get_optional_env("OLLAMA_HOST", "http://localhost:11434"),
    )

    # Validate filter configuration
    max_group_size = _get_int_env("MAX_GROUP_SIZE", 20)

    if max_group_size < 2:
        raise ValueError(
            f"❌ MAX_GROUP_SIZE must be at least 2, got: {max_group_size}"
        )

    filter_config = FilterConfig(
        ignore_large_groups=_get_optional_env("IGNORE_LARGE_GROUPS", "false").lower() == "true",
        max_group_size=max_group_size,
        ignore_muted_chats=_get_optional_env("IGNORE_MUTED_CHATS", "true").lower() == "true",
    )

    config = Config(
        telegram=telegram,
        database=database,
        scheduler=scheduler,
        ai=ai,
        filter=filter_config,
        log_level=_get_optional_env("LOG_LEVEL", "INFO"),
    )

    return config


# Global config instance (lazy loaded)
_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config

