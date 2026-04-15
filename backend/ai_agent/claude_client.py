"""Cliente Anthropic real para SOLER - fallback si no hay API key."""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ClaudeClient:
    def __init__(self):
        self.api_key = os.getenv('ANTHROPIC_API_KEY', '')
        self.enabled = bool(self.api_key)
        self.client = None
        if self.enabled:
            try:
                from anthropic import AsyncAnthropic
                self.client = AsyncAnthropic(api_key=self.api_key)
                logger.info("ClaudeClient habilitado")
            except ImportError:
                logger.warning("anthropic no instalado")
                self.enabled = False

    async def complete(self, system: str, user_msg: str, max_tokens: int = 2048) -> Optional[str]:
        if not self.enabled or not self.client:
            return None
        try:
            resp = await self.client.messages.create(
                model="claude-sonnet-4-5-20250514",
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            )
            return resp.content[0].text
        except Exception as e:
            logger.error("Claude API error: %s", e)
            return None


_client: Optional[ClaudeClient] = None


def get_claude_client() -> ClaudeClient:
    global _client
    if _client is None:
        _client = ClaudeClient()
    return _client
