from aiogram.types import User
from sqlalchemy import select, update, insert, delete
from src.logs import getLogger
from src.database.database import AsyncSessionLocal
from src.database.models import UsersOrm, BannedOrm, AdminsOrm

logger = getLogger(__name__)


async def get_user(user: User):
    """Получение модели юзера из"""
    async with AsyncSessionLocal() as session:
        user = await session.get(UsersOrm, user.id)
        logger.debug(f"Getting user: {user}")
        return user


async def get_user_by_id_or_username(identifier: str):
    """Получение юзера по id/username"""
    async with AsyncSessionLocal() as session:
        if identifier.isdigit():
            stmt = select(UsersOrm).where((UsersOrm.id == int(identifier)))
        else:
            stmt = select(UsersOrm).where((UsersOrm.username == str(identifier)))

        result = await session.execute(stmt)
        return result.scalars().first()


async def change_test_sub(user_id: int, status: bool):
    """Изменение поля модели юзера"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            user = await session.get(UsersOrm, int(user_id))
            if user:
                user.test_sub = status
                await session.flush()
                logger.debug(f"Change user test_sub status, new user obj: {user}")
                return user


async def add_user(user: User, text: str):
    """Добавление юзера в бд"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            info = {
                "id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name
            }
            text = text.split()
            enter_start_text = None
            if len(text) > 1:
                enter_start_text = text[1]

            new_user = UsersOrm(id=user.id, username=user.username, enter_start_text=enter_start_text, info=info)
            session.add(new_user)
            logger.debug(f"Created User: {new_user}")
            return new_user


async def get_user_with_roles(user_id: int):
    """Получение пользователя с ролями"""
    async with AsyncSessionLocal() as session:
        stmt = select(UsersOrm, BannedOrm, AdminsOrm).outerjoin(
            BannedOrm, UsersOrm.id == BannedOrm.user_id
        ).outerjoin(
            AdminsOrm, UsersOrm.id == AdminsOrm.user_id
        ).where(UsersOrm.id == user_id)
        result = await session.execute(stmt)
        roles = result.all()
        user, banned, admin = None, None, None
        if roles:
            roles = roles[0]
            user, banned, admin = roles[0], roles[1], roles[2]
        logger.debug(f"Getting User roles: {user} | {banned} | {admin}")
        return user, banned, admin


async def get_users():
    """Получение всех юзеров"""
    async with AsyncSessionLocal() as session:
        users = await session.execute(select(UsersOrm))
        if users:
            return users.scalars().all()


async def ban_unban_user(user: UsersOrm, action: str):
    """Бан/Unban юзера"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            print(user, action)
            if action == "ban":
                stmt = insert(BannedOrm).values(user_id=user.id)
            elif action == "unban":
                stmt = delete(BannedOrm).where(BannedOrm.user_id == user.id)
            else:
                raise ValueError("Invalid action, must be 'ban' or 'unban'")
            await session.execute(stmt)
            await session.commit()
            logger.debug(f"{action.capitalize()} user: {user}")
