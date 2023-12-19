from typing import Callable, Dict, Optional
from loguru import logger

from constants import config
from middlewares.middleware import Middleware
from conversation import ConversationContext, ConversationHandler
from utils import QueueInfo


class MiddlewareConcurrentLock(Middleware):
    ctx: Dict[str, QueueInfo] = dict()

    def __init__(self):
        ...

    async def handle_request(self, session_id: str, prompt: str, respond: Callable,
                             conversation_context: Optional[ConversationContext], action: Callable):
        handler = await ConversationHandler.get_handler(session_id)

        if session_id not in self.ctx:
            self.ctx[session_id] = QueueInfo()
        queue_info = self.ctx[session_id]
        selected_ctx = handler.current_conversation if conversation_context is None else conversation_context
        if internal_queue := selected_ctx.adapter.get_queue_info():
            logger.debug("[Concurrent] Use Adapter Internal Queue")
            # If Adapter implemented internally Queue，then you need to queue up the middleware first before using theirs.
            logger.debug(f"[Concurrent] Queuing, there are others ahead{queue_info.size} private！")
            async with queue_info:
                queue_info = internal_queue
        # Reject new messages when the queue is full
        if 0 < config.response.max_queue_size < queue_info.size:
            logger.debug("[Concurrent]Queue is full, denial of service！")
            await respond(config.response.queue_full)
            return
        else:
            # Prompt user: request has been queued
            if queue_info.size > config.response.queued_notice_size:
                await respond(config.response.queued_notice.format(queue_size=queue_info.size))
        # execute in queue
        logger.debug(f"[Concurrent] Queuing, there are others ahead {queue_info.size} private！")
        async with queue_info:
            logger.debug("[Concurrent] Arrive in line！")
            await action(session_id, prompt, conversation_context, respond)