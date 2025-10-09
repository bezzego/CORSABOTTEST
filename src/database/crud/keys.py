from datetime import datetime

from sqlalchemy import desc, select

from src.database.crud.notifications import sync_user_key_rules
from src.database.database import AsyncSessionLocal
from src.database.models import KeysOrm
from src.logs import getLogger


logger = getLogger(__name__)


async def get_device_last_id(user_id: int, device: str):
    """Получить последний device id пользователя."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(KeysOrm)
            .where(KeysOrm.user_id == user_id, KeysOrm.device == device)
            .order_by(desc(KeysOrm.id))
        )
        key = result.scalar()
        if not key:
            return 1

        return int(key.name[-1]) + 1


async def add_new_key(
    user_id: int,
    server_id: int,
    key: str,
    device: str,
    finish: datetime,
    name: str,
    is_test: bool,
):
    """Создание ключа в БД и синхронизация уведомлений по правилам A–D."""
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
                is_test=is_test,
            )
            session.add(new_key)
            logger.debug("Created new Key: %s", new_key)

        await session.refresh(new_key)
        key_id = new_key.id

    try:
        await sync_user_key_rules(user_id, key_ids=[key_id])
    except Exception:
        logger.exception(
            "Failed to sync notification schedules for new key_id=%s (user_id=%s)",
            key_id,
            user_id,
        )

    return new_key


async def get_user_keys(user_id: int) -> list[KeysOrm]:
    """Получение всех ключей пользователя."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(KeysOrm).where(KeysOrm.user_id == user_id).order_by(desc(KeysOrm.finish))
        )
        if result:
            return result.scalars().all()
        return []


async def get_key_by_id(pk_id: int) -> KeysOrm | None:
    """Получение ключа по id."""
    async with AsyncSessionLocal() as session:
        key = await session.get(KeysOrm, pk_id)
        if key:
            return key
        return None


async def get_all_keys_server(server_id: int) -> list[KeysOrm]:
    """Получение всех ключей сервера."""
    async with AsyncSessionLocal() as session:
        stmt = select(KeysOrm).where(KeysOrm.server_id == server_id)
        result = await session.execute(stmt)
        if result:
            return result.scalars().all()
        return []


async def get_all_keys() -> list[KeysOrm]:
    """Получение всех ключей."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(KeysOrm))
        if result:
            return result.scalars().all()
        return []


async def update_key(key: KeysOrm):
    """Обновляет объект ключа в БД и пересинхронизирует уведомления."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            ex_key = await session.get(KeysOrm, key.id)
            logger.debug("Updated key:\nex_key %s\nnew_key %s", ex_key, key)
            if not ex_key:
                return
            ex_key.alerted = key.alerted
            ex_key.active = key.active
            ex_key.finish = key.finish
            ex_key.server_id = key.server_id

        await session.refresh(ex_key)
        user_id = ex_key.user_id
        key_id = ex_key.id

    try:
        await sync_user_key_rules(user_id, key_ids=[key_id])
    except Exception:
        logger.exception(
            "Failed to sync notification schedules after updating key_id=%s (user_id=%s)",
            key_id,
            user_id,
        )


async def update_key_transfer(key: KeysOrm):
    """Обновляет объект ключа при переносе на другой сервер."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            ex_key = await session.get(KeysOrm, key.id)
            logger.debug("Updated key:\nex_key %s\nnew_key %s", ex_key, key)
            if ex_key:
                ex_key.server_id = key.server_id
                ex_key.key = key.key


async def delete_key(key: KeysOrm):
    """Удаляет запись о ключе."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            key_obj = await session.get(KeysOrm, key.id)
            if key_obj:
                await session.delete(key_obj)
