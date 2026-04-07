from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from src.database.crud.keys import get_all_keys_server
from src.database.crud.servers import get_servers, get_server_by_id, change_server_value, delete_server, add_server
from src.keyboards.admin_callback_datas import EditServers, AddServer
from src.keyboards.inline_admin import get_edit_servers_buttons, get_edit_server_buttons, get_confirm_buttons
from src.keyboards.reply_admin import get_reply_admin_btn
from src.logs import getLogger
from src.services.keys_manager import check_connection
from src.states.admin_states import AdminMenu, AdminServers
from src.utils.utils_async import auth_admin_role

router = Router(name=__name__)
logger = getLogger(__name__)

"""───────────────────────────────────────────── Func ─────────────────────────────────────────────"""


async def show_servers(message: Message):
    servers = await get_servers()

    if not servers:
        await message.answer(
            text="⚠️ Нету серверов в бд.")
        return

    await message.answer(
        text="Список серверов:",
        reply_markup=get_edit_servers_buttons(servers))


async def show_server(server_id: int, callback: CallbackQuery, reply_markup=None):
    server = await get_server_by_id(server_id)
    keys_count = await get_all_keys_server(server_id)
    if server:
        await callback.answer()
        bypass_info = ""
        if server.is_bypass:
            bypass_info = (
                f"\nЛимит трафика: <code>{server.traffic_limit_gb} ГБ</code>"
                f"\nШлюз (адрес): <code>{server.gateway_host}</code>"
                f"\nШлюз (порт): <code>{server.gateway_port}</code>"
            )
        return await callback.message.answer(
            text=f"""
ID: <code>{server.id}</code>
Сервер: <code>{server.host}</code>
Логин: <code>{server.login}</code>
Пароль: <code>{server.password}</code>
Макс ключей: <code>{server.max_users}</code>
Ключей на сервере: <code>{len(keys_count)}</code>
Тестовый: <code>{server.is_test}</code>
flow xtls-rprx-vision: <code>{server.flow_enabled}</code>
Обход белых списков: <code>{server.is_bypass}</code>{bypass_info}
""",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup)


async def auth_server(server_id: int, callback: CallbackQuery, reply_markup=None):
    server = await get_server_by_id(server_id)
    if server:
        is_test = "TEST" if server.is_test else "NOT TEST"
        text = f"Проверка соединения с сервером <code>[{is_test}] {server.host}</code>..."
        msg = await callback.message.answer(
            text=text,
            parse_mode=ParseMode.HTML)
        if await check_connection(server):
            await msg.edit_text(
                text=text + f"\n\nСоединение успешно установлено ✅",
                parse_mode=ParseMode.HTML)

        else:
            await msg.edit_text(
                text=text + f"\n\nСоединение не установлено ❌\nПроверьте данные подключения.",
                parse_mode=ParseMode.HTML)

        await callback.answer()

"""───────────────────────────────────────────── Commands and Reply ─────────────────────────────────────────────"""


@router.message(F.text == get_reply_admin_btn("adm_edit"), StateFilter(AdminMenu.servers_menu, AdminServers.edit))
@auth_admin_role
async def cmd_edit_servers(message: Message, state: FSMContext):
    await show_servers(message)
    await state.set_state(AdminServers.edit)

"""───────────────────────────────────────────── Callbacks Edit Servers ─────────────────────────────────────────────"""


@router.callback_query(EditServers.filter(F.action == "pagination"), AdminServers.edit)
async def clb_paginate_servers(callback: CallbackQuery, callback_data: EditServers):
    servers = await get_servers()
    new_markup = get_edit_servers_buttons(servers, callback_data.page)

    await callback.message.edit_reply_markup(reply_markup=new_markup)
    await callback.answer()


@router.callback_query(EditServers.filter(F.action == "show_server"), AdminServers.edit)
async def clb_show_server(callback: CallbackQuery, callback_data: EditServers):
    await show_server(callback_data.server_id, callback)


@router.callback_query(EditServers.filter(F.action == "auth_server"), AdminServers.edit)
async def clb_auth_server(callback: CallbackQuery, callback_data: EditServers):
    await auth_server(callback_data.server_id, callback)


@router.callback_query(EditServers.filter(F.action == "edit_server"), AdminServers.edit)
async def clb_edit_server(callback: CallbackQuery, callback_data: EditServers):
    msg = await show_server(callback_data.server_id, callback, get_edit_server_buttons(callback_data.server_id, callback_data.page))
    if not msg:
        return


@router.callback_query(EditServers.filter(F.action == "delete_server"), AdminServers.edit)
async def clb_delete_server(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    await callback.answer()
    server = await get_server_by_id(callback_data.server_id)
    await callback.message.answer(
        text=f"Вы уверены что хотите удалить сервер: <b>{server.host}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_confirm_buttons(EditServers, server_id=callback_data.server_id, page=callback_data.page))

    await state.set_state(AdminServers.delete_confirm)


@router.message(F.text == get_reply_admin_btn("adm_add"), StateFilter(AdminMenu.servers_menu, AdminServers.edit))
@auth_admin_role
async def cmd_add_new_server(message: Message, state: FSMContext):
    await message.answer(
        text="<b>Создание нового сервера:</b>\n\nВведите адрес (Ip хост) для сервера  ⬇️",
        parse_mode=ParseMode.HTML)
    await state.set_state(AdminServers.add_address)


@router.callback_query(EditServers.filter(F.action == "back"))
async def clb_cancel(callback: CallbackQuery, callback_data: EditServers):
    await callback.message.delete()


@router.callback_query(EditServers.filter(F.action == "cancel_change"), StateFilter(
    AdminServers.change_address_confirm, AdminServers.change_login_confirm, AdminServers.change_password_confirm,
    AdminServers.change_max_users_confirm, AdminServers.change_test_confirm, AdminServers.change_flow_confirm,
    AdminServers.change_is_bypass_confirm, AdminServers.change_traffic_limit_confirm,
    AdminServers.change_gateway_host_confirm, AdminServers.change_gateway_port_confirm))
async def clb_change_cancel(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Успешно, отмена изменений!")
    await state.clear()


"""───────────────────────────────────────────── Callbacks Edit Host ─────────────────────────────────────────────"""


@router.callback_query(EditServers.filter(F.action == "change_address"))
async def clb_change_host(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        text="Введите новое адрес для сервера ⬇️")
    await state.set_state(AdminServers.change_address)
    await state.update_data(callback_data=callback_data)


@router.message(AdminServers.change_address)
async def get_text_change_address(message: Message, state: FSMContext):
    try:
        state_data = await state.get_data()
        callback_data = state_data["callback_data"]
        await message.answer(
            text=f"Вы уверены что хотите изменить хост на: <code>{message.text}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_confirm_buttons(EditServers, server_id=callback_data.server_id, page=callback_data.page))

        await state.set_state(AdminServers.change_address_confirm)
        await state.update_data(new_address=message.text)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(EditServers.filter(F.action == "confirm_change"), AdminServers.change_address_confirm)
async def clb_change_address_confirm(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    state_data = await state.get_data()
    await change_server_value(int(callback_data.server_id), host=state_data["new_address"])
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно, изменение адрес сервера!\n\nНовый адрес - <code>{state_data['new_address']}</code>",
        parse_mode=ParseMode.HTML)

    await show_servers(callback.message)
    await state.set_state(AdminServers.edit)

"""───────────────────────────────────────────── Callbacks Edit Login ─────────────────────────────────────────────"""


@router.callback_query(EditServers.filter(F.action == "change_login"))
async def clb_change_login(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        text="Введите новый логин для сервера ⬇️")
    await state.set_state(AdminServers.change_login)
    await state.update_data(callback_data=callback_data)


@router.message(AdminServers.change_login)
async def get_text_change_login(message: Message, state: FSMContext):
    try:
        state_data = await state.get_data()
        callback_data = state_data["callback_data"]
        await message.answer(
            text=f"Вы уверены что хотите изменить логин на: <code>{message.text}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_confirm_buttons(EditServers, server_id=callback_data.server_id, page=callback_data.page))

        await state.set_state(AdminServers.change_login_confirm)
        await state.update_data(new_login=message.text)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(EditServers.filter(F.action == "confirm_change"), AdminServers.change_login_confirm)
async def clb_change_login_confirm(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    state_data = await state.get_data()
    await change_server_value(int(callback_data.server_id), login=state_data["new_login"])
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно, изменение логин сервера!\n\nНовый логин - <code>{state_data['new_login']}</code>",
        parse_mode=ParseMode.HTML)

    await show_servers(callback.message)
    await state.set_state(AdminServers.edit)

"""───────────────────────────────────────────── Callbacks Edit Password ─────────────────────────────────────────────"""


@router.callback_query(EditServers.filter(F.action == "change_password"))
async def clb_change_password(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        text="Введите новый пароль для сервера ⬇️")
    await state.set_state(AdminServers.change_password)
    await state.update_data(callback_data=callback_data)


@router.message(AdminServers.change_password)
async def get_text_change_password(message: Message, state: FSMContext):
    try:
        state_data = await state.get_data()
        callback_data = state_data["callback_data"]
        await message.answer(
            text=f"Вы уверены что хотите изменить пароль на: <code>{message.text}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_confirm_buttons(EditServers, server_id=callback_data.server_id, page=callback_data.page))

        await state.set_state(AdminServers.change_password_confirm)
        await state.update_data(new_password=message.text)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(EditServers.filter(F.action == "confirm_change"), AdminServers.change_password_confirm)
async def clb_change_password_confirm(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    state_data = await state.get_data()
    await change_server_value(int(callback_data.server_id), password=state_data["new_password"])
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно, изменение пароля сервера!\n\nНовый пароль - <code>{state_data['new_password']}</code>",
        parse_mode=ParseMode.HTML)

    await show_servers(callback.message)
    await state.set_state(AdminServers.edit)

"""───────────────────────────────────────────── Callbacks Edit Max Users ─────────────────────────────────────────────"""


@router.callback_query(EditServers.filter(F.action == "change_max_users"))
async def clb_change_max_users(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        text="Введите новое количество слотов для сервера ⬇️")
    await state.set_state(AdminServers.change_max_users)
    await state.update_data(callback_data=callback_data)


@router.message(AdminServers.change_max_users)
async def get_text_change_max_users(message: Message, state: FSMContext):
    try:
        if not message.text.isdigit():
            await message.answer("Ошибка! Введите числовой тип, попробуйте снова.")
            return

        state_data = await state.get_data()
        callback_data = state_data["callback_data"]
        await message.answer(
            text=f"Вы уверены что хотите изменить количество слотов на: <code>{message.text}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_confirm_buttons(EditServers, server_id=callback_data.server_id, page=callback_data.page))

        await state.set_state(AdminServers.change_max_users_confirm)
        await state.update_data(new_max_users=message.text)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(EditServers.filter(F.action == "confirm_change"), AdminServers.change_max_users_confirm)
async def clb_change_max_users_confirm(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    state_data = await state.get_data()
    await change_server_value(int(callback_data.server_id), max_users=int(state_data["new_max_users"]))
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно, изменение количество слотов сервера!\n\nНовые количество - <code>{state_data['new_max_users']}</code>",
        parse_mode=ParseMode.HTML)

    await show_servers(callback.message)
    await state.set_state(AdminServers.edit)

"""───────────────────────────────────────────── Callbacks Edit Is Test ─────────────────────────────────────────────"""


@router.callback_query(EditServers.filter(F.action == "change_test"))
async def clb_change_test_status(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        text="Введите новый режим для сервера (<code>test</code> или <code>work</code>) сервера ⬇️",
        parse_mode=ParseMode.HTML)
    await state.set_state(AdminServers.change_test)
    await state.update_data(callback_data=callback_data)


@router.message(AdminServers.change_test)
async def get_text_change_test_status(message: Message, state: FSMContext):
    try:
        if message.text not in ("test", "work"):
            await message.answer("Ошибка! Введите 'test' или 'work', попробуйте снова.")
            return

        state_data = await state.get_data()
        callback_data = state_data["callback_data"]
        await message.answer(
            text=f"Вы уверены что хотите изменить режим на: <code>{message.text}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_confirm_buttons(EditServers, server_id=callback_data.server_id, page=callback_data.page))

        await state.set_state(AdminServers.change_test_confirm)
        await state.update_data(new_test_status=message.text)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(EditServers.filter(F.action == "confirm_change"), AdminServers.change_test_confirm)
async def clb_change_test_status_confirm(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    state_data = await state.get_data()
    if state_data["new_test_status"] == "work":
        status_test = False
    else:
        status_test = True
    await change_server_value(int(callback_data.server_id), is_test=status_test)
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно, изменен режим сервера!\n\nНовый режим - <code>{state_data['new_test_status']}</code>",
        parse_mode=ParseMode.HTML)

    await show_servers(callback.message)
    await state.set_state(AdminServers.edit)


"""───────────────────────────────────────────── Callbacks Edit Flow ─────────────────────────────────────────────"""


@router.callback_query(EditServers.filter(F.action == "change_flow"))
async def clb_change_flow(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        text="Включать flow xtls-rprx-vision при создании ключей? (введите <code>yes</code>/<code>no</code>)",
        parse_mode=ParseMode.HTML)
    await state.set_state(AdminServers.change_flow)
    await state.update_data(callback_data=callback_data)


@router.message(AdminServers.change_flow)
async def get_text_change_flow(message: Message, state: FSMContext):
    try:
        text = message.text.strip().lower()
        if text not in ("yes", "no", "да", "нет", "y", "n", "+", "-"):
            await message.answer("Ошибка! Введите yes/no (да/нет), попробуйте снова.")
            return

        flow_enabled = text in ("yes", "да", "y", "+")
        state_data = await state.get_data()
        callback_data = state_data["callback_data"]
        await message.answer(
            text=(
                "Вы уверены что хотите "
                f"{'включить' if flow_enabled else 'выключить'} flow xtls-rprx-vision "
                "для этого сервера?"
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=get_confirm_buttons(EditServers, server_id=callback_data.server_id, page=callback_data.page))

        await state.set_state(AdminServers.change_flow_confirm)
        await state.update_data(new_flow_enabled=flow_enabled)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(EditServers.filter(F.action == "confirm_change"), AdminServers.change_flow_confirm)
async def clb_change_flow_confirm(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    state_data = await state.get_data()
    await change_server_value(int(callback_data.server_id), flow_enabled=state_data["new_flow_enabled"])
    await callback.answer()
    await callback.message.answer(
        text=(
            "Успешно, изменён режим flow!\n\n"
            f"Новый режим flow xtls-rprx-vision: <code>{state_data['new_flow_enabled']}</code>"
        ),
        parse_mode=ParseMode.HTML)

    await show_servers(callback.message)
    await state.set_state(AdminServers.edit)


"""───────────────────────────────────────────── Callbacks Edit Bypass Fields ─────────────────────────────────────────────"""


@router.callback_query(EditServers.filter(F.action == "change_is_bypass"))
async def clb_change_is_bypass(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        text="Включить обход белых списков для этого сервера? (введите <code>да</code>/<code>нет</code>)",
        parse_mode=ParseMode.HTML)
    await state.set_state(AdminServers.change_is_bypass)
    await state.update_data(callback_data=callback_data)


@router.message(AdminServers.change_is_bypass)
async def get_text_change_is_bypass(message: Message, state: FSMContext):
    try:
        text = message.text.strip().lower()
        if text not in ("yes", "no", "да", "нет", "y", "n", "+", "-"):
            await message.answer("Ошибка! Введите да/нет, попробуйте снова.")
            return

        is_bypass = text in ("yes", "да", "y", "+")
        state_data = await state.get_data()
        callback_data = state_data["callback_data"]
        await message.answer(
            text=f"Вы уверены что хотите {'включить' if is_bypass else 'выключить'} обход белых списков?",
            reply_markup=get_confirm_buttons(EditServers, server_id=callback_data.server_id, page=callback_data.page))

        await state.set_state(AdminServers.change_is_bypass_confirm)
        await state.update_data(new_is_bypass=is_bypass)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(EditServers.filter(F.action == "confirm_change"), AdminServers.change_is_bypass_confirm)
async def clb_change_is_bypass_confirm(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    state_data = await state.get_data()
    await change_server_value(int(callback_data.server_id), is_bypass=state_data["new_is_bypass"])
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно! Обход белых списков: <code>{state_data['new_is_bypass']}</code>",
        parse_mode=ParseMode.HTML)
    await show_servers(callback.message)
    await state.set_state(AdminServers.edit)


@router.callback_query(EditServers.filter(F.action == "change_traffic_limit"))
async def clb_change_traffic_limit(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        text="Введите новый лимит трафика в ГБ (целое число):")
    await state.set_state(AdminServers.change_traffic_limit)
    await state.update_data(callback_data=callback_data)


@router.message(AdminServers.change_traffic_limit)
async def get_text_change_traffic_limit(message: Message, state: FSMContext):
    try:
        if not message.text.strip().isdigit():
            await message.answer("Ошибка! Введите целое число (ГБ), попробуйте снова.")
            return

        state_data = await state.get_data()
        callback_data = state_data["callback_data"]
        new_limit = int(message.text.strip())
        await message.answer(
            text=f"Вы уверены что хотите установить лимит трафика: <code>{new_limit} ГБ</code>?",
            parse_mode=ParseMode.HTML,
            reply_markup=get_confirm_buttons(EditServers, server_id=callback_data.server_id, page=callback_data.page))

        await state.set_state(AdminServers.change_traffic_limit_confirm)
        await state.update_data(new_traffic_limit=new_limit)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(EditServers.filter(F.action == "confirm_change"), AdminServers.change_traffic_limit_confirm)
async def clb_change_traffic_limit_confirm(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    state_data = await state.get_data()
    await change_server_value(int(callback_data.server_id), traffic_limit_gb=state_data["new_traffic_limit"])
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно! Лимит трафика: <code>{state_data['new_traffic_limit']} ГБ</code>",
        parse_mode=ParseMode.HTML)
    await show_servers(callback.message)
    await state.set_state(AdminServers.edit)


@router.callback_query(EditServers.filter(F.action == "change_gateway_host"))
async def clb_change_gateway_host(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        text="Введите новый адрес шлюза (IP или домен):")
    await state.set_state(AdminServers.change_gateway_host)
    await state.update_data(callback_data=callback_data)


@router.message(AdminServers.change_gateway_host)
async def get_text_change_gateway_host(message: Message, state: FSMContext):
    try:
        state_data = await state.get_data()
        callback_data = state_data["callback_data"]
        new_host = message.text.strip()
        await message.answer(
            text=f"Вы уверены что хотите установить адрес шлюза: <code>{new_host}</code>?",
            parse_mode=ParseMode.HTML,
            reply_markup=get_confirm_buttons(EditServers, server_id=callback_data.server_id, page=callback_data.page))

        await state.set_state(AdminServers.change_gateway_host_confirm)
        await state.update_data(new_gateway_host=new_host)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(EditServers.filter(F.action == "confirm_change"), AdminServers.change_gateway_host_confirm)
async def clb_change_gateway_host_confirm(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    state_data = await state.get_data()
    await change_server_value(int(callback_data.server_id), gateway_host=state_data["new_gateway_host"])
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно! Адрес шлюза: <code>{state_data['new_gateway_host']}</code>",
        parse_mode=ParseMode.HTML)
    await show_servers(callback.message)
    await state.set_state(AdminServers.edit)


@router.callback_query(EditServers.filter(F.action == "change_gateway_port"))
async def clb_change_gateway_port(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        text="Введите новый порт шлюза (целое число):")
    await state.set_state(AdminServers.change_gateway_port)
    await state.update_data(callback_data=callback_data)


@router.message(AdminServers.change_gateway_port)
async def get_text_change_gateway_port(message: Message, state: FSMContext):
    try:
        if not message.text.strip().isdigit():
            await message.answer("Ошибка! Введите целое число (порт), попробуйте снова.")
            return

        state_data = await state.get_data()
        callback_data = state_data["callback_data"]
        new_port = int(message.text.strip())
        await message.answer(
            text=f"Вы уверены что хотите установить порт шлюза: <code>{new_port}</code>?",
            parse_mode=ParseMode.HTML,
            reply_markup=get_confirm_buttons(EditServers, server_id=callback_data.server_id, page=callback_data.page))

        await state.set_state(AdminServers.change_gateway_port_confirm)
        await state.update_data(new_gateway_port=new_port)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(EditServers.filter(F.action == "confirm_change"), AdminServers.change_gateway_port_confirm)
async def clb_change_gateway_port_confirm(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    state_data = await state.get_data()
    await change_server_value(int(callback_data.server_id), gateway_port=state_data["new_gateway_port"])
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно! Порт шлюза: <code>{state_data['new_gateway_port']}</code>",
        parse_mode=ParseMode.HTML)
    await show_servers(callback.message)
    await state.set_state(AdminServers.edit)


"""───────────────────────────────────────────── Callbacks Delete Tariff ─────────────────────────────────────────────"""


@router.callback_query(EditServers.filter(F.action == "confirm_change"), AdminServers.delete_confirm)
async def clb_delete_server_confirm(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    await delete_server(callback_data.server_id)
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно, сервер был удален.",
        parse_mode=ParseMode.HTML)

    await show_servers(callback.message)
    await state.set_state(AdminServers.edit)


"""───────────────────────────────────────────── Callbacks Add Server ─────────────────────────────────────────────"""


@router.message(AdminServers.add_address)
async def get_text_add_address(message: Message, state: FSMContext):
    try:
        await message.answer(
            text=f"Получен адрес: <code>{message.text}</code>\n\nВведите логин для сервера  ⬇️",
            parse_mode=ParseMode.HTML)

        await state.set_state(AdminServers.add_login)
        await state.update_data(address=str(message.text))

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.message(AdminServers.add_login)
async def get_text_add_login(message: Message, state: FSMContext):
    try:
        await message.answer(
            text=f"Получен логин: <code>{message.text}</code>\n\nВведите пароль для сервера  ⬇️",
            parse_mode=ParseMode.HTML)

        await state.set_state(AdminServers.add_password)
        await state.update_data(login=message.text)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.message(AdminServers.add_password)
async def get_text_add_password(message: Message, state: FSMContext):
    try:
        await state.update_data(password=message.text)
        await message.answer(
            text=(
                f"Получен пароль: <code>{message.text}</code>\n\n"
                "Включать flow xtls-rprx-vision при создании ключей на этом сервере? "
                "(введите <code>yes</code>/<code>no</code>)"
            ),
            parse_mode=ParseMode.HTML)

        await state.set_state(AdminServers.add_flow)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.message(AdminServers.add_flow)
async def get_text_add_flow(message: Message, state: FSMContext):
    try:
        text = message.text.strip().lower()
        if text not in ("yes", "no", "да", "нет", "y", "n", "+", "-"):
            await message.answer("Ошибка! Введите yes/no (да/нет), попробуйте снова.")
            return

        flow_enabled = text in ("yes", "да", "y", "+")
        await state.update_data(flow_enabled=flow_enabled)

        await message.answer(
            text="Это сервер для обхода белых списков? (введите <code>да</code>/<code>нет</code>)",
            parse_mode=ParseMode.HTML)
        await state.set_state(AdminServers.add_is_bypass)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.message(AdminServers.add_is_bypass)
async def get_text_add_is_bypass(message: Message, state: FSMContext):
    try:
        text = message.text.strip().lower()
        if text not in ("yes", "no", "да", "нет", "y", "n", "+", "-"):
            await message.answer("Ошибка! Введите да/нет, попробуйте снова.")
            return

        is_bypass = text in ("yes", "да", "y", "+")
        await state.update_data(is_bypass=is_bypass)

        if is_bypass:
            await message.answer(
                text="Введите лимит трафика в ГБ (целое число, например <code>10</code>):",
                parse_mode=ParseMode.HTML)
            await state.set_state(AdminServers.add_traffic_limit)
        else:
            await _show_add_server_confirm(message, state)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.message(AdminServers.add_traffic_limit)
async def get_text_add_traffic_limit(message: Message, state: FSMContext):
    try:
        if not message.text.strip().isdigit():
            await message.answer("Ошибка! Введите целое число (ГБ), попробуйте снова.")
            return

        await state.update_data(traffic_limit_gb=int(message.text.strip()))
        await message.answer(
            text="Введите адрес шлюза (IP или домен сервера Б, например <code>1.2.3.4</code>):",
            parse_mode=ParseMode.HTML)
        await state.set_state(AdminServers.add_gateway_host)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.message(AdminServers.add_gateway_host)
async def get_text_add_gateway_host(message: Message, state: FSMContext):
    try:
        await state.update_data(gateway_host=message.text.strip())
        await message.answer(
            text="Введите порт шлюза (целое число, например <code>443</code>):",
            parse_mode=ParseMode.HTML)
        await state.set_state(AdminServers.add_gateway_port)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.message(AdminServers.add_gateway_port)
async def get_text_add_gateway_port(message: Message, state: FSMContext):
    try:
        if not message.text.strip().isdigit():
            await message.answer("Ошибка! Введите целое число (порт), попробуйте снова.")
            return

        await state.update_data(gateway_port=int(message.text.strip()))
        await _show_add_server_confirm(message, state)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


async def _show_add_server_confirm(message: Message, state: FSMContext):
    """Показывает итоговый экран подтверждения создания сервера."""
    state_data = await state.get_data()
    flow_enabled = state_data.get("flow_enabled", True)
    is_bypass = state_data.get("is_bypass", False)
    bypass_info = ""
    if is_bypass:
        bypass_info = (
            f"\nЛимит трафика: <b>{state_data.get('traffic_limit_gb')} ГБ</b>"
            f"\nАдрес шлюза: <b>{state_data.get('gateway_host')}</b>"
            f"\nПорт шлюза: <b>{state_data.get('gateway_port')}</b>"
        )

    await message.answer(
        text=f"""
<b>Создание нового сервера:</b>

Адрес: <b>{state_data['address']}</b>
Логин: <b>{state_data['login']}</b>
Пароль: <b>{state_data['password']}</b>
Максимум ключей: <b>20</b>
Тестовый режим: <b>Выключен</b>
flow xtls-rprx-vision: <b>{'Включен' if flow_enabled else 'Выключен'}</b>
Обход белых списков: <b>{'Да' if is_bypass else 'Нет'}</b>{bypass_info}

Создать сервер с вышеуказанными параметрами?""",
        parse_mode=ParseMode.HTML,
        reply_markup=get_confirm_buttons(AddServer, address="confirm", login=state_data['login'], password=state_data['password']))

    await state.set_state(AdminServers.add_confirm)


@router.callback_query(AddServer.filter(F.action == "confirm_change"), AdminServers.add_confirm)
async def clb_create_server_confirm(callback: CallbackQuery, callback_data: AddServer, state: FSMContext):
    data = await state.get_data()
    await add_server(
        data["address"],
        data["login"],
        data["password"],
        flow_enabled=data.get("flow_enabled", True),
        is_bypass=data.get("is_bypass", False),
        traffic_limit_gb=data.get("traffic_limit_gb"),
        gateway_host=data.get("gateway_host"),
        gateway_port=data.get("gateway_port"),
    )
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно! Сервер был создан",
        parse_mode=ParseMode.HTML)

    await show_servers(callback.message)
    await state.set_state(AdminServers.edit)
