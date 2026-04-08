from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass

from aiogram import Bot, Dispatcher
from fastapi import FastAPI

from app.bot.factory import create_bot, create_dispatcher
from app.core.config import Settings
from app.core.constants import POLLING_TASK_NAME
from app.infra.database import Database, create_database, dispose_database

logger = logging.getLogger(__name__)

LOG_EVENT_POLLING_STARTED = "telegram_polling_started"
LOG_EVENT_POLLING_CANCELLED = "telegram_polling_cancelled"
LOG_EVENT_POLLING_STOPPED = "telegram_polling_stopped"
LOG_EVENT_POLLING_FAILED = "telegram_polling_failed"
LOG_EVENT_STARTUP_BEGIN = "application_startup_begin"
LOG_EVENT_STARTUP_COMPLETE = "application_startup_complete"
LOG_EVENT_SHUTDOWN_BEGIN = "application_shutdown_begin"
LOG_EVENT_SHUTDOWN_COMPLETE = "application_shutdown_complete"


@dataclass(slots=True)
class RuntimeState:
    """Lifecycle-owned runtime resources that must be closed on shutdown."""

    database: Database | None = None
    bot: Bot | None = None
    dispatcher: Dispatcher | None = None
    polling_task: asyncio.Task[None] | None = None
    polling_exception: BaseException | None = None


async def _run_polling_loop(dispatcher: Dispatcher, bot: Bot) -> None:
    """Run Telegram long polling until cancelled by application shutdown."""

    logger.info(LOG_EVENT_POLLING_STARTED)
    try:
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    except asyncio.CancelledError:
        logger.info(LOG_EVENT_POLLING_CANCELLED)
        raise
    finally:
        logger.info(LOG_EVENT_POLLING_STOPPED)


def _record_polling_failure(state: RuntimeState, task: asyncio.Task[None]) -> None:
    """Persist unexpected polling task failures so readiness checks can react."""

    if state.polling_exception is not None or task.cancelled():
        return

    try:
        exception = task.exception()
    except asyncio.CancelledError:
        return

    if exception is None:
        exception = RuntimeError("Telegram polling stopped unexpectedly.")
        logger.error("%s reason=unexpected_stop", LOG_EVENT_POLLING_FAILED)
    else:
        logger.error(
            LOG_EVENT_POLLING_FAILED,
            exc_info=(type(exception), exception, exception.__traceback__),
        )

    state.polling_exception = exception


async def _startup_runtime(state: RuntimeState, settings: Settings) -> None:
    """Initialize resources and start polling as a managed background task."""

    state.database = await create_database(settings.database_url)
    state.bot = create_bot(settings.telegram_bot_token.get_secret_value())
    state.dispatcher = create_dispatcher(
        settings.admin_user_ids,
        debug_commands_mode=settings.debug_commands_mode,
    )
    # Polling is run in a task so FastAPI can continue serving /health concurrently.
    state.polling_task = asyncio.create_task(
        _run_polling_loop(state.dispatcher, state.bot),
        name=POLLING_TASK_NAME,
    )
    state.polling_task.add_done_callback(lambda task: _record_polling_failure(state, task))


async def _shutdown_runtime(state: RuntimeState) -> None:
    """Cancel polling and close runtime resources in safe order."""

    if state.polling_task is not None:
        if not state.polling_task.done():
            state.polling_task.cancel()
            with suppress(asyncio.CancelledError):
                await state.polling_task
        _record_polling_failure(state, state.polling_task)

    if state.bot is not None:
        await state.bot.session.close()

    await dispose_database(state.database)
    logger.info(LOG_EVENT_SHUTDOWN_COMPLETE)


def create_app_lifespan(settings: Settings) -> Callable[[FastAPI], AsyncIterator[None]]:
    """Return FastAPI lifespan function that owns bot and DB lifecycle."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info(LOG_EVENT_STARTUP_BEGIN)
        state = RuntimeState()
        app.state.runtime = state

        try:
            await _startup_runtime(state, settings)
            logger.info(LOG_EVENT_STARTUP_COMPLETE)
            yield
        finally:
            logger.info(LOG_EVENT_SHUTDOWN_BEGIN)
            await _shutdown_runtime(state)

    return lifespan
