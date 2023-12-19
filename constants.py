from enum import Enum

from config import Config
from manager.bot import BotManager

config = Config.load_config()
config.scan_presets()

botManager = BotManager(config)


class LlmName(Enum):
    ChatGPT_Api = "chatgpt-api"
    Bing = "bing"


class BotPlatform(Enum):
    DiscordBot = "discord"
    TelegramBot = "telegram"
    HttpService = "http"