from math import ceil
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.database.crud.servers import get_server_by_id, count_keys_by_server
from src.keyboards.admin_callback_datas import (
    EditTariffs,
    EditServers,
    EditInst,
    EditUserBanned,
    AddDaysKey,
    SpamMessages,
    EditPromo,
    AddTariffsToPromo,
)
from src.keyboards.inline_user import get_key_stats


def get_edit_servers_buttons(servers: list, page: int = 0) -> InlineKeyboardMarkup:
    """Возвращает инлайн_маркап редактирования серверов"""
    ITEMS_PER_PAGE = 10
    total_pages = ceil(len(servers) / ITEMS_PER_PAGE)
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    items_on_page = servers[start:end]

    btn_list = []
    for server in items_on_page:
        btn_list.append([
            InlineKeyboardButton(
                text=f"{server.host}",
                callback_data=EditServers(action="show_server", server_id=str(server.id), page=page).pack()
            ),
            InlineKeyboardButton(
                text="📶",
                callback_data=EditServers(action="auth_server", server_id=str(server.id), page=page).pack()
            ),
            InlineKeyboardButton(
                text="✏️",
                callback_data=EditServers(action="edit_server", server_id=str(server.id), page=page).pack()
            ),
            InlineKeyboardButton(
                text="🗑",
                callback_data=EditServers(action="delete_server", server_id=str(server.id), page=page).pack()
            ),
        ])

    if page > 0:
        btn_list.append([
            InlineKeyboardButton(
                text="⬅ Назад",
                callback_data=EditTariffs(action="pagination", tariff_id=None, page=page - 1).pack()
            )
        ])

    if page < total_pages - 1:
        btn_list.append([
            InlineKeyboardButton(
                text="Вперёд ➡",
                callback_data=EditTariffs(action="pagination", tariff_id=None, page=page + 1).pack()
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=btn_list)


async def get_transfer_server_buttons(callback_data_model, servers: list, page: int = 0) -> InlineKeyboardMarkup:
    """Возвращает инлайн_маркап выбора сервера для переноса ключа"""
    ITEMS_PER_PAGE = 5
    total_pages = ceil(len(servers) / ITEMS_PER_PAGE)
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    items_on_page = servers[start:end]

    btn_list = []

    for server in items_on_page:
        server = await get_server_by_id(server.id)
        count_keys = await count_keys_by_server(server.id)

        btn_list.append([
            InlineKeyboardButton(
                text=f"id: {server.id} | {server.host} | Ключей {count_keys} {'Тест' if server.is_test else ''}",
                callback_data=callback_data_model(
                    action="select",
                    server_id=str(server.id),
                    page=page
                ).pack()
            )
        ])

    if page > 0:
        btn_list.append([
            InlineKeyboardButton(
                text="⬅ Назад",
                callback_data=callback_data_model(
                    action="pagination",
                    server_id=None,
                    key_id=None,
                    page=page - 1
                ).pack()
            )
        ])

    if page < total_pages - 1:
        btn_list.append([
            InlineKeyboardButton(
                text="Вперёд ➡",
                callback_data=callback_data_model(
                    action="pagination",
                    server_id=None,
                    key_id=None,
                    page=page + 1
                ).pack()
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=btn_list)


async def get_keys_buttons(callback_data_model, keys: list, page: int = 0) -> InlineKeyboardMarkup:
    """Возвращает инлайн_маркап ключей"""
    ITEMS_PER_PAGE = 5
    total_pages = ceil(len(keys) / ITEMS_PER_PAGE)
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    items_on_page = keys[start:end]

    btn_list = []
    for key in items_on_page:
        key_stats = await get_key_stats(key.id)
        btn_list.append([
            InlineKeyboardButton(
                text=f"{key_stats} | serv_id:{key.server_id}",
                callback_data=callback_data_model(
                    action="select",
                    key_id=str(key.id),
                    page=page
                ).pack()
            )
        ])

    if page > 0:
        btn_list.append([
            InlineKeyboardButton(
                text="⬅ Назад",
                callback_data=callback_data_model(
                    action="pagination",
                    key_id=None,
                    page=page - 1
                ).pack()
            )
        ])

    if page < total_pages - 1:
        btn_list.append([
            InlineKeyboardButton(
                text="Вперёд ➡",
                callback_data=callback_data_model(
                    action="pagination",
                    key_id=None,
                    page=page + 1
                ).pack()
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=btn_list)


def get_edit_tariffs_buttons(tariffs: list, page: int = 0) -> InlineKeyboardMarkup:
    """Возвращает инлайн_маркап редактирования тарифов"""
    ITEMS_PER_PAGE = 5
    total_pages = ceil(len(tariffs) / ITEMS_PER_PAGE)
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    items_on_page = tariffs[start:end]

    btn_list = []
    for tariff in items_on_page:
        btn_list.append([
            InlineKeyboardButton(
                text=f"{tariff.name} - {tariff.price}₽",
                callback_data=EditTariffs(action="show_tariff", tariff_id=str(tariff.id), page=page).pack()
            ),
            InlineKeyboardButton(
                text="✏️",
                callback_data=EditTariffs(action="edit_tariff", tariff_id=str(tariff.id), page=page).pack()
            ),
            InlineKeyboardButton(
                text="🗑",
                callback_data=EditTariffs(action="delete_tariff", tariff_id=str(tariff.id), page=page).pack()
            ),
        ])

    if page > 0:
        btn_list.append([
            InlineKeyboardButton(
                text="⬅ Назад",
                callback_data=EditTariffs(action="pagination", tariff_id=None, page=page - 1).pack()
            )
        ])

    if page < total_pages - 1:
        btn_list.append([
            InlineKeyboardButton(
                text="Вперёд ➡",
                callback_data=EditTariffs(action="pagination", tariff_id=None, page=page + 1).pack()
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=btn_list)


def get_edit_promos_buttons(promos: list, page: int = 0) -> InlineKeyboardMarkup:
    """Возвращает инлайн_маркап редактирования промокодов"""
    ITEMS_PER_PAGE = 5
    total_pages = ceil(len(promos) / ITEMS_PER_PAGE)
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    items_on_page = promos[start:end]

    btn_list = []
    for promo in items_on_page:
        btn_list.append([
            InlineKeyboardButton(
                text=f"{promo.code} - {promo.price}%",
                callback_data=EditPromo(action="show_promo", promo_id=str(promo.id), page=page).pack()
            ),
            InlineKeyboardButton(
                text="✏️",
                callback_data=EditPromo(action="edit_promo", promo_id=str(promo.id), page=page).pack()
            ),
            InlineKeyboardButton(
                text="🗑",
                callback_data=EditPromo(action="delete_promo", promo_id=str(promo.id), page=page).pack()
            ),
        ])

    if page > 0:
        btn_list.append([
            InlineKeyboardButton(
                text="⬅ Назад",
                callback_data=EditPromo(action="pagination", promo_id=None, page=page - 1).pack()
            )
        ])

    if page < total_pages - 1:
        btn_list.append([
            InlineKeyboardButton(
                text="Вперёд ➡",
                callback_data=EditPromo(action="pagination", promo_id=None, page=page + 1).pack()
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=btn_list)


def get_edit_tariff_buttons(tariff_id: int, page: int) -> InlineKeyboardMarkup:
    btn_list = [
        [InlineKeyboardButton(text="Изменить название", callback_data=EditTariffs(action="change_name", tariff_id=tariff_id, page=page).pack())],
        [InlineKeyboardButton(text="Изменить стоимость", callback_data=EditTariffs(action="change_price", tariff_id=tariff_id, page=page).pack())],
        [InlineKeyboardButton(text="Изменить длительность", callback_data=EditTariffs(action="change_days", tariff_id=tariff_id, page=page).pack())],
        [InlineKeyboardButton(text="Назад", callback_data=EditTariffs(action="back", tariff_id=tariff_id, page=page).pack())],
    ]
    return InlineKeyboardMarkup(inline_keyboard=btn_list)


def get_edit_server_buttons(server_id: int, page: int) -> InlineKeyboardMarkup:
    btn_list = [
        [
            InlineKeyboardButton(text="Изменить адрес", callback_data=EditServers(action="change_address", server_id=server_id, page=page).pack()),
            InlineKeyboardButton(text="Изменить логин", callback_data=EditServers(action="change_login", server_id=server_id, page=page).pack()),
        ],
        [
            InlineKeyboardButton(text="Изменить пароль", callback_data=EditServers(action="change_password", server_id=server_id, page=page).pack()),
            InlineKeyboardButton(text="Изменить количество ключей", callback_data=EditServers(action="change_max_users", server_id=server_id, page=page).pack()),
        ],
        [
            InlineKeyboardButton(text="Изменить Тест статус", callback_data=EditServers(action="change_test", server_id=server_id, page=page).pack())
        ],
        [
            InlineKeyboardButton(text="Изменить flow xtls-rprx-vision", callback_data=EditServers(action="change_flow", server_id=server_id, page=page).pack())
        ],
        [
            InlineKeyboardButton(text="Назад", callback_data=EditServers(action="back", server_id=server_id, page=page).pack())
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=btn_list)


def get_edit_promo_buttons(promo_id: int, page: int) -> InlineKeyboardMarkup:
    btn_list = [
        [
            InlineKeyboardButton(text="Изменить код", callback_data=EditPromo(action="change_code", promo_id=promo_id, page=page).pack()),
            InlineKeyboardButton(text="Изменить скидку", callback_data=EditPromo(action="change_price", promo_id=promo_id, page=page).pack()),
        ],
        [
            InlineKeyboardButton(text="Изменить кол-во пользователей", callback_data=EditPromo(action="change_max_users", promo_id=promo_id, page=page).pack()),
            InlineKeyboardButton(text="Изменить дату конца", callback_data=EditPromo(action="change_finish_date", promo_id=promo_id, page=page).pack()),
        ],
        [
            InlineKeyboardButton(text="Изменить тарифы", callback_data=EditPromo(action="change_tariffs", promo_id=promo_id, page=page).pack())
        ],
        [
            InlineKeyboardButton(text="Назад", callback_data=EditPromo(action="back", promo_id=promo_id, page=page).pack())
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=btn_list)


def get_admin_tariff_buttons(tariffs):
    buttons = []
    for tariff in tariffs:
        buttons.append([
            InlineKeyboardButton(
                text=f"{tariff.name}",
                callback_data=AddTariffsToPromo(action="select", tariff_id=str(tariff.id)).pack()
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="Подтвердить",
            callback_data=AddTariffsToPromo(action="confirm_change", tariff_id=None).pack()
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def edit_inline_keyboard_select_tariff(old_reply_markup: list, callback_data):
    new_reply_markup = old_reply_markup.copy()
    symbol = "✅ "
    for button in old_reply_markup:
        i_in_old = old_reply_markup.index(button)
        if button[0].callback_data == callback_data:
            if symbol not in button[0].text:
                new_reply_markup.pop(i_in_old)
                new_reply_markup.insert(
                    i_in_old,
                    [InlineKeyboardButton(text=f"{symbol}{button[0].text}", callback_data=button[0].callback_data)]
                )
                return InlineKeyboardMarkup(inline_keyboard=new_reply_markup)


def get_edit_inst_menu(device: str):
    btn_list = [
        [InlineKeyboardButton(text="Посмотреть", callback_data=EditInst(action="show", device=device).pack())],
        [
            InlineKeyboardButton(text="Изменить видео", callback_data=EditInst(action="change_video", device=device).pack()),
            InlineKeyboardButton(text="Изменить ссылку", callback_data=EditInst(action="change_link", device=device).pack()),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=btn_list)


def get_spam_menu():
    btn_list = [
        [
            InlineKeyboardButton(text="Конкретному пользователю", callback_data=SpamMessages(action="user").pack()),
            InlineKeyboardButton(text="Всем пользователям", callback_data=SpamMessages(action="all_users").pack()),
        ],
        [InlineKeyboardButton(text="Назад", callback_data=SpamMessages(action="back").pack())],
    ]
    return InlineKeyboardMarkup(inline_keyboard=btn_list)


def get_edit_ban_menu():
    btn_list = [
        [
            InlineKeyboardButton(text="Блокировать", callback_data=EditUserBanned(action="ban").pack()),
            InlineKeyboardButton(text="Разблокировать", callback_data=EditUserBanned(action="unban").pack()),
        ],
        [InlineKeyboardButton(text="Назад", callback_data=EditUserBanned(action="back").pack())],
    ]
    return InlineKeyboardMarkup(inline_keyboard=btn_list)


def get_confirm_buttons(callback_data_model, **kwargs) -> InlineKeyboardMarkup:
    btn_list = [
        [
            InlineKeyboardButton(text="+ Подтвердить", callback_data=callback_data_model(**kwargs, action="confirm_change").pack()),
            InlineKeyboardButton(text="- Отменить", callback_data=callback_data_model(**kwargs, action="cancel_change").pack()),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=btn_list)