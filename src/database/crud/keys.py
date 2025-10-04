from datetime import datetime
from sqlalchemy import select, asc, desc, func
from src.logs import getLogger
from src.database.database import AsyncSessionLocal
from src.database.models import UsersOrm, TariffsOrm, PromoOrm, ServersOrm, KeysOrm, TextSettingsOrm, BannedOrm, AdminsOrm

logger = getLogger(__name__)


async def get_device_last_id(user_id: int, device: str):
    """Получить последний device id пользователя"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(KeysOrm).where(KeysOrm.user_id == user_id, KeysOrm.device == device).order_by(desc(KeysOrm.id)))
        key = result.scalar()
        if not key:
            return 1

        return int(key.name[-1]) + 1


async def add_new_key(user_id: int, server_id: int, key: str, device: str, finish: datetime, name: str, is_test: bool):
    """Создание ключа в бд"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            new_key = KeysOrm(
                user_id=user_id,
                server_id=server_id,
                key=key,
                device=device,
                start=datetime.now(),
                finish=finish,
                name=name,
                is_test=is_test
            )
            session.add(new_key)
            logger.debug(f"Created new Key: {new_key}")
            return new_key


async def get_user_keys(user_id: int) -> list[KeysOrm]:
    """Получение всех ключей юзера"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(KeysOrm).where(KeysOrm.user_id == user_id).order_by(desc(KeysOrm.finish)))
        if result:
            return result.scalars().all()


async def get_key_by_id(pk_id: int) -> KeysOrm:
    """Получение ключа по id"""
    async with AsyncSessionLocal() as session:
        key = await session.get(KeysOrm, pk_id)
        if key:
            return key


async def get_all_keys_server(server_id: int) -> list[KeysOrm]:
    """Получение всех ключей сервера"""
    async with AsyncSessionLocal() as session:
        stmt = select(KeysOrm).where(KeysOrm.server_id == server_id)
        result = await session.execute(stmt)
        if result:
            return result.scalars().all()


async def get_all_keys() -> list[KeysOrm]:
    """Получение всех ключей"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(KeysOrm))
        if result:
            return result.scalars().all()


async def update_key(key: KeysOrm):
    """Обновляет объект ключа"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            ex_key = await session.get(KeysOrm, key.id)
            logger.debug(f"Updated key:\nex_key {ex_key}\nnew_key {key}")
            if ex_key:
                ex_key.alerted = key.alerted
                ex_key.active = key.active
                ex_key.finish = key.finish
                ex_key.server_id = key.server_id


async def update_key_transfer(key: KeysOrm):
    """Обновляет объект ключа"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            ex_key = await session.get(KeysOrm, key.id)
            logger.debug(f"Updated key:\nex_key {ex_key}\nnew_key {key}")
            if ex_key:
                ex_key.server_id = key.server_id
                ex_key.key = key.key


async def delete_key(key: KeysOrm):
    """Удаляет запись о ключе"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            key = await session.get(KeysOrm, key.id)
            if key:
                await session.delete(key)
