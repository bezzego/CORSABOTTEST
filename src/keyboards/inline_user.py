from datetime import datetime, timezone
from math import ceil
from typing import Union
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from src.database.crud.keys import get_key_by_id
from src.keyboards.user_callback_datas import Tariffs, MyKeys
from src.utils.utils import get_key_name_without_user_id, get_days_hours_by_ts
from urllib.parse import urlparse
from src.logs import getLogger

logger = getLogger(__name__)


async def get_key_stats(key_id: int, include_traffic: bool = False) -> str:
    """Возвращает статистику ключа. Если include_traffic=True и ключ bypass — добавляет данные по трафику с панели."""
    key = await get_key_by_id(key_id)
    now = datetime.now(timezone.utc)
    finish = key.finish if key.finish.tzinfo else key.finish.replace(tzinfo=timezone.utc)

    if finish >= now:
        ts = (finish - now).total_seconds()
        days, hours, minutes = get_days_hours_by_ts(ts)
        base = f"🔑{get_key_name_without_user_id(key)} Осталось: {days} дн. {hours} ч. {minutes} м."
    else:
        ts = (now - finish).total_seconds()
        days, hours, minutes = get_days_hours_by_ts(ts)
        base = f"🔑{get_key_name_without_user_id(key)} Истек: {days} дн. {hours} ч. {minutes} м. назад"

    if not include_traffic or not key.is_bypass:
        return base

    try:
        from src.database.crud.servers import get_server_by_id
        from src.services.keys import X3UI
        server = await get_server_by_id(key.server_id)
        if server:
            traffic = X3UI(server).get_client_traffic(key.name)
            if traffic and traffic["total"] > 0:
                used_gb = (traffic["up"] + traffic["down"]) / 1024 ** 3
                limit_gb = traffic["total"] / 1024 ** 3
                remaining_gb = max(0.0, limit_gb - used_gb)
                return base + f"\nТрафик: {used_gb:.1f} GB из {limit_gb:.1f} GB (осталось {remaining_gb:.1f} GB)"
    except Exception:
        logger.warning("get_key_stats: не удалось получить трафик для key_id=%s", key_id, exc_info=True)

    return base


def get_select_device_buttons(callback_data_model, **kwargs):
    """Возвращает инлайн_маркап с выбором девайсам, с указанной class callback_data и возможностью добавлять **kwargs"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="iPhone", callback_data=callback_data_model(**kwargs, action="select_device", device="iphone").pack()),
         InlineKeyboardButton(text="Android", callback_data=callback_data_model(**kwargs, action="select_device", device="android").pack())],
        [InlineKeyboardButton(text="Mac OS", callback_data=callback_data_model(**kwargs, action="select_device", device="macos").pack()),
         InlineKeyboardButton(text="Windows", callback_data=callback_data_model(**kwargs, action="select_device", device="windows").pack())],
        [InlineKeyboardButton(text="TV", callback_data=callback_data_model(**kwargs, action="select_device", device="tv").pack())]
    ])


def get_tariffs_buttons(tariffs, key_id: int = None) -> Union[InlineKeyboardMarkup, list]:
    """Возвращает инлайн_маркап со всеми тарифами"""
    btn_list = []
    tariffs_text = []
    for tariff in tariffs:
        btn_list.append([InlineKeyboardButton(text=f"{tariff.name} - {tariff.price}₽", callback_data=Tariffs(action="select_tariff", tariff_id=str(tariff.id), device=None, key_id=key_id).pack())])
        tariffs_text.append(f"<b>📅 {tariff.name}</b> — {tariff.price}₽ {f'(🎁 {tariff.discount}% скидка)' if tariff.discount else ''}")

    return InlineKeyboardMarkup(inline_keyboard=btn_list), tariffs_text


def edit_inline_keyboard_select_tariff(old_reply_markup: list, callback_data: str):
    """Редактирует инлайн_маркап при выборе тарифа, добавляет и удаляет галочку на элементе"""
    new_reply_markup = old_reply_markup.copy()
    symbol = "✅ "
    for button in old_reply_markup:
        i_in_old = old_reply_markup.index(button)
        if button[0].callback_data != callback_data:
            if symbol in button[0].text:
                new_reply_markup.pop(i_in_old)
                new_reply_markup.insert(i_in_old, [
                    InlineKeyboardButton(text=button[0].text.replace(symbol, ""), callback_data=button[0].callback_data)])

        if button[0].callback_data == callback_data:
            new_reply_markup.pop(i_in_old)
            new_reply_markup.insert(i_in_old, [InlineKeyboardButton(text=f"{symbol}{button[0].text}", callback_data=button[0].callback_data)])

    return InlineKeyboardMarkup(inline_keyboard=new_reply_markup)


def edit_inline_keyboard_select_device(old_reply_markup: list, callback_data: str):
    """Редактирует инлайн_маркап при выборе тарифа-девайса, добавляет и удаляет галочку на элементе"""
    new_reply_markup = old_reply_markup.copy()
    symbol = "✅ "
    for i in range(2):
        for button in old_reply_markup[i]:
            i_in_old = old_reply_markup[i].index(button)
            if button.callback_data != callback_data:
                if symbol in button.text:
                    new_reply_markup[i].pop(i_in_old)
                    new_reply_markup[i].insert(i_in_old,
                                               InlineKeyboardButton(text=button.text.replace(symbol, ""), callback_data=button.callback_data))

            if button.callback_data == callback_data:
                new_reply_markup[i].pop(i_in_old)
                new_reply_markup[i].insert(i_in_old, InlineKeyboardButton(text=f"{symbol}{button.text}", callback_data=button.callback_data))

    return InlineKeyboardMarkup(inline_keyboard=new_reply_markup)


def edit_inline_markup_add_symbol(old_reply_markup: list, callback_data: str, index_elem: int):
    """Возвращает инлайн_маркап с добавлением символа в кнопку по индексу"""
    new_reply_markup = old_reply_markup.copy()
    button = old_reply_markup[index_elem][0]
    symbol = "✅ "

    new_reply_markup.pop(index_elem)
    new_reply_markup.insert(index_elem, [InlineKeyboardButton(text=f"{symbol}{button.text}", callback_data=button.callback_data)])
    return InlineKeyboardMarkup(inline_keyboard=new_reply_markup)


def get_buy_tariff_buttons(callback_data: Tariffs):
    """Создает инлайн_маркап для покупки тарифа, после выбора девайса"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Купить тариф", callback_data=Tariffs(action="buy_tariff", tariff_id=callback_data.tariff_id, device=callback_data.device, key_id=callback_data.key_id).pack())],
        [InlineKeyboardButton(text="Активировать промокод", callback_data=Tariffs(action="promo", tariff_id=callback_data.tariff_id, device=callback_data.device, key_id=callback_data.key_id).pack())]
    ])


def get_payments_buttons(callback_data: Tariffs, pay_url: str):
    """Создает инлайн_маркап для меню платежа, после выбора нажатия на купить"""
    rows = []
    # validate URL
    try:
        parsed = urlparse(pay_url or "")
        valid = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        valid = False

    if valid:
        rows.append([InlineKeyboardButton(text="✅Перейти к оплате", url=pay_url)])
    else:
        logger.warning("Invalid pay_url provided to get_payments_buttons: %s", pay_url)

    rows.append([InlineKeyboardButton(text="🔙Отменить платеж", callback_data=Tariffs(action="cancel_payment", tariff_id=callback_data.tariff_id, device=callback_data.device, key_id=callback_data.key_id).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_inline_markup_with_url(text: str, url: str):
    """Возвращает инлайн_маркап с кнопкой text+url"""
    try:
        parsed = urlparse(url or "")
        valid = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        valid = False

    if not valid:
        logger.warning("get_inline_markup_with_url called with invalid url: %s", url)
        # return empty markup (no url button)
        return InlineKeyboardMarkup(inline_keyboard=[])

    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, url=url)]])


async def get_inline_markup_my_keys(keys: list, page: int = 0):
    """Возвращает инлайн_маркап с ключами юзера"""
    KEYS_PER_PAGE = 5
    total_pages = ceil(len(keys) / KEYS_PER_PAGE)
    start = page * KEYS_PER_PAGE
    end = start + KEYS_PER_PAGE
    keys_on_page = keys[start:end]

    btn_list = []
    for key in keys_on_page:
        key_stats = await get_key_stats(key.id)
        btn_list.append([InlineKeyboardButton(text=f"{key_stats}", callback_data=MyKeys(button_type="title", key_id=key.id, page=page).pack())])
        if not key.is_test:
            btn_list.append(
                [InlineKeyboardButton(text="Скачать", callback_data=MyKeys(button_type="download", key_id=key.id, page=page).pack()),
                 InlineKeyboardButton(text="Продлить", callback_data=MyKeys(button_type="prolong", key_id=key.id, page=page).pack())])
        else:
            btn_list.append(
                [InlineKeyboardButton(text="Скачать", callback_data=MyKeys(button_type="download", key_id=key.id, page=page).pack())])

    if page > 0:
        btn_list.append(
            [InlineKeyboardButton(text="⬅ Назад", callback_data=MyKeys(button_type="pagination", key_id=None, page=page - 1).pack())]
        )
    if page < total_pages - 1:
        btn_list.append(
            [InlineKeyboardButton(text="Вперёд ➡", callback_data=MyKeys(button_type="pagination", key_id=None, page=page + 1).pack())]
        )

    return InlineKeyboardMarkup(inline_keyboard=btn_list)


