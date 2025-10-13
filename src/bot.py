import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from src.database.crud import init_database
from src.handlers.user_handlers import user_routers
from src.handlers.admin_handlers import admin_routers
from src.logs import getLogger
from src.config import settings
from src.services.scheduler import start_scheduler

aiogram_logger = getLogger("aiogram.event")
aiogram_logger.setLevel("WARNING")


dp = Dispatcher(storage=MemoryStorage())
logger = getLogger(__name__)


async def main():
    bot = Bot(token=settings.telegram.token)
    await bot.delete_webhook(drop_pending_updates=True)
    await init_database()
    await start_scheduler(bot)
    dp.include_routers(*user_routers, *admin_routers)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
