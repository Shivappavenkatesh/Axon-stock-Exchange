import os
import asyncio
import inspect
import logging

# `python-telegram-bot` is optional: without it, notifications are disabled
# instead of crashing every module that imports this one.
try:
    from telegram import Bot
    from telegram.error import TelegramError
except ImportError:  # pragma: no cover - exercised only without the package
    Bot = None

    class TelegramError(Exception):
        pass

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

logger = logging.getLogger(__name__)

_bot = None
if TELEGRAM_BOT_TOKEN:
    if Bot is None:
        logger.warning("TELEGRAM_BOT_TOKEN is set but python-telegram-bot is not installed; Telegram alerts disabled")
    else:
        _bot = Bot(token=TELEGRAM_BOT_TOKEN)

def send_telegram_message(message: str) -> bool:
    """
    Send a message to the configured Telegram chat.
    Returns True if sent, False otherwise.
    """
    if not _bot or not TELEGRAM_CHAT_ID:
        return False

    try:
        # python-telegram-bot v20+ makes send_message async; older
        # versions expose it as a normal blocking function. Support
        # both by checking the attribute.
        send_fn = _bot.send_message

        async def _async_send():
            await send_fn(chat_id=TELEGRAM_CHAT_ID, text=message)

        if inspect.iscoroutinefunction(send_fn):
            # asyncio.run() fails in background threads (e.g. APScheduler)
            # where the default event loop may already be closed.  Create a
            # fresh loop explicitly so it works from any thread context.
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # We're inside an already-running loop (rare); schedule and wait.
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(lambda: asyncio.run(_async_send())).result(timeout=15)
            else:
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(_async_send())
                finally:
                    loop.close()
        else:
            send_fn(chat_id=TELEGRAM_CHAT_ID, text=message)

        return True
    except TelegramError as e:
        logger.error(f"Error sending Telegram message: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending Telegram message: {e}")
        return False
