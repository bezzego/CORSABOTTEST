from sqlalchemy import select, asc, desc, func, update, delete
from sqlalchemy.orm import aliased
from src.logs import getLogger
from src.database.database import AsyncSessionLocal
from src.database.models import UsersOrm, TariffsOrm, PromoOrm, ServersOrm, KeysOrm, TextSettingsOrm, BannedOrm, AdminsOrm

logger = getLogger(__name__)


async def check_servers(is_test: bool = False):
    """Проверка на наличие серверов в бд"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(ServersOrm).where(ServersOrm.is_test == is_test))
        servers = result.all()
        logger.debug(f"check_servers: {servers}")
        if servers:
            return True


async def get_sorted_servers(is_test: bool = False):
    """Получение всех серверов"""
    async with AsyncSessionLocal() as session:
        keys_alias = aliased(KeysOrm)

        stmt = (
            select(ServersOrm, func.count(keys_alias.id).label("used_slots"))
            .outerjoin(keys_alias, ServersOrm.id == keys_alias.server_id)
            .where(ServersOrm.is_test == is_test)
            .group_by(ServersOrm.id)
            .order_by((ServersOrm.max_users - func.count(keys_alias.id)).desc())
        )
        result = await session.execute(stmt)
        servers = result.all()
        logger.debug(f"Getting sort servers: {servers}")
        return servers


async def get_server_by_id(server_id: int):
    """Получение сервера по server_id"""
    async with AsyncSessionLocal() as session:
        server = await session.get(ServersOrm, server_id)
        if server:
            return server


async def get_servers():
    """Возвращает сервера"""
    async with AsyncSessionLocal() as session:
        servers = await session.execute(select(ServersOrm))
        if servers:
            return servers.scalars().all()


async def change_server_value(server_id: int, **kwargs):
    """Изменение параметра сервера"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = update(ServersOrm).where(ServersOrm.id == server_id).values(**kwargs).returning(ServersOrm)
            result = await session.execute(stmt)
            logger.debug(f"Change server {kwargs}: {result.scalar()}")


async def count_keys_by_server(server_id: int):
    """Подсчитывает сколько ключей на сервере"""
    async with AsyncSessionLocal() as session:
        stmt = select(func.count()).select_from(KeysOrm).where(KeysOrm.server_id == server_id)
        result = await session.execute(stmt)
        return result.scalar()


async def delete_server(server_id: int):
    """Удаление сервера из бд"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = delete(ServersOrm).where(ServersOrm.id == server_id).returning(ServersOrm)
            result = await session.execute(stmt)
            logger.debug(f"Delete server: {result.scalar()}")


async def add_server(address: str, login: str, password: str):
    """Создание нового сервера в бд"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            new_server = ServersOrm(
                host=address,
                login=login,
                password=password,
                max_users=20,
                is_test=False)
            session.add(new_server)
            await session.flush()
            logger.debug(f"Add new server: {new_server}")
