import contextlib
import time
from datetime import datetime
from typing import List, Dict, Optional

import httpx
from graia.amnesia.message import MessageChain
from graia.ariadne.message.element import Image as GraiaImage, Element

from loguru import logger


from adapter.botservice import BotAdapter
from adapter.chatgpt.api import ChatGPTAPIAdapter

from constants import LlmName
from constants import config

from drawing import DrawingAPI, SDWebUI as SDDrawing, OpenAI as OpenAIDrawing

from exceptions import PresetNotFoundException, BotTypeNotFoundException, NoAvailableBotException, \
    CommandRefusedException, DrawingFailedException

from middlewares.draw_ratelimit import MiddlewareRatelimit

from renderer import Renderer
from renderer.merger import BufferedContentMerger, LengthContentMerger
from renderer.renderer import MixedContentMessageChainRenderer, MarkdownImageRenderer, PlainTextRenderer
from renderer.splitter import MultipleSegmentSplitter

from utils import retry
from utils.text_to_speech import TtsVoice, TtsVoiceManager

handlers = {}

middlewares = MiddlewareRatelimit()


class ConversationContext:
    type: str
    adapter: BotAdapter
    """Chatbot Adapter"""

    splitter: Renderer
    """message separator"""
    merger: Renderer
    """message combiner"""
    renderer: Renderer
    """message renderer"""

    drawing_adapter: DrawingAPI = None
    """drawing engine"""

    preset: str = None

    preset_decoration_format: Optional[str] = "{prompt}"
    """Default text"""

    conversation_voice: TtsVoice = None
    """Voice """

    @property
    def current_model(self):
        return self.adapter.current_model

    @property
    def supported_models(self):
        return self.adapter.supported_models

    def __init__(self, _type: str, session_id: str):
        self.session_id = session_id

        self.last_resp = ''

        self.last_resp_time = -1

        self.switch_renderer()

        if config.text_to_speech.always:
            tts_engine = config.text_to_speech.engine
            tts_voice = config.text_to_speech.default
            try:
                self.conversation_voice = TtsVoiceManager.parse_tts_voice(tts_engine, tts_voice)
            except KeyError as e:
                logger.error(f"Failed to load {tts_engine} tts voice setting -> {tts_voice}")
        if _type == LlmName.ChatGPT_Api.value:
            self.adapter = ChatGPTAPIAdapter(self.session_id)
        else:
            raise BotTypeNotFoundException(_type)
        self.type = _type

        # 
        if config.sdwebui:
            self.drawing_adapter = SDDrawing()
        else:
            with contextlib.suppress(NoAvailableBotException):
                self.drawing_adapter = OpenAIDrawing(self.session_id)

    def switch_renderer(self, mode: Optional[str] = None):
        # Currently this is the only one
        self.splitter = MultipleSegmentSplitter()

        if config.response.buffer_delay > 0:
            self.merger = BufferedContentMerger(self.splitter)
        else:
            self.merger = LengthContentMerger(self.splitter)

        if not mode:
            mode = "image" if config.text_to_image.default or config.text_to_image.always else config.response.mode

        if mode == "image" or config.text_to_image.always:
            self.renderer = MarkdownImageRenderer(self.merger)
        elif mode == "mixed":
            self.renderer = MixedContentMessageChainRenderer(self.merger)
        elif mode == "text":
            self.renderer = PlainTextRenderer(self.merger)
        else:
            self.renderer = MixedContentMessageChainRenderer(self.merger)
        if mode != "image" and config.text_to_image.always:
            raise CommandRefusedException("Since the profile setting forces picture mode on, It won't switch to any other mode.")

    async def reset(self):
        await self.adapter.on_reset()
        self.last_resp = ''
        self.last_resp_time = -1
        yield config.response.reset

    @retry((httpx.ConnectError, httpx.ConnectTimeout, TimeoutError))
    async def ask(self, prompt: str, chain: MessageChain = None, name: str = None):
        await self.check_and_reset()
        # Check if it is a drawing command
        for prefix in config.trigger.prefix_image:
            if prompt.startswith(prefix):
                # TODO : This section can be merged into RateLimitMiddleware
                respond_str = middlewares.handle_draw_request(self.session_id, prompt)
                # TODO : wtf is it
                if respond_str != "1":
                    yield respond_str
                    return
                if not self.drawing_adapter:
                    yield "The drawing engine is not configured and the drawing function cannot be used!"
                    return
                prompt = prompt.removeprefix(prefix)
                try:
                    if chain.has(GraiaImage):
                        images = await self.drawing_adapter.img_to_img(chain.get(GraiaImage), prompt)
                    else:
                        images = await self.drawing_adapter.text_to_img(prompt)
                    for i in images:
                        yield i
                except Exception as e:
                    raise DrawingFailedException from e
                respond_str = middlewares.handle_draw_respond_completed(self.session_id, prompt)
                if respond_str != "1":
                    yield respond_str
                return

        if self.preset_decoration_format:
            prompt = (
                self.preset_decoration_format.replace("{prompt}", prompt)
                .replace("{nickname}", name)
                .replace("{last_resp}", self.last_resp)
                .replace("{date}", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            )

        async with self.renderer:
            async for item in self.adapter.ask(prompt):
                if isinstance(item, Element):
                    yield item
                else:
                    yield await self.renderer.render(item)
                self.last_resp = item or ''
                self.last_resp_time = int(time.time())
            yield await self.renderer.result()

    async def rollback(self):
        resp = await self.adapter.rollback()
        if isinstance(resp, bool):
            yield config.response.rollback_success if resp else config.response.rollback_fail.format(
                reset=config.trigger.reset_command)
        else:
            yield resp

    async def switch_model(self, model_name):
        return await self.adapter.switch_model(model_name)

    async def load_preset(self, keyword: str):
        self.preset_decoration_format = None
        if keyword in config.presets.keywords:
            presets = config.load_preset(keyword)
            for text in presets:
                if not text.strip() or not text.startswith('#'):
                    # Determine whether the format is role: text
                    if ':' in text:
                        role, text = text.split(':', 1)
                    else:
                        role = 'system'

                    if role == 'user_send':
                        self.preset_decoration_format = text
                        continue

                    if role == 'voice':
                        self.conversation_voice = TtsVoiceManager.parse_tts_voice(config.text_to_speech.engine,
                                                                                  text.strip())
                        logger.debug(f"Set conversation voice to {self.conversation_voice.full_name}")
                        continue

                    async for item in self.adapter.preset_ask(role=role.lower().strip(), text=text.strip()):
                        yield item
        elif keyword != 'default':
            raise PresetNotFoundException(keyword)
        self.preset = keyword

    def delete_message(self, respond_msg):
        # TODO: adapt to all platforms
        pass

    async def check_and_reset(self):
        timeout_seconds = config.system.auto_reset_timeout_seconds
        current_time = time.time()
        if timeout_seconds == -1 or self.last_resp_time == -1 or current_time - self.last_resp_time < timeout_seconds:
            return
        logger.debug(f"Reset conversation({self.session_id}) after {current_time - self.last_resp_time} seconds.")
        async for _resp in self.reset():
            logger.debug(_resp)


class ConversationHandler:
    """
    Each chat window has one ConversationHandler,
    Responsible for managing multiple different ConversationContext
    """
    conversations: Dict[str, ConversationContext]
    """All conversations in the current chat window"""

    current_conversation: ConversationContext = None

    session_id: str = 'unknown'

    def __init__(self, session_id: str):
        self.conversations = {}
        self.session_id = session_id

    def list(self) -> List[ConversationContext]:
        ...

    """
    Get or create a new context
    Here's the code and create it's the same
    Because the multi-session function will be added after create
    """

    async def first_or_create(self, _type: str):
        if _type in self.conversations:
            return self.conversations[_type]
        conversation = ConversationContext(_type, self.session_id)
        self.conversations[_type] = conversation
        return conversation

    """Create new context"""

    async def create(self, _type: str):
        if _type in self.conversations:
            return self.conversations[_type]
        conversation = ConversationContext(_type, self.session_id)
        self.conversations[_type] = conversation
        return conversation

    """Switch conversation context"""

    def switch(self, index: int) -> bool:
        if len(self.conversations) > index:
            self.current_conversation = self.conversations[index]
            return True
        return False

    @classmethod
    async def get_handler(cls, session_id: str):
        if session_id not in handlers:
            handlers[session_id] = ConversationHandler(session_id)
        return handlers[session_id]