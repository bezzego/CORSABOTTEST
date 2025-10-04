from datetime import datetime

from sqlalchemy import select, asc, desc, func, update, delete
from src.logs import getLogger
from src.database.database import AsyncSessionLocal
from src.database.models import UsersOrm, TariffsOrm, PromoOrm, ServersOrm, KeysOrm, TextSettingsOrm, BannedOrm, AdminsOrm

logger = getLogger(__name__)


async def get_promos():
    """Возвращает промокоды"""
    async with AsyncSessionLocal() as session:
        promos = await session.execute(select(PromoOrm))
        if promos:
            return promos.scalars().all()


async def get_promo_by_id(promo_id: int):
    """Получение сервера по promo_id"""
    async with AsyncSessionLocal() as session:
        promo = await session.get(PromoOrm, int(promo_id))
        if promo:
            return promo


async def get_promo_by_code(code: str) -> PromoOrm:
    """Получение сервера по code"""
    async with AsyncSessionLocal() as session:
        stmt = select(PromoOrm).where(PromoOrm.code == code)
        result = await session.execute(stmt)
        if result:
            return result.scalar()


async def activate_promo(promo: int, user_id: int):
    """Обновление нужных данных после активации промокода"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            try:
                promo = await session.get(PromoOrm, int(promo))
                if promo:
                    promo.users.append(user_id)

                user = await session.get(UsersOrm, user_id)
                if user:
                    user.used_promo = True

                await session.commit()

            except Exception as e:
                logger.error(e, exc_info=True)


async def change_promo_value(promo_id: int, **kwargs):
    """Изменение параметра promo"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = update(PromoOrm).where(PromoOrm.id == promo_id).values(**kwargs).returning(PromoOrm)
            result = await session.execute(stmt)
            logger.debug(f"Change promo {kwargs}: {result.scalar()}")


async def change_promo_tariffs(promo_id: int, tariffs: list):
    async with AsyncSessionLocal() as session:
        async with session.begin():
            promo: PromoOrm = await session.get(PromoOrm, int(promo_id))
            if promo:
                promo.tariffs.clear()
                for t_id in tariffs:
                    promo.tariffs.append(int(t_id))
                await session.commit()
                logger.debug(f"Change promo add tariffs: {tariffs}")


async def add_promo(code: str, price: int, user_limit: int, finish_time: datetime, tariffs: list):
    """Создание нового промокода в бд"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            new_promo = PromoOrm(code=code, price=int(price), users_limit=int(user_limit), finish_time=finish_time, tariffs=tariffs)
            session.add(new_promo)
            await session.flush()
            logger.debug(f"Add new promo: {new_promo}")
            await session.commit()
            return new_promo


async def delete_promo(promo_id: int):
    """Удаление сервера из бд"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = delete(PromoOrm).where(PromoOrm.id == promo_id).returning(PromoOrm)
            result = await session.execute(stmt)
            logger.debug(f"Delete promo: {result.scalar()}")
