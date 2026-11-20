"""
Sends trade confirmations and status updates back to the user via Telegram.

Uses the SAME user-mode Telethon client as the listener (shared session),
so no bot setup is required. Messages are DM'd to the user's own
Saved Messages / their own chat with themselves (configurable).
"""
import logging
from typing import Optional

from telethon import TelegramClient

import config

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, client: TelegramClient):
        """
        client: an already-authenticated TelegramClient (shared with the listener).
        """
        self.client = client
        self.target_id = config.TELEGRAM_NOTIFY_USER_ID
        self._resolved = None

    async def _resolve_target(self):
        if self._resolved is not None:
            return self._resolved

        if self.target_id:
            try:
                self._resolved = await self.client.get_entity(self.target_id)
                return self._resolved
            except Exception as e:
                logger.warning(f"Could not resolve notify target {self.target_id}: {e}")

        # Fallback — Saved Messages (the user chatting with themselves)
        me = await self.client.get_me()
        self._resolved = me
        return self._resolved

    async def send(self, message: str):
        """Send a plain-text notification."""
        try:
            target = await self._resolve_target()
            await self.client.send_message(target, message)
        except Exception as e:
            logger.warning(f"Notification send failed: {e}")
