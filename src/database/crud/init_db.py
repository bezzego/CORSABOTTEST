from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from src.database.database import async_engine, AsyncSessionLocal, Base
from src.database.models import UsersOrm, TariffsOrm, PromoOrm, ServersOrm, KeysOrm, TextSettingsOrm, BannedOrm, AdminsOrm


async def init_database():
    """Инициализация базы данных"""
    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await _migrate_add_tv_columns(connection)
        await _migrate_add_traffic_reset_at(connection)

    await create_default_settings_rows()


async def _migrate_add_traffic_reset_at(connection):
    """Добавляет колонку traffic_reset_at в keys если её нет"""
    await connection.execute(text(
        "ALTER TABLE keys ADD COLUMN IF NOT EXISTS traffic_reset_at TIMESTAMPTZ"
    ))


async def _migrate_add_tv_columns(connection):
    """Добавляет колонки tv_video и tv_url если их нет"""
    for col in ("tv_video", "tv_url"):
        await connection.execute(text(
            f"ALTER TABLE text_settings ADD COLUMN IF NOT EXISTS {col} TEXT"
        ))


async def create_default_settings_rows():
    """Создание дефолтных текстовых настроек в бд"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = insert(TextSettingsOrm).values(id=1)
            stmt = stmt.on_conflict_do_nothing(index_elements=["id"])
            await session.execute(stmt)
