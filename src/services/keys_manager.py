from datetime import datetime, timedelta
from functools import wraps
from aiogram import Bot
from aiogram.enums import ParseMode
from src.database.crud import change_test_sub, get_tariff
from src.database.crud.keys import add_new_key, get_device_last_id, get_key_by_id, get_key_by_payment_id, update_key, delete_key, \
    update_key_transfer, get_all_keys_server
from src.database.crud.promo import activate_promo
from src.database.crud.payments import is_key_issued, mark_key_issued, mark_payment_as_error
from src.database.crud.servers import get_sorted_servers, get_server_by_id
from src.database.models import TariffsOrm, ServersOrm, PaymentsOrm
from src.keyboards.reply_user import get_start_menu
from src.logs import getLogger
from src.services.keys import X3UI
from src.services.notifications import notification_service
from src.utils.utils import get_key_name_without_user_id
from src.utils.utils_async import send_admins_message, send_notification_to_user
from src.config import settings

logger = getLogger(__name__)


def create_key_dec(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            logger.info(f"Create key {args if args else ''} | {kwargs}")
            return await func(*args, **kwargs)

        except Exception as e:
            logger.error(f"Error create key {args if args else ''} | {kwargs}: {e}", exc_info=True)
            await send_admins_message(bot=kwargs["bot"],
                                      text=f"У пользователя id={kwargs['user_id']} ошибка при создании ключа:\n\n{str(e)}")

    return wrapper


@create_key_dec
async def create_key(bot: Bot, user_id: int, finish_date: datetime, tariff_id: int = None, device: str = None, is_test: bool = False, promo = None, payment_id: int = None):
    """Создание ключа на сервере"""
    servers = await get_sorted_servers(is_test)
    server, used_slots = servers[0]
    free_slots = server.max_users - used_slots
    logger.debug(f"Create_key - get best server: used_slots: {used_slots} | free_slots: {free_slots} | {server}")

    if free_slots <= 0:
        text = f"⚠️ Не хватает {'тестовых' if is_test else 'платных'} серверов. Но ключи продолжаем создавать\n\nВыбранный сервер для создания ключей:\n Хост: {server.host}\nМаксимум слотов: {server.max_users}\nЗанято: {int(used_slots) + 1}"
        await send_admins_message(bot=bot, text=text)

    if not server:
        await send_notification_to_user(bot, user_id, f"⚠️ Не было найдено сводных серверов! Пожалуйста, обратитесь в поддержку.")
        raise RuntimeWarning("CreateKey Error, not found servers!")

    await send_notification_to_user(bot, user_id, "Идет выпуск ключа. Ожидание займет 1 минуту.")

    user = await change_test_sub(user_id, True)
    # Устанавливаем значение по умолчанию, если device не указан
    device = device or "unknown"
    device_id = await get_device_last_id(user_id, device)
    name = f'{settings.prefix}_{user_id}_{device}_{device_id}'

    days = (finish_date - datetime.now()).days

    x3_class = X3UI(server=server)
    x3_class.create_key(name, days)
    key = x3_class.get_key(name)

    new_key = await add_new_key(
        user_id=user_id,
        server_id=server.id,
        key=key,
        device=device,
        finish=finish_date,
        name=name,
        is_test=is_test,
        payment_id=payment_id)

    await send_notification_to_user(bot, user_id, f"Ключ 🔑{settings.prefix}_{device}{device_id} создан:")
    await send_notification_to_user(bot, user_id, key)
    if promo:
        await activate_promo(promo, user_id)

    if is_test:
        await notification_service.on_trial_key_created(user_id, new_key.finish)
    else:
        await notification_service.on_paid_key_created(user_id, new_key.finish)
    logger.info(f"Был создан новый ключ: {new_key}\nХост: {server.host}\nМаксимум слотов: {server.max_users}\nЗанято: {int(used_slots) + 1}")
    
    return new_key  # Возвращаем созданный ключ для атомарной обработки


async def prolong_key(bot: Bot, user_id: int, tariff: TariffsOrm, key_id: int, _admin_days: int = None, promo=None):
    key = await get_key_by_id(key_id)
    if not key:
        logger.error(f"Key {key_id} not found for prolongation (user_id={user_id})")
        await bot.send_message(
            chat_id=user_id,
            text="⚠️ Не было найдено ключа, обратитесь в поддержку")
        return
    
    server = await get_server_by_id(key.server_id)
    if not server:
        logger.error(f"Server {key.server_id} not found for key {key_id} (user_id={user_id})")
        await bot.send_message(
            chat_id=user_id,
            text="⚠️ Не было найдено сервера, обратитесь в поддержку")
        return
    add_days = tariff.days if tariff else _admin_days
    key.finish = max(key.finish, datetime.now()) + timedelta(days=add_days)

    if key.alerted:
        key.alerted = False

    if key.active:
        key.active = True

    await update_key(key)

    key = await get_key_by_id(key_id)
    days = key.finish - datetime.now()
    x3_class = X3UI(server)
    x3_class.turn_on_user(key.name, days.days)
    logger.info(f"Был продлен ключ: {key}\nХост: {server.host}\nВыбранный тариф: {tariff}")

    await send_notification_to_user(bot, user_id, f"Ключ 🔑{get_key_name_without_user_id(key)} был продлен на {add_days} дней.")
    if promo:
        await activate_promo(promo, user_id)

    if key.is_test:
        await notification_service.on_trial_key_created(user_id, key.finish)
    else:
        await notification_service.on_paid_key_prolonged(user_id, key.finish)


async def check_connection(server: ServersOrm):
    try:
        x3_class = X3UI(server)
        resp = x3_class.auth()
        if isinstance(resp, dict) and resp.get('success'):
            return True
        logger.warning(f"Server auth failed or returned unexpected response for server id={server.id}: {resp}")
        return False
    except Exception as e:
        logger.error(e, exc_info=True)


async def transfer_all_keys_from_server_to_server(bot: Bot, first_server_id: int, second_server_id: int):
    keys_to_transfer = await get_all_keys_server(first_server_id)
    if keys_to_transfer:
        for key in keys_to_transfer:
            await transfer_key_to_select_server(bot, key.id, second_server_id)


async def transfer_key_to_select_server(bot: Bot, key_id: int, server_id: int):
    try:
        key = await get_key_by_id(int(key_id))
        old_server = await get_server_by_id(key.server_id)

        # Удаление старого ключа с панельки
        x3_class = X3UI(old_server)
        x3_class.delete_user(key.name)

        # Создание нового ключа
        transfer_server = await get_server_by_id(int(server_id))
        x3_class = X3UI(transfer_server)
        days = (key.finish - datetime.now()).days
        x3_class.create_key(key.name, days)
        key_data = x3_class.get_key(key.name)

        key.server_id = transfer_server.id
        key.key = key_data
        await update_key_transfer(key)

        logger.info(f"Был перенесен ключ на другой сервер: key: {key} to server: {transfer_server}")
        text = f"Ваш ключ 🔑{get_key_name_without_user_id(key)} был перенесен на другой сервер.\nСрок действия ключа не изменился.\nВаш новый ключ:"
        await send_notification_to_user(bot, key.user_id, text)
        await send_notification_to_user(bot, key.user_id, key_data)

    except Exception as e:
        logger.error(f"Error transfer key {key_id} | to s_id: {server_id}: {e}", exc_info=True)


async def process_success_payment(bot, payment: PaymentsOrm):
    """
    Обработка успешного платежа с выдачей ключа.
    Идемпотентная функция - безопасна для повторных вызовов.
    Атомарная операция: ключ создается, payment.key_id обновляется, только потом success.
    
    ИСПРАВЛЕНИЕ: Если у платежа есть key_id, но нет key_issued_at, проверяем и переотправляем ключ.
    """
    # Проверяем, был ли ключ уже выдан (key_issued_at установлен)
    if await is_key_issued(payment):
        logger.info(f"Payment {payment.label} already processed (key_issued_at set). Skipping.")
        return
    
    # Если у платежа есть key_id, но нет key_issued_at - ключ был создан, но не отправлен
    # Необходимо переотправить ключ пользователю
    if payment.key_id is not None:
        logger.warning(f"Payment {payment.label} has key_id={payment.key_id} but key_issued_at is not set. Resending key to user.")
        try:
            key = await get_key_by_id(payment.key_id)
            if key:
                # Переотправляем ключ пользователю
                await send_notification_to_user(bot, payment.user_id, f"Ключ 🔑{get_key_name_without_user_id(key)}:")
                await send_notification_to_user(bot, payment.user_id, key.key)
                # Помечаем как обработанный
                await mark_key_issued(payment.id, key_id=payment.key_id)
                logger.info(f"Key {payment.key_id} resent to user {payment.user_id} for payment {payment.label}")
                return
            else:
                logger.error(f"Key {payment.key_id} not found for payment {payment.label}. Will create new key.")
                # Ключ не найден, создадим новый ниже
        except Exception as e:
            logger.error(f"Error resending key {payment.key_id} for payment {payment.label}: {e}", exc_info=True)
            # Продолжаем обработку, чтобы создать новый ключ
    
    # Проверяем существование ключа по payment_id (правило 1 платеж → 1 ключ)
    existing_key = await get_key_by_payment_id(payment.id)
    if existing_key:
        logger.warning(f"Payment {payment.label} already has key with payment_id (key_id={existing_key.id}). Updating payment.key_id and resending key.")
        # Синхронизируем payment.key_id с существующим ключом
        # Переотправляем ключ, если он не был отправлен ранее
        try:
            await send_notification_to_user(bot, payment.user_id, f"Ключ 🔑{get_key_name_without_user_id(existing_key)}:")
            await send_notification_to_user(bot, payment.user_id, existing_key.key)
        except Exception as e:
            logger.error(f"Error resending existing key {existing_key.id} for payment {payment.label}: {e}", exc_info=True)
        await mark_key_issued(payment.id, key_id=existing_key.id)
        return

    promo = payment.promo
    key_id = payment.key_id
    logger.info(f"Processing payment: user_id={payment.user_id} | label={payment.label} | key_id={key_id}")
    
    try:
        # ЗАДАЧА 1: Проверка тарифа - если не найден, помечаем как error и останавливаем recovery
        tariff = await get_tariff(payment.tariff_id)
        if not tariff:
            error_msg = f"Тариф {payment.tariff_id} не найден в базе данных"
            logger.error(f"Tariff {payment.tariff_id} not found for payment {payment.label} (user_id={payment.user_id})")
            await mark_payment_as_error(payment.id, error_msg)
            await send_admins_message(
                bot=bot,
                text=f"⚠️ Платеж {payment.label} (user_id={payment.user_id}) помечен как ERROR:\n{error_msg}\n\nRecovery больше не будет пытаться обработать этот платеж."
            )
            return  # Выходим, не повторяем recovery

        # ЗАДАЧА 2: Гарантируем device
        device = payment.device or "unknown"
        
        created_key = None
        
        if not key_id:
            # Создание нового ключа
            created_key = await create_key(
                bot=bot,
                user_id=payment.user_id,
                finish_date=datetime.now() + timedelta(days=tariff.days),
                tariff_id=tariff.id,
                device=device,
                is_test=False,
                promo=promo,
                payment_id=payment.id)  # Связываем ключ с платежом
        else:
            # Продление существующего ключа
            # Проверяем, что ключ существует перед попыткой продления
            key = await get_key_by_id(key_id)
            if not key:
                logger.error(f"Key {key_id} not found for payment {payment.label} (user_id={payment.user_id}). Creating new key instead.")
                await send_admins_message(
                    bot=bot,
                    text=f"⚠️ Ключ {key_id} не найден для платежа {payment.label} (user_id={payment.user_id}). Создается новый ключ."
                )
                # Создаем новый ключ вместо продления несуществующего
                created_key = await create_key(
                    bot=bot,
                    user_id=payment.user_id,
                    finish_date=datetime.now() + timedelta(days=tariff.days),
                    tariff_id=tariff.id,
                    device=device,
                    is_test=False,
                    promo=promo,
                    payment_id=payment.id)  # Связываем ключ с платежом
            else:
                await prolong_key(
                    bot=bot,
                    user_id=payment.user_id,
                    tariff=tariff,
                    key_id=key_id,
                    promo=promo)
                created_key = key

        # ЗАДАЧА 3: Атомарная операция - только после успешного создания ключа
        # Обновляем payment.key_id и помечаем как обработанный
        if created_key:
            await mark_key_issued(payment.id, key_id=created_key.id)
            logger.info(f"Payment {payment.label} successfully processed, key issued (key_id={created_key.id})")
        else:
            raise RuntimeError("Key was not created but no exception was raised")
        
    except Exception as e:
        logger.error(f"Error processing payment {payment.label}: {e}", exc_info=True)
        await send_admins_message(
            bot=bot,
            text=f"⚠️ Ошибка при обработке платежа {payment.label} (user_id={payment.user_id}):\n\n{str(e)}"
        )
        # Не помечаем как обработанный при ошибке, чтобы можно было повторить попытку
        raise
