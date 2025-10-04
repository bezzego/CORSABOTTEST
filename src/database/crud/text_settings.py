from sqlalchemy import select, update
from src.logs import getLogger
from src.database.database import AsyncSessionLocal
from src.database.models import UsersOrm, TariffsOrm, PromoOrm, ServersOrm, KeysOrm, TextSettingsOrm, BannedOrm, AdminsOrm

logger = getLogger(__name__)


async def get_text_settings(pk_id: int = 1) -> TextSettingsOrm:
    """Получение записи в TextSettingsOrm"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(TextSettingsOrm).where(TextSettingsOrm.id == pk_id))
        return result.scalar()


async def change_settings_value(**kwargs):
    """Изменение параметра тарифа"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            pk_id = 1
            stmt = update(TextSettingsOrm).where(TextSettingsOrm.id == pk_id).values(**kwargs).returning(TextSettingsOrm)
            result = await session.execute(stmt)
            logger.debug(f"Change text settings {kwargs}: {result.scalar()}")


async def update_faq_list(new_list: list):
    """Обновление faq списка"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(select(TextSettingsOrm).where(TextSettingsOrm.id == 1))
            settings = result.scalar()
            settings.faq_list = new_list
            logger.debug(f"Update faq_list: {settings.faq_list}")
            await session.commit()


async def update_test_sub(new_hours: int):
    """Обновление количества часов"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(select(TextSettingsOrm).where(TextSettingsOrm.id == 1))
            settings = result.scalar()
            settings.test_hours = int(new_hours)
            logger.debug(f"Update test_hours: {settings.test_hours}")
            await session.commit()
