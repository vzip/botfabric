import os
from enum import Enum

from tempfile import NamedTemporaryFile
from typing import Optional

from graia.ariadne.message.element import Plain, Voice
from loguru import logger

from constants import config
from utils.azure_tts import synthesize_speech, encode_to_silk

tts_voice_dic = {}
"""Sound list for each engine"""


class VoiceType(Enum):
    Wav = "wav"
    Mp3 = "mp3"
    Silk = "silk"


class TtsVoice:

    def __init__(self):
        self.engine = None
        """Ref: edge, azure, vits"""
        self.gender = None
        """Ref: Male, Female"""
        self.full_name = None
        """Ref: en-US-JennyMultilingualNeural"""
        self.lang = None
        """Ref: en, ru, sp"""
        self.region = None
        """Ref:US, UK, MX"""
        self.name = None
        """Ref: Jenny Multilingual"""
        self.alias = None
        """Ref: jenny"""
        self.sub_region = None
        """Ref: la"""

    def description(self):
        return f"{self.alias}: {self.full_name}{f' - {self.gender}' if self.gender else ''}"

    @staticmethod
    def parse(engine, voice: str, gender=None):
        tts_voice = TtsVoice()
        tts_voice.engine = engine
        tts_voice.full_name = voice
        tts_voice.gender = gender
        if engine in ["edge", "azure"]:
            """en-US-JennyMultilingualNeural"""
            voice_info = voice.split("-")
            if len(voice_info) < 3:
                return None
            lang = voice_info[0]
            region = voice_info[1]
            if len(voice_info) == 4:
                sub_region = voice_info[2]
                name = voice_info[3]
            else:
                sub_region = None
                name = voice_info[2]
            alias = name.replace("Neural", "").lower()
            tts_voice.lang = lang
            tts_voice.region = region
            tts_voice.name = name
            tts_voice.alias = alias
            tts_voice.sub_region = sub_region
        else:
            tts_voice.lang = voice
            tts_voice.alias = voice

        return tts_voice


class TtsVoiceManager:
    """tts"""

    @staticmethod
    def parse_tts_voice(tts_engine, voice_name) -> TtsVoice:
        if tts_engine != "edge":
            # todo support other engines
            return TtsVoice.parse(tts_engine, voice_name)
        
        
        _voice_dic = tts_voice_dic["edge"]
        if _voice := TtsVoice.parse(tts_engine, voice_name):
            return _voice_dic.get(_voice.alias, None)
        if voice_name in _voice_dic:
            return _voice_dic[voice_name]

    @staticmethod
    async def list_tts_voices(tts_engine, voice_prefix):
        """list_tts_voices"""

        def match_voice_prefix(full_name):
            if isinstance(voice_prefix, str):
                return full_name.startswith(voice_prefix)
            if isinstance(voice_prefix, list):
                for _prefix in voice_prefix:
                    if full_name.startswith(_prefix):
                        return True
                return False

            _voice_dic = tts_voice_dic["edge"]
            return [v for v in _voice_dic.values() if voice_prefix is None or match_voice_prefix(v.full_name)]
        # todo support other engines
        return []


async def get_tts_voice(elem, conversation_context, voice_type=VoiceType.Wav) -> Optional[Voice]:
    if not isinstance(elem, Plain) or not str(elem):
        return None

    voice_suffix = f".{voice_type.value}"

    output_file = NamedTemporaryFile(mode='w+b', suffix=voice_suffix, delete=False)
    output_file.close()

    logger.debug(f"[TextToSpeech]  - {conversation_context.session_id}")
    if config.text_to_speech.engine == "azure":
        tts_output_file_name = (f"{output_file.name}.{VoiceType.Wav.value}"
                                if voice_type == VoiceType.Silk else output_file.name)
        if await synthesize_speech(
                str(elem),
                tts_output_file_name,
                conversation_context.conversation_voice
        ):
            voice = Voice(path=tts_output_file_name)
            if voice_type == VoiceType.Silk:
                voice = Voice(data_bytes=await encode_to_silk(await voice.get_bytes()))

            logger.debug(f"[TextToSpeech]  - {output_file.name} - {conversation_context.session_id}")
            return voice

    else:
        raise ValueError("The text-to-audio engine does not exist. Please check whether the configuration file is correct.")