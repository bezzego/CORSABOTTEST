from src.config import settings
from src.database.crud.payments import new_payment
from src.logs import getLogger
from yoomoney import Client, Quickpay
from uuid import uuid4

logger = getLogger(__name__)

client = Client(settings.payments.token)


async def create_payment(tariff, price, user_id, device, key_id=None, promo=None):
    """Создание юмани платежа"""
    label = str(uuid4())
    payment = Quickpay(
        receiver=str(client.account_info().account),
        quickpay_form="shop",
        targets=f"Покупка тарифа {tariff.name}",
        paymentType="SB",
        sum=price,
        label=label)

    await new_payment(
        label=label,
        user_id=user_id,
        tariff_id=tariff.id,
        amount=price,
        url=payment.redirected_url,
        device=device,
        key_id=key_id,
        promo=promo)
    return payment.redirected_url, label


async def check_payment(label: str):
    """Проверка статуса юмани платежа"""
    history = client.operation_history(label=label)
    for operation in history.operations:
        logger.info(f"Payment check: t: {operation.title}, am: {operation.amount}, status: {operation.status}, l: {operation.label}")
        if operation.status == "success":
            return True

    logger.debug(f"Payment not found: l: {label}")
    return False
