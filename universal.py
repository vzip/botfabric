import asyncio
import re
from typing import Callable

import httpcore
import httpx
import openai
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Plain
from httpx import ConnectTimeout
from loguru import logger
from requests.exceptions import SSLError, ProxyError, RequestException
from urllib3.exceptions import MaxRetryError

from constants import botManager, BotPlatform
from constants import config
from conversation import ConversationHandler, ConversationContext
from exceptions import PresetNotFoundException, BotRatelimitException, ConcurrentMessageException, \
    BotTypeNotFoundException, NoAvailableBotException, BotOperationNotSupportedException, CommandRefusedException, \
    DrawingFailedException

from middlewares.concurrentlock import MiddlewareConcurrentLock
from middlewares.ratelimit import MiddlewareRatelimit
from middlewares.timeout import MiddlewareTimeout

from utils.text_to_speech import get_tts_voice, TtsVoiceManager, VoiceType

middlewares = [MiddlewareTimeout(), MiddlewareRatelimit(), MiddlewareConcurrentLock()]


async def get_ping_response(conversation_context: ConversationContext):
    current_voice = conversation_context.conversation_voice.alias if conversation_context.conversation_voice else "None"
    response = config.response.ping_response.format(current_ai=conversation_context.type,
                                                    current_voice=current_voice,
                                                    supported_ai=botManager.bots_info())
    tts_voices = await TtsVoiceManager.list_tts_voices(
        config.text_to_speech.engine, config.text_to_speech.default_voice_prefix)
    if tts_voices:
        supported_tts = ",".join([v.alias for v in tts_voices])
        response += config.response.ping_tts_response.format(supported_tts=supported_tts)
    return response


async def handle_message(_respond: Callable, session_id: str, message: str,
                         chain: MessageChain = MessageChain("Unsupported"), is_manager: bool = False,
                         nickname: str = 'Someone', request_from=None):
    conversation_context = None

    def wrap_request(n, m):
        """
        Wrapping send messages
        """
        async def call(session_id, message, conversation_context, respond):
            await m.handle_request(session_id, message, respond, conversation_context, n)

        return call

    def wrap_respond(n, m):
        """
        Wrapping respond messages
        """
        async def call(session_id, message, rendered, respond):
            await m.handle_respond(session_id, message, rendered, respond, n)

        return call

    async def respond(msg: str):
        """
        Respond method
        """
        if not msg:
            return
        ret = await _respond(msg)
        for m in middlewares:
            await m.on_respond(session_id, message, msg)

        # TODO: Later refactored into platforms ' respond only handles MessageChain
        if isinstance(msg, str):
            msg = MessageChain([Plain(msg)])

        nonlocal conversation_context
        if not conversation_context:
            conversation_context = conversation_handler.current_conversation

        if not conversation_context:
            return ret
        # TTS Converting
        if conversation_context.conversation_voice and isinstance(msg, MessageChain):
            if request_from == BotPlatform.HttpService:
                voice_type = VoiceType.Mp3
            else:
                voice_type = VoiceType.Wav
            tasks = []
            for elem in msg:
                task = asyncio.create_task(get_tts_voice(elem, conversation_context, voice_type))
                tasks.append(task)
            while tasks:
                done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for voice_task in done:
                    voice = await voice_task
                    if voice:
                        await _respond(voice)

        return ret

    async def request(_session_id, prompt: str, conversation_context, _respond):
        """
        Request method
        """

        task = None

        # Without prefix - initialize session normally
        if bot_type_search := re.search(config.trigger.switch_command, prompt):
            if not (config.trigger.allow_switching_ai or is_manager):
                await respond("Sorry, only administrators can switch AI!")
                return
            conversation_handler.current_conversation = (
                await conversation_handler.create(
                    bot_type_search[1].strip()
                )
            )
            await respond(f"Switched to {bot_type_search[1].strip()} AI start chatting with me now")
            return
        # The final conversation context to choose
        if not conversation_context:
            conversation_context = conversation_handler.current_conversation
        # Here are the instructions that can be executed after the session exists

        # Reset session
        if prompt in config.trigger.reset_command:
            task = conversation_context.reset()

        elif prompt in config.trigger.rollback_command:
            task = conversation_context.rollback()

        elif prompt in config.trigger.ping_command:
            await respond(await get_ping_response(conversation_context))
            return

        elif voice_type_search := re.search(config.trigger.switch_voice, prompt):
            if not config.azure.tts_speech_key and config.text_to_speech.engine == "azure":
                await respond("The Azure TTS account is not configured and voice switching cannot be performed!")
            new_voice = voice_type_search[1].strip()
            if new_voice in ['None', "None"]:
                conversation_context.conversation_voice = None
                await respond("Voice is turned off, let's continue chatting")
            elif config.text_to_speech.engine == "azure":
                tts_voice = TtsVoiceManager.parse_tts_voice("azure", new_voice)
                conversation_context.conversation_voice = tts_voice
                if tts_voice:
                    await respond(f"Switched to {tts_voice.full_name} Voice, let's keep chatting!")
                else:
                    await respond("The provided voice ID is invalid. Please enter a valid voice ID.")
            else:
                await respond("The text-to-speech engine is not configured and the voice function cannot be used.")
            return

        elif prompt in config.trigger.mixed_only_command:
            conversation_context.switch_renderer("mixed")
            await respond("It has been switched to the mixed image and text mode, and my next reply will be presented in a mixed mode of image and text!")
            return

        elif prompt in config.trigger.image_only_command:
            conversation_context.switch_renderer("image")
            await respond("Switched to picture-only mode, my next reply will be presented in pictures!")
            return

        elif prompt in config.trigger.text_only_command:
            conversation_context.switch_renderer("text")
            await respond("Switched to text-only mode, my next reply will be presented in text (except for being swallowed)")
            return

        elif switch_model_search := re.search(config.trigger.switch_model, prompt):
            model_name = switch_model_search[1].strip()
            if model_name in conversation_context.supported_models:
                if not (is_manager or model_name in config.trigger.allowed_models):
                    await respond(f"Sorry, only administrators can switch to Sorry, only administrators can switch to {model_name} ")
                else:
                    await conversation_context.switch_model(model_name)
                    await respond(f"Switched to {model_name} Model, let's chat")
            else:
                logger.warning(f"Model {model_name} is not in the support list and will try to create a conversation using this model next time.")
                await conversation_context.switch_model(model_name)
                await respond(
                    f"Model {model_name} is not in the support list. We will try to use this model to create a conversation next time. Currently, AI only supports {conversation_context.supported_models}")
            return

        # Load preset
        if preset_search := re.search(config.presets.command, prompt):
            logger.trace(f"session_id : {session_id}  {preset_search[1]}")
            async for _ in conversation_context.reset(): ...
            task = conversation_context.load_preset(preset_search[1])
        elif not conversation_context.preset:
            # There are currently no presets
            logger.trace(f"session_id : {session_id} Preset not detected, executing default preset...")
            # Implicit loading does not reply to the default content
            async for _ in conversation_context.load_preset('default'): ...

        # If you don’t have any tasks, let’s chat!
        if not task:
            task = conversation_context.ask(prompt=prompt, chain=chain, name=nickname)
        async for rendered in task:
            if rendered:
                if not str(rendered).strip():
                    logger.warning("Output with empty content detected, ignored")
                    continue
                action = lambda session_id, prompt, rendered, respond: respond(rendered)
                for m in middlewares:
                    action = wrap_respond(action, m)

                # handle_response
                await action(session_id, prompt, rendered, respond)
        for m in middlewares:
            await m.handle_respond_completed(session_id, prompt, respond)

    try:
        if not message.strip():
            return await respond(config.response.placeholder)

        for r in config.trigger.ignore_regex:
            if re.match(r, message):
                logger.debug(f"re {r}")
                return

        # 
        conversation_handler = await ConversationHandler.get_handler(session_id)
        # 
        if ' ' in message and (config.trigger.allow_switching_ai or is_manager):
            for ai_type, prefixes in config.trigger.prefix_ai.items():
                for prefix in prefixes:
                    if f'{prefix} ' in message:
                        conversation_context = await conversation_handler.first_or_create(ai_type)
                        message = message.removeprefix(f'{prefix} ')
                        break
                else:
                    # Continue if the inner loop wasn't broken.
                    continue
                # Inner loop was broken, break the outer.
                break
        if not conversation_handler.current_conversation:
            conversation_handler.current_conversation = await conversation_handler.create(
                config.response.default_ai)

        action = request
        for m in middlewares:
            action = wrap_request(action, m)

        # 
        await action(session_id, message.strip(), conversation_context, respond)
    except DrawingFailedException as e:
        logger.exception(e)
        await _respond(config.response.error_drawing.format(exc=e.__cause__ or 'unknown'))
    except CommandRefusedException as e:
        await _respond(str(e))
    except openai.error.InvalidRequestError as e:
        await _respond(f"InvalidRequestError {str(e)}")
    except BotOperationNotSupportedException:
        await _respond("BotOperationNotSupportedException")
    except ConcurrentMessageException as e:  # Chatbot 
        await _respond(config.response.error_request_concurrent_error)
    except BotRatelimitException as e:  # Chatbot
        await _respond(config.response.error_request_too_many.format(exc=e))
    except NoAvailableBotException as e:  #
        await _respond(f"NoAvailableBotException AI")
    except BotTypeNotFoundException as e:  #
        respond_msg = f"AI {e} BotTypeNotFoundException\n"
        respond_msg += botManager.bots_info()
        await _respond(respond_msg)
    except PresetNotFoundException:  # 
        await _respond("PresetNotFoundException")
    except (RequestException, SSLError, ProxyError, MaxRetryError, ConnectTimeout, ConnectTimeout,
            httpcore.ReadTimeout, httpx.TimeoutException) as e:  # 
        await _respond(config.response.error_network_failure.format(exc=e))
    except Exception as e:  # 
        logger.exception(e)
        await _respond(config.response.error_format.format(exc=e))