from __future__ import annotations

import os
import sys
from typing import List, Union, Literal, Dict, Optional

import toml
from charset_normalizer import from_bytes
from loguru import logger
from pydantic import BaseModel, BaseConfig, Extra


class TelegramBot(BaseModel):
    bot_token: str
    """Bot token"""
    proxy: Optional[str] = None
    """login:pass@ip:port"""
    manager_chat: Optional[int] = None
    """chat id"""


class DiscordBot(BaseModel):
    bot_token: str
    channel_id: int
    """Discord Bot token"""


class HttpService(BaseModel):
    host: str
    """0.0.0.0"""
    port: int
    """Http service port, 8080"""
    debug: bool = True
    """debug status"""


class OpenAIParams(BaseModel):
    temperature: float = 0.5
    max_tokens: int = 4000
    top_p: float = 1.0
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0
    min_tokens: int = 1000
    compressed_session: bool = False
    compressed_tokens: int = 1000
    stream: bool = True


class OpenAIAuths(BaseModel):
    api_endpoint: Optional[str] = 'https://api.openai.com/v1'
    """OpenAI API"""

    gpt_params: OpenAIParams = OpenAIParams()

    accounts:List[Union[OpenAIEmailAuth, OpenAISessionTokenAuth, OpenAIAccessTokenAuth, OpenAIAPIKey]] = []


class OpenAIAuthBase(BaseModel):
    mode: str = "browserless"
    proxy: Union[str, None] = None
    """ip"""
    driver_exec_path: Union[str, None] = None
    """Chromedriver"""
    browser_exec_path: Union[str, None] = None
    """Chrome """
    conversation: Union[str, None] = None
    """UUID"""
    paid: bool = False
    gpt4: bool = False
    """GPT-4"""
    model: Optional[str] = None
    """model version"""
    verbose: bool = False
    """verbose status"""
    title_pattern: str = ""
    """title"""
    auto_remove_old_conversations: bool = False
    """auto_remove_old_conversations"""

    class Config(BaseConfig):
        extra = Extra.allow

class OpenAIEmailAuth(OpenAIAuthBase):
    email: str
    """OpenAI """
    password: str
    """OpenAI """
    isMicrosoftLogin: bool = False
    """ Microsoft """


class OpenAISessionTokenAuth(OpenAIAuthBase):
    session_token: str
    """OpenAI session_token"""


class OpenAIAccessTokenAuth(OpenAIAuthBase):
    access_token: str
    """OpenAI access_token"""


class OpenAIAPIKey(OpenAIAuthBase):
    api_key: str = "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"
    """OpenAI api_key"""


class TextToImage(BaseModel):
    always: bool = False
    """always"""
    default: bool = False
    """default"""
    font_size: int = 30
    """font_size"""
    width: int = 1000
    """width"""
    font_path: str = "fonts/sarasa-mono-sc-regular.ttf"
    """font_path"""
    offset_x: int = 50
    """offset_x"""
    offset_y: int = 50
    """offset_y"""
    wkhtmltoimage: Union[str, None] = None


class TextToSpeech(BaseModel):
    always: bool = False
    """always"""
    engine: str = "azure"
    """engine"""
    default: str = "en-US-JennyNeural"
    """voice"""
    default_voice_prefix: List[str] = ["en-US", "en-US"]
    """default_voice_prefix"""


class AzureConfig(BaseModel):
    tts_speech_key: Optional[str] = None
    """TTS KEY"""
    tts_speech_service_region: Optional[str] = None
    """TTS Region"""



class Trigger(BaseModel):
    prefix: List[str] = [""]
    """The global trigger response prefix is also suitable for private and group chats, and is not required by default."""
    prefix_friend: List[str] = []
    """The trigger response prefix in the private chat is not required by default."""
    prefix_group: List[str] = []
    """The trigger response prefix in the group chat is not required by default."""

    prefix_ai: Dict[str, List[str]] = {}
    """The prefix of a specific type of AI, starting with the prefix, will send a message directly to the specified AI session."""

    require_mention: Literal["at", "mention", "none"] = "at"
    """In the group requires @bot to respond"""
    reset_command: List[str] = ["reset"]
    """Command to reset the session"""
    rollback_command: List[str] = ["rollback"]
    """The command to roll back the session"""
    prefix_image: List[str] = ["draw", "нарисуй"]
    """Image creation prefix"""
    switch_model: str = r"switch_model (.+)"
    """Switch the model of the current context"""
    switch_command: str = r"switch_command (.+)"
    """Commands to switch AI"""
    switch_voice: str = r"switch_voice (.+)"
    """Command to switch tts voice"""
    mixed_only_command: List[str] = ["mixed_"]
    """Switch to graphic and text mixing mode"""
    image_only_command: List[str] = ["image"]
    """image_only_command"""
    text_only_command: List[str] = ["text_"]
    """text_only_command"""
    ignore_regex: List[str] = []
    """ignore_regex"""
    allowed_models: List[str] = [
        "gpt-3.5-turbo-16k-0613",
        "gpt-3.5-turbo-1106"
    ]
    """allowed_models"""
    allow_switching_ai: bool = True
    """allow_switching_ai"""
    ping_command: List[str] = ["ping"]
    """ping_command"""


class Response(BaseModel):
    mode: str = "mixed"
    """mixed - mixed, force-text - force-text, force-image - force-image"""

    buffer_delay: float = 15
    """buffer_delay"""

    default_ai: Union[str, None] = None
    """default_ai"""

    error_format: str = "There is a failure! If this problem persists, please tell me to `reset` to start a new session, or send the `rollback`, and I will regard what you said in the last one as if I didn't see it. \nThe reason: {exc}"
    """error_format"""

    error_network_failure: str = "error_network_failure \n{exc}"
    """error_network_failure"""

    error_session_authenciate_failed: str = "error_session_authenciate_failed \n{exc}"
    """error_session_authenciate_failed"""

    error_request_too_many: str = "error_request_too_many \nBody {exc}(Code: 429)\n"

    error_request_concurrent_error: str = "error_request_concurrent_error"

    error_server_overloaded: str = "error_server_overloaded"
    """error_server_overloaded 429"""

    error_drawing: str = "error_drawing: {exc}"

    placeholder: str = (
        "Hello! I'm Assistant, a large language model trained by OpenAI. I'm not a real person, but a computer program that can help you solve problems through text chat. If you have any questions, please feel free to let me know and I will try my best to answer them.\n"
        "If you need to reset our session, please reply `Reset Session`."
    )
    """The placeholder for replying to empty messages"""

    reset = "The session has been reset."
    """reset"""

    rollback_success = "I have rolled back to the previous conversation, and I forgot what you just sent."
    """rollback_success"""

    rollback_fail = "The rollback failed, and there was no earlier record! If you want to start over, please send: {reset}"
    """rollback_fail"""

    quote: bool = True
    """Do you reply to the triggered message?"""

    timeout: float = 30.0
    """timeout"""

    timeout_format: str = "I'm still thinking. Please wait a little longer~"
    """timeout_format"""

    max_timeout: float = 600.0
    """max_timeout"""

    cancel_wait_too_long: str = "Ah, this question is a little difficult. I haven't figured it out for a long time. Try to ask another question?"
    """cancel_wait_too_long"""

    max_queue_size: int = 10
    """The maximum number of messages waiting to be processed. If you want to turn off this function, set it to 0."""

    queue_full: str = "Sorry! There are a lot of people need to reply now, and I can't receive new messages at this time. Please send it to me later!"
    """queue_full"""

    queued_notice_size: int = 3
    """The minimum length of the notification will be sent when the new message is added to the queue."""

    queued_notice: str = "The message has been received! At present, I still have {queue_size} messages to reply to. Please wait a moment. "
    """ queued_notice : queue_size """

    ping_response: str = "AI {current_ai} / current_voice: {current_voice}" \
                         "\nAI \n{supported_ai}"
    """ping"""
    ping_tts_response: str = "\nAvailable voice: \n{supported_tts}"
    """ping tts"""


class System(BaseModel):
    accept_group_invite: bool = False
    """Automatically receive invitation requests"""

    accept_friend_request: bool = False
    """Automatically receive friend requests"""

    auto_reset_timeout_seconds: int = 8 * 3600
    """How long will the session be idle and then it will be reset? -1 will not be reset."""


class Preset(BaseModel):
    command: str = r"Load (\w+)"
    keywords: dict[str, str] = {}
    loaded_successful: str = "The preset is loaded successfully!"
    scan_dir: str = "./presets"
    hide: bool = False
    """Is it forbidden to use others? Preset list command to view presets"""


class Ratelimit(BaseModel):
    warning_rate: float = 0.8
    """Ratelimit"""

    warning_msg: str = "\n\nWarning: The quota is about to run out! \n Currently sent: {usage} messages, the maximum limit is {limit} messages/hour, please adjust your rhythm. \n The quota limit is reset at the hour, and the current server time: {current_time}"
    """warning_msg"""

    exceed: str = "The quota limit has been reached. Please wait for the next hour to continue talking to me."
    """exceed"""

    draw_warning_msg: str = "\n\nWarning: The quota is about to run out! \nAt present, it has been drawn: {usage} pictures, the maximum limit is {limit} pictures/hour, please adjust your rhythm. \nThe quota limit is reset at the hour, and the current server time: {current_time}"
    """draw_warning_msg"""

    draw_exceed: str = "The quota limit has been reached. Please wait for the next hour before using the drawing function."
    """draw_exceed"""

class SDWebUI(BaseModel):
    api_url: str
    """API http://127.0.0.1:7890"""
    prompt_prefix: str = 'masterpiece, best quality, illustration, extremely detailed 8K wallpaper'
    """xxx"""
    negative_prompt: str = 'NG_DeepNegative_V1_75T, badhandv4, EasyNegative, bad hands, missing fingers, cropped legs, worst quality, low quality, normal quality, jpeg artifacts, blurry,missing arms, long neck, Humpbacked,multiple breasts, mutated hands and fingers, long body, mutation, poorly drawn , bad anatomy,bad shadow,unnatural body, fused breasts, bad breasts, more than one person,wings on halo,small wings, 2girls, lowres, bad anatomy, text, error, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, out of frame, lowres, text, error, cropped, worst quality, low quality, jpeg artifacts, ugly, duplicate, morbid, mutilated, out of frame, extra fingers, mutated hands, poorly drawn hands, poorly drawn face, mutation, deformed, dehydrated, bad anatomy, bad proportions, extra limbs, cloned face, disfigured, gross proportions, malformed limbs, missing arms, missing legs, extra arms, extra legs, fused fingers, too many fingers, nsfw, nake, nude, blood'
    """xx"""
    sampler_index: str = 'DPM++ SDE Karras'
    filter_nsfw: bool = True
    denoising_strength: float = 0.45
    steps: int = 25
    enable_hr: bool = False
    seed: int = -1
    batch_size: int = 1
    n_iter: int = 1
    cfg_scale: float = 7.5
    restore_faces: bool = False
    authorization: str = ''
    """xx:xx"""

    timeout: float = 10.0
    """xx"""

    class Config(BaseConfig):
        extra = Extra.allow

class Config(BaseModel):
    # === Platform Settings ===
    telegram: Optional[TelegramBot] = None
    discord: Optional[DiscordBot] = None
    http: Optional[HttpService] = None

    # === Account Settings ===
    openai: OpenAIAuths = OpenAIAuths()
    azure: AzureConfig = AzureConfig()


    # === Response Settings ===
    text_to_image: TextToImage = TextToImage()
    text_to_speech: TextToSpeech = TextToSpeech()
    trigger: Trigger = Trigger()
    response: Response = Response()
    system: System = System()
    presets: Preset = Preset()
    ratelimit: Ratelimit = Ratelimit()

     # === External Utilities ===
    sdwebui: Optional[SDWebUI] = None

    def scan_presets(self):
        for keyword, path in self.presets.keywords.items():
            if os.path.isfile(path):
                logger.success(f"Check the presets: {keyword} <==> {path} [Success]")
            else:
                logger.error(f"Check the presets: {keyword} <==> {path} [Failure: The file does not exist]")
        for root, _, files in os.walk(self.presets.scan_dir, topdown=False):
            for name in files:
                if not name.endswith(".txt"):
                    continue
                path = os.path.join(root, name)
                name = name.removesuffix('.txt')
                if name in self.presets.keywords:
                    logger.error(f"Registration preset: {name} <==> {path} [Failure: Keywords already exist]")
                    continue
                self.presets.keywords[name] = path
                logger.success(f"Registration preset: {name} <==> {path} [Success]")

    def load_preset(self, keyword):
        try:
            with open(self.presets.keywords[keyword], "rb") as f:
                if guessed_str := from_bytes(f.read()).best():
                    return str(guessed_str).replace('<|im_end|>', '').replace('\r', '').split('\n\n')
                else:
                    raise ValueError("The preset JSON format cannot be recognized, please check the encoding.")

        except KeyError as e:
            raise ValueError("The preset does not exist.") from e
        except FileNotFoundError as e:
            raise ValueError("The preset file does not exist.") from e
        except Exception as e:
            logger.exception(e)
            logger.error("The configuration file is wrong, please modify it again.")

    OpenAIAuths.update_forward_refs()

    @staticmethod
    def __load_json_config() -> Config:
        try:
            import json
            with open("config.json", "rb") as f:
                if guessed_str := from_bytes(f.read()).best():
                    return Config.parse_obj(json.loads(str(guessed_str)))
                else:
                    raise ValueError("JSON ValueError")
        except Exception as e:
            logger.exception(e)
            logger.error("Exception")
            exit(-1)

    @staticmethod
    def load_config() -> Config:
        if env_config := os.environ.get('CHATGPT_FOR_BOT_FULL_CONFIG', ''):
            return Config.parse_obj(toml.loads(env_config))
        try:
            if (
                    not os.path.exists('config.cfg')
                    or os.path.getsize('config.cfg') <= 0
            ) and os.path.exists('config.json'):
                logger.info("Converting the old version of the configuration file")
                Config.save_config(Config.__load_json_config())
                logger.warning("Tip: The configuration file has been modified to config.cfg, The original config.json, It will be renamed to config.json.old")
                try:
                    os.rename('config.json', 'config.json.old')
                except Exception as e:
                    logger.error(e)
                    logger.error("Exception")
            with open("config.cfg", "rb") as f:
                if guessed_str := from_bytes(f.read()).best():
                    return Config.parse_obj(toml.loads(str(guessed_str)))
                else:
                    raise ValueError("The configuration file cannot be recognized. Please check if the input is wrong.")
        except Exception as e:
            logger.exception(e)
            logger.error("The configuration file is wrong, please modify it again.")
            exit(-1)

    @staticmethod
    def save_config(config: Config):
        try:
            with open("config.cfg", "wb") as f:
                parsed_str = toml.dumps(config.dict()).encode(sys.getdefaultencoding())
                f.write(parsed_str)
        except Exception as e:
            logger.exception(e)
            logger.warning("Configuration save failed")