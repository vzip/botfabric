import os
import sys
import creart
sys.path.append(os.getcwd())
from asyncio import AbstractEventLoop
import asyncio
from utils.exithooks import hook
from loguru import logger
from constants import config, botManager


loop = creart.create(AbstractEventLoop)

loop.run_until_complete(botManager.login())

bots = []


if config.telegram:
    logger.info("telegram bot")
    from platforms.telegram_bot import start_task

    bots.append(loop.create_task(start_task()))
    
if config.discord:
    logger.info("discord bot")
    from platforms.discord_bot import start_task

    bots.append(loop.create_task(start_task()))

if config.http:
    logger.info("http service")
    from platforms.http_service import start_task

    bots.append(loop.create_task(start_task()))


hook()
loop.run_until_complete(asyncio.gather(*bots))
loop.run_forever()