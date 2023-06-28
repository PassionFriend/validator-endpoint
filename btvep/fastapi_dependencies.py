import concurrent.futures
import json
import logging
from datetime import datetime
from math import ceil
from typing import Annotated
import openai

import redis.asyncio
import rich
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter

from btvep.config import Config
from btvep.constants import COST
from btvep.db.api_keys import ApiKey
from btvep.db.api_keys import get_by_key as get_api_key_by_key
from btvep.db.api_keys import update as update_api_key
from btvep.db.request import Request as DBRequest
from btvep.db.utils import db, db_state_default

config = Config().load()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


from starlette.requests import Request
from starlette.responses import Response


async def reset_db_state():
    db._state._state.set(db_state_default.copy())
    db._state.reset()


def get_db(db_state=Depends(reset_db_state)):
    try:
        db.connect()
        yield
    finally:
        if not db.is_closed():
            db.close()


async def InitializeRateLimiting():
    try:
        redis_instance = redis.asyncio.from_url(
            config.redis_url, encoding="utf-8", decode_responses=True
        )

        async def rate_limit_identifier(request: Request):
            return request.headers.get("Authorization").split(" ")[1]

        await FastAPILimiter.init(redis_instance, identifier=rate_limit_identifier)
    except redis.asyncio.ConnectionError as e:
        rich.print(
            f"[red]ERROR:[/red] Could not connect to redis on [cyan]{config.redis_url}[/cyan]\n [red]Redis is required for rate limiting.[/red]"
        )
        raise e


filter = None
if config.openai_filter_enabled:
    if config.openai_api_key is None:
        raise Exception("OpenAI filter enabled, but openai_api_key is not set.")
    from btvep.filter import OpenAIFilter

    filter = OpenAIFilter(config.openai_api_key)


async def authenticate_api_key(
    request: Request, input_api_key: str = Depends(oauth2_scheme)
) -> ApiKey:
    def raiseKeyError(detail: str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )

    async def createErrorRequest(error: str):
        DBRequest.create(
            is_api_success=False,
            api_error=error,
            prompt=json.dumps((await request.json())["messages"]),
            api_key=input_api_key,
        )

    if (input_api_key is None) or (input_api_key == ""):
        createErrorRequest("APIKeyMissing")
        raiseKeyError("Missing API key")

    api_key = get_api_key_by_key(input_api_key)
    if api_key is None:
        createErrorRequest("APIKeyInvalid")
        raiseKeyError("Invalid API key")

    elif api_key.enabled == 0:
        createErrorRequest("APIKeyDisabled")
        raiseKeyError("API key is disabled")
    elif (api_key.valid_until != -1) and (
        api_key.valid_until < datetime.now().timestamp()
    ):
        createErrorRequest("APIKeyExpired")
        raiseKeyError(
            "API key has expired as of "
            + str(datetime.utcfromtimestamp(api_key.valid_until))
        )
    elif not api_key.has_unlimited_credits() and api_key.credits - COST < 0:
        createErrorRequest("APIKeyNotEnoughCredits")
        raiseKeyError("Not enough credits")

    ###  API key is now validated. ###

    if filter:
        messages = (await request.json())["messages"]
        messageContents = [message["content"] for message in messages]
        try:
            check_res = filter.safe_check(messageContents)
            if check_res["any_flagged"]:
                createErrorRequest("FlaggedByOpenAIModerationFilter")
                raiseKeyError("OpenAI moderation filter triggered")
        except concurrent.futures.TimeoutError as e:
            logging.warning("OpenAI filter timed out. Allowing request.")
            pass
        except openai.error.AuthenticationError:
            logging.warning("OpenAI filter auth error. Allowing request.")
            pass

    # Subtract cost if not unlimited
    credits = None if api_key.has_unlimited_credits() else api_key.credits - COST

    # Increment request count and potentially credits
    update_api_key(
        api_key.api_key,
        request_count=api_key.request_count + 1,
        credits=credits,
    )

    return api_key


def get_rate_limits(api_key: str = None) -> list[RateLimiter]:
    """Get rate limits. Leave api_key as None to get global rate limits."""

    if not config.rate_limiting_enabled:
        return []
    rate_limits = None
    if api_key is not None:
        rate_limits = json.loads(api_key.rate_limits)
    elif config.rate_limiting_enabled:
        rate_limits = config.global_rate_limits

    HTTP_429_TOO_MANY_REQUESTS = 429

    async def ratelimit_callback(request, response, pexpire, limit):
        print(
            f"Rate limit triggered for ratelimit rule: {limit}",
        )

        DBRequest.create(
            is_api_success=False,
            api_error="RateLimitExceeded",
            prompt=json.dumps((await request.json())["messages"]),
            api_key=request.headers.get("authorization").split(" ")[1],
        )

        expire = ceil(pexpire / 1000)

        raise HTTPException(
            HTTP_429_TOO_MANY_REQUESTS,
            "Too Many Requests",
            headers={"Retry-After": str(expire)},
        )

    rate_limiters = [
        RateLimiter(
            times=limit["times"],
            seconds=limit["seconds"],
            callback=lambda request, response, pexpire: ratelimit_callback(
                request, response, pexpire, limit
            ),
        )
        for limit in rate_limits
    ]

    # Sort the list in ascending order by the ratio of milliseconds to times
    sorted_rate_limiters = sorted(
        rate_limiters, key=lambda rl: rl.milliseconds / rl.times
    )

    return sorted_rate_limiters


global_rate_limits = get_rate_limits()


def VerifyAndLimit():
    async def a(
        request: Request,
        response: Response,
        api_key: Annotated[ApiKey, Depends(authenticate_api_key)],
    ):
        for ratelimit in (
            get_rate_limits(api_key)
            if api_key and api_key.rate_limits
            else global_rate_limits
        ):
            await ratelimit(request, response)

    return a
