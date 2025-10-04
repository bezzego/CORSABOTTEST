from sqlalchemy.dialects.postgresql import insert
from src.database.database import async_engine, AsyncSessionLocal, Base
from src.database.models import UsersOrm, TariffsOrm, PromoOrm, ServersOrm, KeysOrm, TextSettingsOrm, BannedOrm, AdminsOrm


async def init_database():
    """Инициализация базы данных"""
    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    await create_default_settings_rows()


async def create_default_settings_rows():
    """Создание дефолтных текстовых настроек в бд"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = insert(TextSettingsOrm).values(id=1)
            stmt = stmt.on_conflict_do_nothing(index_elements=["id"])
            await session.execute(stmt)
