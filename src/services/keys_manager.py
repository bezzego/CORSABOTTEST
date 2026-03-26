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
            result = await func(*args, **kwargs)
            # Проверяем, что функция вернула результат
            if result is None:
                raise RuntimeError(f"create_key returned None for user_id={kwargs.get('user_id')}")
            return result
        except Exception as e:
            logger.error(f"Error create key {args if args else ''} | {kwargs}: {e}", exc_info=True)
            # Отправляем уведомление админам, но ПРОБРАСЫВАЕМ исключение дальше
            try:
                await send_admins_message(bot=kwargs.get("bot"),
                                          text=f"У пользователя id={kwargs.get('user_id')} ошибка при создании ключа:\n\n{str(e)}")
            except:
                pass  # Не блокируем проброс исключения из-за ошибки отправки
            raise  # Пробрасываем исключение дальше, чтобы process_success_payment мог обработать

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
    create_resp = x3_class.create_key(name, days)
    if not create_resp or create_resp.status_code != 200:
        status = getattr(create_resp, "status_code", None)
        body = (getattr(create_resp, "text", "") or "")[:200]
        raise RuntimeError(
            f"Create key failed for user_id={user_id} on server={server.host}: "
            f"HTTP {status} body={body}"
        )
    key = x3_class.get_key(name)
    if not key:
        raise RuntimeError(
            f"Create key failed for user_id={user_id} on server={server.host}: empty key data"
        )

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
    """Продление существующего ключа. Всегда возвращает ключ или бросает исключение."""
    key = await get_key_by_id(key_id)
    if not key:
        error_msg = f"Key {key_id} not found for prolongation (user_id={user_id})"
        logger.error(error_msg)
        await bot.send_message(
            chat_id=user_id,
            text="⚠️ Не было найдено ключа, обратитесь в поддержку")
        raise ValueError(error_msg)
    
    server = await get_server_by_id(key.server_id)
    if not server:
        error_msg = f"Server {key.server_id} not found for key {key_id} (user_id={user_id})"
        logger.error(error_msg)
        await bot.send_message(
            chat_id=user_id,
            text="⚠️ Не было найдено сервера, обратитесь в поддержку")
        raise ValueError(error_msg)
    
    # Сохраняем старое значение finish для проверки, было ли продление
    old_finish = key.finish
    
    try:
        add_days = tariff.days if tariff else _admin_days
        key.finish = max(key.finish, datetime.now()) + timedelta(days=add_days)

        if key.alerted:
            key.alerted = False

        if key.active:
            key.active = True

        await update_key(key)

        key = await get_key_by_id(key_id)
        if not key:
            raise RuntimeError(f"Key {key_id} disappeared after update")
            
        days = key.finish - datetime.now()
        x3_class = X3UI(server)
        x3_class.turn_on_user(key.name, days.days)
        logger.info(f"Был продлен ключ: {key}\nХост: {server.host}\nВыбранный тариф: {tariff}")

        # ИСПРАВЛЕНИЕ: Отправка уведомления обернута в try-except
        # Если отправка не удалась, ключ уже продлен, поэтому не пробрасываем исключение
        try:
            await send_notification_to_user(bot, user_id, f"Ключ 🔑{get_key_name_without_user_id(key)} был продлен на {add_days} дней.")
            if promo:
                await activate_promo(promo, user_id)

            if key.is_test:
                await notification_service.on_trial_key_created(user_id, key.finish)
            else:
                await notification_service.on_paid_key_prolonged(user_id, key.finish)
        except Exception as notify_error:
            # Ключ уже продлен в БД и на сервере, но уведомление не отправлено
            # Логируем ошибку, но не пробрасываем исключение, так как основная операция выполнена
            logger.error(f"Key {key_id} prolonged successfully, but failed to send notification to user {user_id}: {notify_error}", exc_info=True)
            # Пытаемся отправить хотя бы базовое уведомление
            try:
                await send_notification_to_user(bot, user_id, f"Ваш ключ 🔑{get_key_name_without_user_id(key)} был продлен.")
            except:
                pass  # Если и это не удалось, просто логируем
        
        return key  # Всегда возвращаем ключ
    except Exception as e:
        # Если ошибка произошла до обновления ключа в БД, пробрасываем исключение
        # Если после - ключ уже продлен, нужно проверить
        if old_finish and key and key.finish and key.finish > old_finish:
            # Ключ был продлен, но произошла ошибка
            logger.warning(f"Key {key_id} was prolonged (finish changed from {old_finish} to {key.finish}), but error occurred: {e}")
            # Возвращаем ключ, так как продление выполнено
            return key
        logger.error(f"Error prolonging key {key_id} for user {user_id}: {e}", exc_info=True)
        raise  # Пробрасываем исключение дальше


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
        text = f"Ваш ключ 🔑{get_key_name_without_user_id(key)} был перенесен на другой сервер.\nСрок действия ключа не изменился.\nСтарый ключ нужно удалить из приложения и добавить ключ ниже:"
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
    
    # Если у платежа есть key_id, но нет key_issued_at - ключ был создан/продлен, но не отправлен
    # Проверяем, существует ли ключ и был ли он уже обработан
    if payment.key_id is not None:
        logger.warning(f"Payment {payment.label} has key_id={payment.key_id} but key_issued_at is not set. Checking if key was already processed.")
        try:
            key = await get_key_by_id(payment.key_id)
            if key:
                # Проверяем, есть ли ключ, связанный с этим платежом (новый ключ)
                existing_key_by_payment = await get_key_by_payment_id(payment.id)
                
                if existing_key_by_payment and existing_key_by_payment.id == key.id:
                    # Это новый ключ, созданный для этого платежа - просто отправляем уведомление
                    logger.info(f"Key {key.id} already exists for payment {payment.label}. Resending notification.")
                    try:
                        await send_notification_to_user(bot, payment.user_id, f"Ключ 🔑{get_key_name_without_user_id(key)}:")
                        await send_notification_to_user(bot, payment.user_id, key.key)
                        await mark_key_issued(payment.id, key_id=key.id)
                        logger.info(f"Key {key.id} notification resent to user {payment.user_id} for payment {payment.label}")
                        return
                    except Exception as send_error:
                        logger.error(f"Failed to send key {key.id} to user {payment.user_id}: {send_error}", exc_info=True)
                        # Ключ существует, помечаем как обработанный даже если отправка не удалась
                        await mark_key_issued(payment.id, key_id=key.id)
                        logger.info(f"Key {key.id} marked as issued despite notification failure for payment {payment.label}")
                        return
                else:
                    # Это продление существующего ключа
                    # ИСПРАВЛЕНИЕ: Всегда выполняем продление, даже если ключ еще активен
                    # Пользователь должен иметь возможность продлить ключ в любой момент
                    logger.info(f"Key {key.id} exists for payment {payment.label}. Will proceed with prolongation (key can be prolonged even if still active).")
                    # Продолжаем обработку ниже для выполнения продления
            else:
                logger.error(f"Key {payment.key_id} not found for payment {payment.label}. Will create new key.")
                # Ключ не найден, создадим новый ниже
        except Exception as e:
            logger.error(f"Error checking key {payment.key_id} for payment {payment.label}: {e}", exc_info=True)
            # Продолжаем обработку, чтобы создать/продлить ключ
    
    # Проверяем существование ключа по payment_id (правило 1 платеж → 1 ключ)
    existing_key = await get_key_by_payment_id(payment.id)
    if existing_key:
        logger.warning(f"Payment {payment.label} already has key with payment_id (key_id={existing_key.id}). Updating payment.key_id and resending key.")
        # Синхронизируем payment.key_id с существующим ключом
        # Переотправляем ключ, если он не был отправлен ранее
        try:
            await send_notification_to_user(bot, payment.user_id, f"Ключ 🔑{get_key_name_without_user_id(existing_key)}:")
            await send_notification_to_user(bot, payment.user_id, existing_key.key)
            # Только после успешной отправки помечаем как обработанный
            await mark_key_issued(payment.id, key_id=existing_key.id)
            logger.info(f"Existing key {existing_key.id} resent to user {payment.user_id} for payment {payment.label}")
            return
        except Exception as e:
            logger.error(f"Error resending existing key {existing_key.id} for payment {payment.label}: {e}", exc_info=True)
            # Не помечаем как обработанный, если отправка не удалась
            raise  # Пробрасываем, чтобы recovery попробовал снова

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

        # ЗАДАЧА 2: Гарантируем device - всегда должно быть значение
        device = payment.device
        if not device or device.strip() == "":
            # Если это продление ключа, пытаемся взять device из существующего ключа
            if key_id:
                existing_key_for_device = await get_key_by_id(key_id)
                if existing_key_for_device and existing_key_for_device.device:
                    device = existing_key_for_device.device
                    logger.info(f"Payment {payment.label}: Using device '{device}' from existing key {key_id}")
                else:
                    device = "unknown"
                    logger.warning(f"Payment {payment.label}: key_id={key_id} but key not found or has no device, using 'unknown'")
            else:
                device = "unknown"
                logger.warning(f"Payment {payment.label} has empty device, using 'unknown' as fallback")
        
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
            
            # Проверяем, что ключ действительно создан
            if not created_key:
                raise RuntimeError(f"create_key returned None for payment {payment.label}")
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
                
                if not created_key:
                    raise RuntimeError(f"create_key returned None when creating replacement key for payment {payment.label}")
            else:
                # Продлеваем существующий ключ
                created_key = await prolong_key(
                    bot=bot,
                    user_id=payment.user_id,
                    tariff=tariff,
                    key_id=key_id,
                    promo=promo)
                
                # prolong_key теперь всегда возвращает ключ или бросает исключение
                if not created_key:
                    raise RuntimeError(f"prolong_key returned None for key {key_id} in payment {payment.label}")

        # ЗАДАЧА 3: Атомарная операция - только после успешного создания/продления ключа
        # Ключ уже отправлен пользователю в create_key или prolong_key
        # Обновляем payment.key_id и помечаем как обработанный
        if created_key:
            await mark_key_issued(payment.id, key_id=created_key.id)
            logger.info(f"Payment {payment.label} successfully processed, key issued (key_id={created_key.id})")
        else:
            raise RuntimeError(f"Key was not created/prolonged for payment {payment.label}")
        
    except Exception as e:
        logger.error(f"Error processing payment {payment.label}: {e}", exc_info=True)
        await send_admins_message(
            bot=bot,
            text=f"⚠️ Ошибка при обработке платежа {payment.label} (user_id={payment.user_id}):\n\n{str(e)}"
        )
        # Не помечаем как обработанный при ошибке, чтобы можно было повторить попытку
        raise
