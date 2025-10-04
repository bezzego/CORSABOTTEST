from sqlalchemy import select, asc, desc, func
from src.logs import getLogger
from src.database.database import AsyncSessionLocal
from src.database.models import UsersOrm, TariffsOrm, PromoOrm, ServersOrm, KeysOrm, TextSettingsOrm, BannedOrm, AdminsOrm

logger = getLogger(__name__)


async def get_admins_list():
    """Получение всех админов"""
    async with AsyncSessionLocal() as session:
        stmt = select(AdminsOrm)
        result = await session.execute(stmt)
        admins = result.scalars().all()
        logger.debug(f"Getting admins list: {admins}")
        return admins
