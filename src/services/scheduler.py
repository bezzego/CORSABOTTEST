import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta
from src.database.crud.payments import (
    get_payments_to_check, 
    mark_payment_successful, 
    delete_expired_payment,
    get_success_payments_without_key
)
from src.database.models import PaymentsOrm
from src.logs import getLogger
from src.services.keys_manager import process_success_payment
from src.services.notifications import notification_service
from src.services.payments import check_payment

logger = getLogger(__name__)


# Планировщик теперь работает по московскому времени (Europe/Moscow)
scheduler = AsyncIOScheduler(timezone=ZoneInfo("Europe/Moscow"))


async def check_pending_payments(bot):
    """Фоновая проверка всех ожидающих платежей"""
    payments = await get_payments_to_check()
    logger.debug(f"Start check pending_payments: list: {payments}")

    for payment in payments:
        try:
            await process_pending_payment(bot, payment)
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"Error processing pending payment {payment.label}: {e}", exc_info=True)

    logger.debug(f"Complete check pending_payments")


async def check_success_payments_without_key(bot):
    """
    Проверка и обработка платежей в статусе success, для которых ключ еще не выдан (восстановление).
    
    ЗАДАЧА 4: Ограничение recovery
    - Обрабатывает максимум 5 платежей за запуск
    - Только платежи не старше 30 дней
    - Предотвращает массовую повторную выдачу ключей
    """
    # ЗАДАЧА 4: Лимиты для предотвращения массовой повторной выдачи
    payments = await get_success_payments_without_key(limit=5, days_cutoff=30)
    if payments:
        logger.warning(f"Found {len(payments)} success payments without issued key. Processing recovery (limited to 5 per run, max 30 days old)...")
    else:
        logger.debug("No payments found for recovery")
        return
    
    for payment in payments:
        try:
            logger.info(f"Recovering payment {payment.label} (user_id={payment.user_id}, created_at={payment.created_at})")
            await process_success_payment(bot, payment)
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"Error recovering payment {payment.label}: {e}", exc_info=True)


async def process_pending_payment(bot, payment: PaymentsOrm):
    """Обработка платежа в статусе pending"""
    logger.debug(f"process pending_payment: {payment}")
    is_payment_success = await check_payment(payment.label)
    if is_payment_success:
        # Помечаем платеж как успешный только при явном успешном ответе от YooMoney
        await mark_payment_successful(payment)
        logger.info(f"Payment confirmed: {payment.label}")
        
        # Выдаем ключ (идемпотентная операция)
        try:
            await process_success_payment(bot, payment)
        except Exception as e:
            logger.error(f"Failed to process success payment {payment.label}: {e}", exc_info=True)
            # Платеж останется в статусе success, но без key_issued_at
            # Будет обработан в следующем цикле check_success_payments_without_key
        return

    # Если платёж не найден в YooMoney, НЕ помечаем его как успешный
    # Платёж остаётся в статусе pending до явного подтверждения от YooMoney
    
    # Всюду сравниваем в московском времени
    created_at = payment.created_at
    if created_at.tzinfo:
        created_at_msk = created_at.astimezone(ZoneInfo("Europe/Moscow"))
    else:
        created_at_msk = created_at.replace(tzinfo=ZoneInfo("Europe/Moscow"))

    now_msk = datetime.now(ZoneInfo("Europe/Moscow"))

    # Удаляем только очень старые pending платежи (старше 30 минут), но НЕ помечаем их как успешные
    if created_at_msk < now_msk - timedelta(minutes=30):
        await delete_expired_payment(payment)
        logger.debug(f"payment expired and deleted: {payment.label}")
    else:
        logger.debug(f"payment still pending: {payment.label}")


async def reset_bypass_traffic(bot):
    """Ежедневная задача: сбрасывает трафик на X3UI для bypass-ключей, у которых прошло ≥30 дней."""
    from src.database.crud.keys import get_bypass_keys_due_for_traffic_reset, update_key_traffic_reset
    from src.database.crud.servers import get_server_by_id
    from src.services.keys import X3UI
    from datetime import datetime, timezone

    keys = await get_bypass_keys_due_for_traffic_reset()
    logger.debug("reset_bypass_traffic: found %d keys due for reset", len(keys))

    for key in keys:
        try:
            server = await get_server_by_id(key.server_id)
            if not server:
                logger.warning("reset_bypass_traffic: server %s not found for key_id=%s", key.server_id, key.id)
                continue
            x3 = X3UI(server)
            if x3.reset_client_traffic(key.name):
                await update_key_traffic_reset(key.id, datetime.now(timezone.utc))
                logger.info("reset_bypass_traffic: traffic reset for key_id=%s name=%s", key.id, key.name)
            else:
                logger.warning("reset_bypass_traffic: panel reset failed for key_id=%s, will retry next run", key.id)
        except Exception:
            logger.error("reset_bypass_traffic: error for key_id=%s", key.id, exc_info=True)


async def start_scheduler(bot):
    # Проверка pending платежей каждые 25 секунд
    scheduler.add_job(check_pending_payments, 'interval', seconds=25, args=[bot])
    # Проверка success платежей без ключа каждые 60 секунд (восстановление)
    scheduler.add_job(check_success_payments_without_key, 'interval', seconds=60, args=[bot])
    scheduler.add_job(reset_bypass_traffic, 'interval', hours=24, args=[bot])
    await notification_service.init(scheduler, bot)
    scheduler.start()
