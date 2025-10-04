from src.logs import getLogger
from sqlalchemy import select
from src.database.database import AsyncSessionLocal
from src.database.models import PaymentsOrm, PaymentStatus
from datetime import datetime, timedelta

logger = getLogger(__name__)


async def new_payment(label: str, user_id: id, tariff_id: str, amount: int, url: str, device: str, key_id: int = None, promo: int = None):
    """Добавление нового платежа в бд"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            payment = PaymentsOrm(
                label=label,
                user_id=user_id,
                tariff_id=tariff_id,
                amount=amount,
                url=url,
                key_id=key_id,
                device=device,
                promo=promo,
                status=PaymentStatus.pending)

            session.add(payment)

        logger.debug(f"Create new payment: {payment}")


async def get_payments_to_check():
    """Получение всех платежей в статусе pending, созданных 2–50 минут назад"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                select(PaymentsOrm).where(
                    PaymentsOrm.status == PaymentStatus.pending,
                )
            )
            return result.scalars().all()


async def mark_payment_successful(payment: PaymentsOrm):
    async with AsyncSessionLocal() as session:
        async with session.begin():
            payment = await session.get(PaymentsOrm, payment.id)
            if payment:
                payment.status = PaymentStatus.success
                payment.updated_at = datetime.now()


async def delete_expired_payment(payment: PaymentsOrm):
    async with AsyncSessionLocal() as session:
        async with session.begin():
            payment = await session.get(PaymentsOrm, payment.id)
            if payment:
                await session.delete(payment)
