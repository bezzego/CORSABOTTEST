import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
from src.database.crud.payments import get_payments_to_check, mark_payment_successful, delete_expired_payment
from src.database.models import PaymentsOrm
from src.logs import getLogger
from src.services.keys_manager import process_success_payment
from src.services.notifications import notification_service
from src.services.payments import check_payment

logger = getLogger(__name__)


scheduler = AsyncIOScheduler()


async def check_pending_payments(bot):
    """Фоновая проверка всех ожидающих платежей"""
    payments = await get_payments_to_check()
    logger.debug(f"Start check pending_payments: list: {payments}")

    for payment in payments:
        try:
            await process_pending_payment(bot, payment)
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(e)

    logger.debug(f"Complete check pending_payments")


async def process_pending_payment(bot, payment: PaymentsOrm):
    logger.debug(f"process pending_payment: {payment}")
    is_payment_success = await check_payment(payment.label)
    if is_payment_success:
        await mark_payment_successful(payment)
        logger.debug(f"payment confirmed: {payment.label}")
        await process_success_payment(bot, payment)

    elif payment.created_at < datetime.now() - timedelta(minutes=30):
        await delete_expired_payment(payment)
        logger.debug(f"payment expired and deleted: {payment.label}")
    else:
        logger.debug(f"payment still pending: {payment.label}")


async def start_scheduler(bot):
    scheduler.add_job(check_pending_payments, 'interval', seconds=25, args=[bot])
    await notification_service.init(scheduler, bot)
    scheduler.start()
