import json
import time
import aiohttp
import async_timeout
import tiktoken
from loguru import logger
from typing import AsyncGenerator

from adapter.botservice import BotAdapter
from config import OpenAIAPIKey
from constants import botManager, config

DEFAULT_ENGINE: str = "gpt-3.5-turbo"


class OpenAIChatbot:
    def __init__(self, api_info: OpenAIAPIKey):
        self.api_key = api_info.api_key
        self.proxy = api_info.proxy
        self.presence_penalty = config.openai.gpt_params.presence_penalty
        self.frequency_penalty = config.openai.gpt_params.frequency_penalty
        self.top_p = config.openai.gpt_params.top_p
        self.temperature = config.openai.gpt_params.temperature
        self.max_tokens = config.openai.gpt_params.max_tokens
        self.engine = api_info.model or DEFAULT_ENGINE
        self.timeout = config.response.max_timeout
        self.conversation: dict[str, list[dict]] = {
            "default": [
                {
                    "role": "system",
                    "content": "You are ChatGPT, a large language model trained by OpenAI.\nKnowledge cutoff: 2021-09\nCurrent date:[current date]",
                },
            ],
        }

    async def rollback(self, session_id: str = "default", n: int = 1) -> None:
        try:
            if session_id not in self.conversation:
                raise ValueError(f"Session ID {session_id} does not exist")

            if n > len(self.conversation[session_id]):
                raise ValueError(f"Number of rollbacks {n} session exceeded {session_id} number of messages.")

            for _ in range(n):
                self.conversation[session_id].pop()

        except ValueError as ve:
            logger.error(ve)
            raise
        except Exception as e:
            logger.error(f"unknown err: {e}")
            raise

    def add_to_conversation(self, message: str, role: str, session_id: str = "default") -> None:
        if role and message is not None:
            self.conversation[session_id].append({"role": role, "content": message})
        else:
            logger.warning("An error occurred! The returned message is empty and is not added to the session.")
            raise ValueError("An error occurred! The returned message is empty and is not added to the session.")

    # https://github.com/openai/openai-cookbook/blob/main/examples/How_to_count_tokens_with_tiktoken.ipynb
    def count_tokens(self, session_id: str = "default", model: str = DEFAULT_ENGINE):
        """Return the number of tokens used by a list of messages."""
        if model is None:
            model = DEFAULT_ENGINE
        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")

        tokens_per_message = 4
        tokens_per_name = 1

        num_tokens = 0
        for message in self.conversation[session_id]:
            num_tokens += tokens_per_message
            for key, value in message.items():
                if value is not None:
                    num_tokens += len(encoding.encode(value))
                    if key == "name":
                        num_tokens += tokens_per_name
        num_tokens += 3  # every reply is primed with assistant
        return num_tokens

    def get_max_tokens(self, session_id: str, model: str) -> int:
        """Get max tokens"""
        return self.max_tokens - self.count_tokens(session_id, model)


class ChatGPTAPIAdapter(BotAdapter):
    api_info: OpenAIAPIKey = None
    """API Key"""

    def __init__(self, session_id: str = "unknown"):
        self.latest_role = None
        self.__conversation_keep_from = 0
        self.session_id = session_id
        self.api_info = botManager.pick('openai-api')
        self.bot = OpenAIChatbot(self.api_info)
        self.conversation_id = None
        self.parent_id = None
        super().__init__()
        self.bot.conversation[self.session_id] = []
        self.current_model = self.bot.engine
        self.supported_models = [
            "gpt-3.5-turbo",
            "gpt-3.5-turbo-0301",
            "gpt-3.5-turbo-0613",
            "gpt-3.5-turbo-16k",
            "gpt-3.5-turbo-16k-0613",
            "gpt-4",
            "gpt-4-0314",
            "gpt-4-32k",
            "gpt-4-32k-0314",
            "gpt-4-0613",
            "gpt-4-32k-0613",
        ]

    def manage_conversation(self, session_id: str, prompt: str):
        if session_id not in self.bot.conversation:
            self.bot.conversation[session_id] = [
                {"role": "system", "content": prompt}
            ]
            self.__conversation_keep_from = 1

        while self.bot.max_tokens - self.bot.count_tokens(session_id) < config.openai.gpt_params.min_tokens and \
                len(self.bot.conversation[session_id]) > self.__conversation_keep_from:
            self.bot.conversation[session_id].pop(self.__conversation_keep_from)
            logger.debug(
                f"Clean up the token and use the token number after the history is forgotten. {str(self.bot.count_tokens(session_id))}"
            )

    async def switch_model(self, model_name):
        self.current_model = model_name
        self.bot.engine = self.current_model

    async def rollback(self):
        if len(self.bot.conversation[self.session_id]) <= 0:
            return False
        await self.bot.rollback(self.session_id, n=2)
        return True

    async def on_reset(self):
        self.api_info = botManager.pick('openai-api')
        self.bot.api_key = self.api_info.api_key
        self.bot.proxy = self.api_info.proxy
        self.bot.conversation[self.session_id] = []
        self.bot.engine = self.current_model
        self.__conversation_keep_from = 0

    def construct_data(self, messages: list = None, api_key: str = None, stream: bool = True):
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }
        data = {
            'model': self.bot.engine,
            'messages': messages,
            'stream': stream,
            'temperature': self.bot.temperature,
            'top_p': self.bot.top_p,
            'presence_penalty': self.bot.presence_penalty,
            'frequency_penalty': self.bot.frequency_penalty,
            "user": 'user',
            'max_tokens': self.bot.get_max_tokens(self.session_id, self.bot.engine),
        }
        return headers, data

    def _prepare_request(self, session_id: str = None, messages: list = None, stream: bool = False):
        self.api_info = botManager.pick('openai-api')
        api_key = self.api_info.api_key
        proxy = self.api_info.proxy
        api_endpoint = config.openai.api_endpoint or "https://api.openai.com/v1"

        if not messages:
            messages = self.bot.conversation[session_id]

        headers, data = self.construct_data(messages, api_key, stream)

        return proxy, api_endpoint, headers, data

    async def _process_response(self, resp, session_id: str = None):

        result = await resp.json()

        total_tokens = result.get('usage', {}).get('total_tokens', None)
        logger.debug(f"[ChatGPT-API: {self.bot.engine}] use token amount : {total_tokens}")
        if total_tokens is None:
            raise Exception("Response does not contain 'total_tokens'")

        content = result.get('choices', [{}])[0].get('message', {}).get('content', None)
        logger.debug(f"[ChatGPT-API:{self.bot.engine}] response: {content}")
        if content is None:
            raise Exception("Response does not contain 'content'")

        response_role = result.get('choices', [{}])[0].get('message', {}).get('role', None)
        if response_role is None:
            raise Exception("Response does not contain 'role'")

        self.bot.add_to_conversation(content, response_role, session_id)

        return content

    async def request(self, session_id: str = None, messages: list = None) -> str:
        proxy, api_endpoint, headers, data = self._prepare_request(session_id, messages, stream=False)

        async with aiohttp.ClientSession() as session:
            with async_timeout.timeout(self.bot.timeout):
                async with session.post(f'{api_endpoint}/chat/completions', headers=headers,
                                                    data=json.dumps(data), proxy=proxy) as resp:
                    if resp.status != 200:
                        response_text = await resp.text()
                        raise Exception(
                            f"{resp.status} {resp.reason} {response_text}",
                        )
                    return await self._process_response(resp, session_id)

    async def request_with_stream(self, session_id: str = None, messages: list = None) -> AsyncGenerator[str, None]:
        proxy, api_endpoint, headers, data = self._prepare_request(session_id, messages, stream=True)

        async with aiohttp.ClientSession() as session:
            with async_timeout.timeout(self.bot.timeout):
                async with session.post(f'{api_endpoint}/chat/completions', headers=headers, data=json.dumps(data),
                                        proxy=proxy) as resp:
                    if resp.status != 200:
                        response_text = await resp.text()
                        raise Exception(
                            f"{resp.status} {resp.reason} {response_text}",
                        )

                    response_role: str = ''
                    completion_text: str = ''

                    async for line in resp.content:
                        try:
                            line = line.decode('utf-8').strip()
                            if not line.startswith("data: "):
                                continue
                            line = line[len("data: "):]
                            if line == "[DONE]":
                                break
                            if not line:
                                continue
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            raise Exception(f"JSON decoding error: {line}") from None
                        except Exception as e:
                            logger.error(f"unknown error: {e}\nResponse content: {resp.content}")
                            logger.error("Please submit this to the project issue so that the problem can be fixed.")
                            raise Exception(f"unknown error: {e}") from None
                        if 'error' in event:
                            raise Exception(f"Response error: {event['error']}")
                        if 'choices' in event and len(event['choices']) > 0 and 'delta' in event['choices'][0]:
                            delta = event['choices'][0]['delta']
                            if 'role' in delta:
                                if delta['role'] is not None:
                                    response_role = delta['role']
                            if 'content' in delta:
                                event_text = delta['content']
                                if event_text is not None:
                                    completion_text += event_text
                                    self.latest_role = response_role
                                    yield event_text
        self.bot.add_to_conversation(completion_text, response_role, session_id)

    async def compressed_session(self, session_id: str):
        if session_id not in self.bot.conversation or not self.bot.conversation[session_id]:
            logger.debug(f"The session does not exist and no compression is performed: {session_id}")
            return

        if self.bot.count_tokens(session_id) > config.openai.gpt_params.compressed_tokens:
            logger.debug('Start session compression')

            filtered_data = [entry for entry in self.bot.conversation[session_id] if entry['role'] != 'system']
            self.bot.conversation[session_id] = [entry for entry in self.bot.conversation[session_id] if
                                                 entry['role'] not in ['assistant', 'user']]

            filtered_data.append(({"role": "system",
                                   "content": "Summarize the discussion briefly in 200 words or less to use as a prompt for future context."}))

            async for text in self.request_with_stream(session_id=session_id, messages=filtered_data):
                pass

            token_count = self.bot.count_tokens(self.session_id, self.bot.engine)
            logger.debug(f"Amount of tokens used after compressing the session：{token_count}")

    async def ask(self, prompt: str) -> AsyncGenerator[str, None]:
        """Send a message to api and return the response with stream."""

        self.manage_conversation(self.session_id, prompt)

        if config.openai.gpt_params.compressed_session:
            await self.compressed_session(self.session_id)

        event_time = None

        try:
            if self.bot.engine not in self.supported_models:
                logger.warning(f"The current model is an unofficially supported model. Please pay attention to the console output. The currently used model is {self.bot.engine}")
            logger.debug(f"[Try using ChatGPT-API:{self.bot.engine}] ask: {prompt}")
            self.bot.add_to_conversation(prompt, "user", session_id=self.session_id)
            start_time = time.time()

            full_response = ''

            if config.openai.gpt_params.stream:
                async for resp in self.request_with_stream(session_id=self.session_id):
                    full_response += resp
                    yield full_response

                token_count = self.bot.count_tokens(self.session_id, self.bot.engine)
                logger.debug(f"[ChatGPT-API:{self.bot.engine}] response:{full_response}")
                logger.debug(f"[ChatGPT-API:{self.bot.engine}] Use token amount: {token_count}")
            else:
                yield await self.request(session_id=self.session_id)
            event_time = time.time() - start_time
            if event_time is not None:
                logger.debug(f"[ChatGPT-API:{self.bot.engine}] It took to receive all the messages{event_time:.2f}")

        except Exception as e:
            logger.error(f"[ChatGPT-API:{self.bot.engine}] Request failed: \n{e}")
            yield f"An error occurred: \n{e}"
            raise

    async def preset_ask(self, role: str, text: str):
        self.bot.engine = self.current_model
        if role.endswith('bot') or role in {'assistant', 'chatgpt'}:
            logger.debug(f"[Default] Response: {text}")
            yield text
            role = 'assistant'
        if role not in ['assistant', 'user', 'system']:
            raise ValueError(f"The default text is wrong! Only supports setting the default text of assistant, user or system, but you wrote {role}。")
        if self.session_id not in self.bot.conversation:
            self.bot.conversation[self.session_id] = []
            self.__conversation_keep_from = 0
        self.bot.conversation[self.session_id].append({"role": role, "content": text})
        self.__conversation_keep_from = len(self.bot.conversation[self.session_id])