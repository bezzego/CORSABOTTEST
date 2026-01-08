from src.logs import getLogger
from sqlalchemy import select
from src.database.database import AsyncSessionLocal
from src.database.models import PaymentsOrm, PaymentStatus
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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
            return payment


async def mark_payment_as_error(payment_id: int, reason: str = None):
    """Помечает платеж как error (не может быть обработан, recovery не должен повторять)"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            payment = await session.get(PaymentsOrm, payment_id)
            if payment:
                payment.status = PaymentStatus.error
                payment.updated_at = datetime.now(ZoneInfo("Europe/Moscow"))
                if reason:
                    logger.warning(f"Payment {payment.label} marked as error: {reason}")
            return payment


async def mark_key_issued(payment_id: int, key_id: int = None):
    """Помечает платеж как обработанный (ключ выдан)"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            payment = await session.get(PaymentsOrm, payment_id)
            if payment:
                payment.key_issued_at = datetime.now(ZoneInfo("Europe/Moscow"))
                if key_id:
                    payment.key_id = key_id
                payment.updated_at = datetime.now(ZoneInfo("Europe/Moscow"))
            return payment


async def is_key_issued(payment: PaymentsOrm) -> bool:
    """Проверяет, был ли уже выдан ключ для платежа"""
    # Если у объекта уже есть key_issued_at, используем его
    if hasattr(payment, 'key_issued_at') and payment.key_issued_at is not None:
        return True
    
    # Иначе проверяем в базе данных
    async with AsyncSessionLocal() as session:
        result = await session.get(PaymentsOrm, payment.id)
        if result:
            return result.key_issued_at is not None
        return False


async def get_success_payments_without_key() -> list[PaymentsOrm]:
    """Получение всех платежей в статусе success, для которых ключ еще не выдан"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PaymentsOrm).where(
                PaymentsOrm.status == PaymentStatus.success,
                PaymentsOrm.key_issued_at.is_(None)
            )
        )
        return result.scalars().all()


async def delete_expired_payment(payment: PaymentsOrm):
    async with AsyncSessionLocal() as session:
        async with session.begin():
            payment = await session.get(PaymentsOrm, payment.id)
            if payment:
                await session.delete(payment)


async def get_success_payments() -> list[PaymentsOrm]:
    """Получение всех платежей в статусе success."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PaymentsOrm).where(PaymentsOrm.status == PaymentStatus.success)
        )
        if result:
            return result.scalars().all()
        return []
