import asyncio
from loguru import logger
from constants import config

try:
    from graiax import silkcoder


    async def encode_to_silk(input_data: bytes) -> bytes:
        return await silkcoder.async_encode(
            input_data,
            audio_format=None,
            ios_adaptive=True
        )
except ImportError as e:
    async def encode_to_silk(a=None):
        logger.warning("Warning: The Silk transcoding module cannot be loaded and the voice may not play properly. Please install the latest vc_redist runtime library.")
        return a
    if config.text_to_speech.engine == 'azure':
        asyncio.run(encode_to_silk())


try:
    import azure.cognitiveservices.speech as speechsdk


    async def synthesize_speech(text: str, output_file: str,
                                voice):
        if not config.azure.tts_speech_key:
            logger.warning("[Azure TTS] tts_speech_key is not detected, no speech conversion is performed.")
            return False
        loop = asyncio.get_event_loop()
        future = loop.create_future()

        def create_synthesizer():
            speech_key, service_region = config.azure.tts_speech_key, config.azure.tts_speech_service_region
            speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)
            # https://learn.microsoft.com/en-us/azure/cognitive-services/speech-service/language-support?tabs=tts#neural-voices
            speech_config.set_property(speechsdk.PropertyId.SpeechServiceConnection_SynthVoice, voice.full_name)
            audio_config = speechsdk.audio.AudioOutputConfig(filename=output_file)
            return speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)

        # result = await asyncio.get_event_loop().run_in_executor(None, synthesizer.speak_text_async(text).get)
        # result = synthesizer.speak_text_async(text).get()
        synthesizer = await loop.run_in_executor(None, create_synthesizer)
        loop.call_soon_threadsafe(run_synthesize_speech, synthesizer, text, future)

        return await future


    def run_synthesize_speech(synthesizer, text, future):
        result = synthesizer.speak_text_async(text).get()
        future.set_result(result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted)

except FileNotFoundError as e:
    async def synthesize_speech(a=None, b=None, c=None):
        logger.error("Error: Azure TTS service cannot be loaded, please install the latest vc_redist runtime.")
        logger.error("Reference link:")
        return None
    if config.text_to_speech.engine == 'azure':
        asyncio.run(synthesize_speech())