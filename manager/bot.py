import asyncio
import base64
import hashlib
import itertools
import json
import os
import re
import time
import urllib.request
from typing import List, Dict
from urllib.parse import urlparse

import httpx
import openai
import regex
import requests
import urllib3.exceptions
from aiohttp import ClientConnectorError
from httpx import ConnectTimeout
from loguru import logger

from requests.exceptions import SSLError, RequestException

from tinydb import TinyDB, Query

import utils.network as network


from config import OpenAIAuthBase, OpenAIAPIKey, Config

from exceptions import NoAvailableBotException, APIKeyNoFundsError


class BotManager:
    """Bot lifecycle manager."""

    bots: Dict[str, List] = {
        "openai-api": [],
    }
    """Bot list"""

    openai: List[OpenAIAuthBase]
    """OpenAI Account infos"""


    roundrobin: Dict[str, itertools.cycle] = {}

    def __init__(self, config: Config) -> None:
        self.config = config
        self.openai = config.openai.accounts if config.openai else []
        

        try:
            os.mkdir('data')
            logger.warning(
                "Warning: The data directory is not detected if you pass Docker Deployment, please mount this directory for login caching, otherwise you can ignore this message.")
        except Exception:
            pass
        self.cache_db = TinyDB('data/login_caches.json')

    async def handle_openai(self):
        # Considering that someone may write the wrong global configuration
        for account in self.config.openai.accounts:
            account = account.dict()
            if 'api_endpoint' in account:
                logger.warning("Warning: api_endpoint The configuration location is wrong and is being adjusted to global configuration.")
                self.config.openai.api_endpoint = account['api_endpoint']

        # api_endpoint
        if self.config.openai.api_endpoint:
            openai.api_base = self.config.openai.api_endpoint or openai.api_base
            if openai.api_base.endswith("/"):
                openai.api_base.removesuffix("/")
        logger.info(f"Current api_endpoint is：{openai.api_base}")

        pattern = r'^https://[^/]+/v1$'

        if not re.match(pattern, openai.api_base):
            logger.error("API wrong address is incorrectly filled in. The correct format should be 'https://<URL>/v1'")

        await self.login_openai()

    async def login(self):
        self.bots = {
            "openai-api": [],
        }

        self.__setup_system_proxy()

        login_funcs = {
            'openai': self.handle_openai,
        }

        for key, login_func in login_funcs.items():
            if hasattr(self, key) and len(getattr(self, key)) > 0:
                if asyncio.iscoroutinefunction(login_func):
                    await login_func()
                else:
                    login_func()

        count = sum(len(v) for v in self.bots.values())

        if count < 1:
            logger.error("There is no account that has successfully logged in, and the program cannot be started.！")
            exit(-2)
        else:
            for k, v in self.bots.items():
                logger.info(f"AI type {k} - Available accounts: {len(v)} ")

        if not self.config.response.default_ai:
            # Automatic guess default AI
            default_ai_mappings = {
                "openai-api": "chatgpt-api",

            }

            self.config.response.default_ai = next(
                (
                    default_ai
                    for key, default_ai in default_ai_mappings.items()
                    if len(self.bots[key]) > 0
                ),
                'openai-api',
            )


    async def login_openai(self):  # sourcery skip: raise-specific-error
        counter = 0
        for i, account in enumerate(self.openai):
            logger.info("Login to {i} OpenAI account", i=i + 1)
            try:
                if isinstance(account, OpenAIAPIKey):
                    bot = await self.__login_openai_apikey(account)
                    self.bots["openai-api"].append(bot)
                else:
                    raise Exception(f"Undefined login type:{account.mode}")
                bot.id = i
                bot.account = account
                logger.success("login successful", i=i + 1)
                counter = counter + 1
            except httpx.HTTPStatusError as e:
                logger.error("Login failed! The account password may be incorrect, or Endpoint does not support this login method. {exc}", exc=e)
            except (
                    ConnectTimeout, RequestException, SSLError, urllib3.exceptions.MaxRetryError,
                    ClientConnectorError) as e:
                logger.error("Login failed! Failed to connect to the OpenAI server, please change the agent node and try again! {exc}", exc=e)
            except APIKeyNoFundsError:
                logger.error("Login failed! The API account balance is insufficient and cannot be used anymore.")
            except Exception as e:
                err_msg = str(e)
                if "failed to connect to the proxy server" in err_msg:
                    logger.error("{exc}", exc=e)
                elif "All login method failed" in err_msg:
                    logger.error("Login failed! All login methods have expired. Please check whether the IP, proxy or login information is correct. {exc}", exc=e)
                else:
                    logger.error("unknown err")
                    logger.exception(e)
        if len(self.bots) < 1:
            logger.error("All OpenAI accounts failed to log in!")
        logger.success(f"Successfully logged in {counter}/{len(self.openai)} OpenAI ")


    def __setup_system_proxy(self):

        system_proxy = None
        for url in urllib.request.getproxies().values():
            try:
                system_proxy = self.__check_proxy(url)
                if system_proxy is not None:
                    break
            except:
                pass
        if system_proxy is not None:
            openai.proxy = system_proxy

    def __check_proxy(self, proxy):  # sourcery skip: raise-specific-error
        if proxy is None:
            return openai.proxy
        logger.info(f"[Agent Test] Checking proxy configuration：{proxy}")
        proxy_addr = urlparse(proxy)
        if not network.is_open(proxy_addr.hostname, proxy_addr.port):
            raise Exception("Login failed! Unable to connect to the local proxy server, please check whether the proxy in the configuration file is correct！")
        requests.get("http://www.gstatic.com/generate_204", proxies={
            "https": proxy,
            "http": proxy
        })
        logger.success("[Agent Test] Connection successful！")
        return proxy

    def __save_login_cache(self, account: OpenAIAuthBase, cache: dict):
        """Save login cache"""
        account_sha = hashlib.sha256(account.json().encode('utf8')).hexdigest()
        q = Query()
        self.cache_db.upsert({'account': account_sha, 'cache': cache}, q.account == account_sha)

    def __load_login_cache(self, account):
        """Read login cache"""
        account_sha = hashlib.sha256(account.json().encode('utf8')).hexdigest()
        q = Query()
        cache = self.cache_db.get(q.account == account_sha)
        return cache['cache'] if cache is not None else {}

    async def __login_openai_apikey(self, account):
        logger.info("Trying to log in using api_key...")
        if proxy := self.__check_proxy(account.proxy):
            openai.proxy = proxy
            account.proxy = proxy
        logger.info(
            f"The currently checked API Key is：{account.api_key[:8]}******{account.api_key[-4:]}"
        )
        logger.warning("If you encounter a problem when querying the API quota, please confirm the quota yourself.")
        return account

    def pick(self, llm: str):
        if llm not in self.roundrobin:
            self.roundrobin[llm] = itertools.cycle(self.bots[llm])
        if len(self.bots[llm]) == 0:
            raise NoAvailableBotException(llm)
        return next(self.roundrobin[llm])

    def bots_info(self):
        from constants import LlmName
        bot_info = ""
        if len(self.bots['openai-api']) > 0:
            bot_info += f"* {LlmName.ChatGPT_Api.value} : OpenAI ChatGPT API\n"
        return bot_info