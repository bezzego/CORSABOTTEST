from sqlalchemy import select, asc, desc, update, delete, result_tuple
from src.logs import getLogger
from src.database.database import AsyncSessionLocal
from src.database.models import TariffsOrm

logger = getLogger(__name__)


async def get_tariffs():
    """Получение всех тарифов"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(TariffsOrm).order_by(desc(TariffsOrm.price)))
        tariffs = result.scalars().all()
        logger.debug(f"Getting tariffs list: {tariffs}")
        return tariffs


async def get_tariff(tariff_id: str):
    """Получение записи тарифа"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(TariffsOrm).where(TariffsOrm.id == int(tariff_id)))
        tariff = result.scalar()
        logger.debug(f"Getting tariff: {tariff}")
        return tariff


async def change_tariff_value(tariff_id: int, **kwargs):
    """Изменение параметра тарифа"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = update(TariffsOrm).where(TariffsOrm.id == tariff_id).values(**kwargs).returning(TariffsOrm)
            result = await session.execute(stmt)
            logger.debug(f"Change tariff {kwargs}: {result.scalar()}")


async def delete_tariff(tariff_id: int):
    """Удаление тарифа из бд"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = delete(TariffsOrm).where(TariffsOrm.id == tariff_id).returning(TariffsOrm)
            result = await session.execute(stmt)
            logger.debug(f"Delete tariff: {result.scalar()}")


async def add_tariff(name: str, price: int, days: int):
    """Создание нового тарифа в бд"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            new_tariff = TariffsOrm(name=name, price=int(price), days=int(days))
            session.add(new_tariff)
            await session.flush()
            logger.debug(f"Add new tariff: {new_tariff}")
