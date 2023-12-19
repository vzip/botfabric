from typing import Generator

from loguru import logger


class BotAdapter:
    """Defines a common interface for all Chatbots"""
    preset_name: str = "default"

    def get_queue_info(self): ...
    """Get internal queue"""

    def __init__(self, session_id: str = "unknown"):
        self.supported_models = []
        self.current_model = "default"
        ...

    async def ask(self, msg: str) -> Generator[str, None, None]: ...
    """Send a message to AI"""

    async def rollback(self): ...
    """Roll back conversation"""

    async def on_reset(self): ...
    """This function is called when the session is reset"""

    async def preset_ask(self, role: str, text: str):
        """Ask questions in the default way"""
        if role.endswith('bot') or role in {'assistant', 'chatgpt'}:
            logger.debug(f"[Default] Response: {text}")
            yield text
        else:
            logger.debug(f"[Default] Send: {text}")
            item = None
            async for item in self.ask(text): ...
            if item:
                logger.debug(f"[Default] Chatbot responds:{item}")

    async def switch_model(self, model_name): ...
    """Switch model"""