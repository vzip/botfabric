import asyncio
from loguru import logger


def retry(exceptions, tries=4, delay=3, backoff=2):
    """
    Exponential retry decorator function for async methods
    :param exceptions: Exception type, which can be a single type or a tuple type
    :param tries: Maximum number of retries, default is 4
    :param delay: Initial retry delay time, default is 3 seconds
    :param backoff: Retry delay time increase multiplier, default is 2
    :return: Decorator function
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            _tries = tries
            _delay = delay
            while _tries > 0:
                try:
                    async for result in func(*args, **kwargs):
                        yield result
                    return
                except exceptions as e:
                    logger.exception(e)
                    logger.error(f"An error was encountered while processing the request, which will be {_delay} Try again in seconds...")
                    await asyncio.sleep(_delay)
                    _tries -= 1
                    _delay *= backoff
            async for result in func(*args, **kwargs):
                yield result

        return wrapper

    return decorator