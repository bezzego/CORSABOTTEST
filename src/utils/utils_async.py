import asyncio
from functools import wraps
from typing import Union
from datetime import datetime, timezone

from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, Message
from src.database.crud import add_user, get_user_with_roles, get_users, get_text_settings
from src.database.crud.admins import get_admins_list
from src.database.crud.keys import get_user_keys, get_all_keys
from src.database.crud.promo import get_promos
from src.database.crud.servers import check_servers, get_servers
from src.keyboards.inline_user import edit_inline_keyboard_select_tariff, edit_inline_keyboard_select_device, \
    edit_inline_markup_add_symbol, get_inline_markup_with_url
from src.keyboards.reply_user import get_reply_user_btn
from src.logs import getLogger
from src.services.notifications import notification_service
import io
import xlsxwriter

logger = getLogger(__name__)


def check_have_servers(handler):
    """Проверка есть ли сервера в бд"""
    @wraps(handler)
    async def wrapper(message, *args, **kwargs):
        test_servers = False
        if get_reply_user_btn("test_sub") == message.text:
            test_servers = True

        have_servers = await check_servers(test_servers)
        if not have_servers:
            await message.reply("⚠️ На данный момент нету существующих серверов, попробуйте позже или обратитесь в поддержку.")
            await send_admins_message(message.bot,
                                      f"⚠️ Не было найдено сводных {'тестовых' if test_servers else 'платных'} серверов! Пожалуйста, обратитесь в поддержку.")
            return

        return await handler(message, *args, **kwargs)

    return wrapper


def auth_admin_role(handler):
    """Получение роли админа"""
    @wraps(handler)
    async def wrapper(message, *args, **kwargs):
        if message.chat.type in ("group", "supergroup", "channel"):
            return

        user, banned, admin = await get_user_with_roles(message.from_user.id)

        if admin:
            return await handler(message, *args, **kwargs)

    return wrapper


def auth_user_role(handler):
    """Получение роли юзера в бд"""
    @wraps(handler)
    async def wrapper(message, *args, **kwargs):
        if message.chat.type in ("group", "supergroup", "channel"):
            return

        user, banned, admin = await get_user_with_roles(message.from_user.id)
        if not user:
            user = await add_user(message.from_user, message.text)
            await notification_service.on_user_registered(
                message.from_user.id,
                datetime.now(timezone.utc),
            )

        if banned:
            await message.reply("К сожалению вы были заблокированы и не можете использовать функционал бота.")
            return

        if message.text.startswith("/start") or message.text == get_reply_user_btn("test_sub"):
            return await handler(message, *args, **kwargs, user=user, admin_role=True if admin else None)

        return await handler(message, *args, **kwargs)

    return wrapper


async def delete_message_from_state(callback: CallbackQuery, state_data: dict, item_name: str):
    """Удаление сообщений по айди из состояния"""
    try:

        if item_name in state_data:
            await callback.bot.delete_message(callback.message.chat.id, state_data[item_name])
            state_data.pop(item_name)

        return state_data

    except Exception as e:
        logger.warning(f"{e}\nstate_data: {state_data}")
        return state_data


async def update_inline_reply_markup(callback, func: Union[edit_inline_keyboard_select_tariff, edit_inline_keyboard_select_device, edit_inline_markup_add_symbol], *args):
    """Обновление инлайн_маркап с ссылкой на функции"""
    try:
        if not args:
            new_reply_markup = func(callback.message.reply_markup.inline_keyboard, callback.data)
        else:
            new_reply_markup = func(callback.message.reply_markup.inline_keyboard, callback.data, args[0])

        if new_reply_markup:
            await callback.message.edit_reply_markup(reply_markup=new_reply_markup)

    except Exception as e:
        logger.error(e, exc_info=True)


async def send_admins_message(bot, text: str):
    """Отправка сообщения всем админам"""
    admins = await get_admins_list()
    for admin in admins:
        try:
            await bot.send_message(
                chat_id=admin.user_id,
                text=text)

        except Exception as e:
            logger.error(e)


async def send_notification_to_user(bot, user_id: int, text: str):
    """Отправка уведомления пользователю"""
    try:
        await bot.send_message(
            chat_id=user_id,
            text=text)

    except Exception as e:
        logger.error(e)


async def send_message_safe(bot, chat_id: int, message: Message) -> Message:
    try:
        if message.text:
            return await bot.send_message(chat_id, message.text, parse_mode=ParseMode.HTML)
        elif message.photo:
            return await bot.send_photo(chat_id, photo=message.photo[-1].file_id, caption=message.caption, parse_mode=ParseMode.HTML)
        elif message.video:
            return await bot.send_video(chat_id, video=message.video.file_id, caption=message.caption, parse_mode=ParseMode.HTML)
        elif message.document:
            return await bot.send_document(chat_id, document=message.document.file_id, caption=message.caption, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(f"Ошибка при отправке пользователю {chat_id}: {e}")
        return False


async def broadcast_message(bot, message: Message, admin_id: int, user=None):
    """Фоновая рассылка сообщения всем пользователям."""
    users = [user] if user else await get_users()
    total = len(users)
    success = 0
    failed = 0
    status_message = await bot.send_message(admin_id, f"Рассылка началась, вы получите оповещение по ее завершению.\n\nВсего пользователей: {total}\n\nМожете продолжать пользоваться ботом.")

    for idx, user in enumerate(users, 1):
        if await send_message_safe(bot, user.id, message):
            success += 1
        else:
            failed += 1

        await asyncio.sleep(0.2)

    final_status = f"Рассылка завершена!\n\nОтправлено сообщений: {success}\nОшибок: {failed}\nВсего пользователей: {total}"
    await bot.edit_message_text(final_status, chat_id=admin_id, message_id=status_message.message_id)


async def export_users_to_excel():
    """Создание статистики по юзерам"""
    users_data = {'№': [], 'ID': [], 'Имя и юзернейм': [], 'Пробная подписка': [], 'Промокод': [],
                  'Кол-во ключей': [], 'Ключи': [], 'Дата появления': [], 'Ссылка': []}

    users = await get_users()
    servers = {server.id: server.host for server in await get_servers()}
    promos = await get_promos()
    promos_dict = {promo.id: promo for promo in promos}

    for index, user in enumerate(sorted(users, key=lambda x: x.id), start=1):
        users_data['№'].append(index)
        users_data['ID'].append(user.id)
        users_data['Имя и юзернейм'].append(user.username or "Не указано")
        users_data['Пробная подписка'].append("Использована" if user.test_sub else "Нет")
        users_data['Промокод'].append("Использован" if user.used_promo else "Нет")

        user_keys = await get_user_keys(user.id)
        users_data['Кол-во ключей'].append(len(user_keys))

        if user_keys:
            keys_info = '\n'.join(f'{key.name} - {servers.get(key.server_id, "Unknown")}' for key in user_keys)
        else:
            keys_info = '-'
        users_data['Ключи'].append(keys_info)

        users_data['Дата появления'].append(user.created_at.strftime('%Y-%m-%d %H:%M:%S'))
        users_data['Ссылка'].append(user.enter_start_text or '-')

    out = io.BytesIO()
    workbook = xlsxwriter.Workbook(out)
    worksheet = workbook.add_worksheet('База пользователей')

    header_format = workbook.add_format({'bold': True, 'align': 'center'})
    cell_format = workbook.add_format({'text_wrap': True})

    headers = list(users_data.keys())
    for col_num, header in enumerate(headers):
        worksheet.write(0, col_num, header, header_format)

        column_data = [str(header)] + [str(value) for value in users_data[header]]
        max_length = max(len(cell) for cell in column_data)
        worksheet.set_column(col_num, col_num, max_length + 2)

    for row_num in range(len(users_data['№'])):
        for col_num, key in enumerate(headers):
            worksheet.write(row_num + 1, col_num, users_data[key][row_num], cell_format)

    workbook.close()
    out.seek(0)
    out.name = "users.xlsx"
    return out


async def export_promos_to_excel():
    """Создание статистики по промокодам"""
    promos_data = {'№': [], 'Код': [], 'Кол-во активаций': [], 'Конец': [], 'Макс. пользователей': [], 'Сумма': []}

    promos = await get_promos()
    for index, promo in enumerate(sorted(promos, key=lambda x: x.id), start=1):
        promos_data['№'].append(index)
        promos_data['Код'].append(promo.code)
        promos_data['Кол-во активаций'].append(len(promo.users))
        promos_data['Конец'].append(
            "-" if promo.finish_time is None else promo.finish_time.strftime('%Y-%m-%d %H:%M:%S'))
        promos_data['Макс. пользователей'].append("-" if promo.users_limit == -1 else promo.users_limit)
        promos_data['Сумма'].append(promo.price)

    out = io.BytesIO()
    workbook = xlsxwriter.Workbook(out)
    worksheet = workbook.add_worksheet('База промокодов')

    header_format = workbook.add_format({'bold': True, 'align': 'center'})
    cell_format = workbook.add_format({'text_wrap': True})

    headers = list(promos_data.keys())
    for col_num, header in enumerate(headers):
        worksheet.write(0, col_num, header, header_format)

        column_data = [str(header)] + [str(value) for value in promos_data[header]]
        max_length = max(len(cell) for cell in column_data)
        worksheet.set_column(col_num, col_num, max_length + 2)

    for row_num in range(len(promos_data['№'])):
        for col_num, key in enumerate(headers):
            worksheet.write(row_num + 1, col_num, promos_data[key][row_num], cell_format)

    workbook.close()
    out.seek(0)
    out.name = "promo.xlsx"
    return out


async def export_keys_to_excel():
    """Создание статистики по ключам"""
    keys_data = {
        '№': [],
        'Название': [],
        'Пользователь': [],
        'Сервер': [],
        'Начало': [],
        'Конец': [],
        'Ключ': [],
        'Источник': [],
        'Тестовый ключ?': [],
    }

    keys = await get_all_keys()
    servers = {server.id: server.host for server in await get_servers()}
    users_map = {user.id: user for user in await get_users()}

    for index, key in enumerate(sorted(keys, key=lambda x: x.id), start=1):
        keys_data['№'].append(index)
        keys_data['Название'].append(key.name)
        keys_data['Пользователь'].append(key.user_id)
        keys_data['Сервер'].append(servers.get(key.server_id, "Unknown"))
        keys_data['Начало'].append(key.start.strftime('%Y-%m-%d %H:%M:%S'))
        keys_data['Конец'].append(key.finish.strftime('%Y-%m-%d %H:%M:%S'))
        keys_data['Ключ'].append(key.key[:-1])
        user_obj = users_map.get(key.user_id)
        keys_data['Источник'].append(user_obj.enter_start_text if user_obj and user_obj.enter_start_text else '-')
        keys_data['Тестовый ключ?'].append('Да' if key.is_test else 'Нет')

    out = io.BytesIO()
    workbook = xlsxwriter.Workbook(out)
    worksheet = workbook.add_worksheet('База ключей')

    header_format = workbook.add_format({'bold': True, 'align': 'center'})
    cell_format = workbook.add_format({'text_wrap': True})

    headers = list(keys_data.keys())

    for col_num, header in enumerate(headers):
        worksheet.write(0, col_num, header, header_format)

        column_data = [str(header)] + [str(value) for value in keys_data[header]]
        max_length = max(len(cell) for cell in column_data)
        worksheet.set_column(col_num, col_num, max_length + 2)

    for row_num in range(len(keys_data['№'])):
        for col_num, key in enumerate(headers):
            worksheet.write(row_num + 1, col_num, keys_data[key][row_num], cell_format)

    workbook.close()
    out.seek(0)
    out.name = "keys.xlsx"
    return out


async def show_device_inst(message: Message, callback_data):
    logger.debug(f"clb_video_inst: {callback_data}")
    device = callback_data.device
    text_settings = await get_text_settings()

    video = getattr(text_settings, f"{device}_video")
    url = getattr(text_settings, f"{device}_url")
    kb = get_inline_markup_with_url("Скачать приложение", url) if url else None
    text = f"Инструкция для <b>{device.capitalize()}</b>:"

    if not video and not url:
        await message.answer(
            text="К сожалению для этого устройства не предоставлено инструкций, попробуйте позже")

    elif not video:
        await message.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=kb)

    await message.answer_video(
        caption=text,
        parse_mode=ParseMode.HTML,
        video=video,
        reply_markup=kb)
