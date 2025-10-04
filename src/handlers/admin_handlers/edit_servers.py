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
        return await callback.message.answer(
            text=f"""
ID: <code>{server.id}</code>
Сервер: <code>{server.host}</code>
Логин: <code>{server.login}</code>
Пароль: <code>{server.password}</code>
Макс ключей: <code>{server.max_users}</code>
Ключей на сервере: <code>{len(keys_count)}</code>
Тестовый: <code>{server.is_test}</code>
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
    AdminServers.change_address_confirm, AdminServers.change_login_confirm, AdminServers.change_password_confirm))
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
        state_data = await state.get_data()
        print(state_data)
        await message.answer(
            text=f"""
<b>Создание нового сервера:</b>

Адрес: <b>{state_data['address']}</b>
Логин: <b>{state_data['login']}</b>
Пароль: <b>{message.text}</b>
Максимум ключей: <b>20</b>
Тестовый режим: <b>Выключен</b>

Создать сервер с вышеуказанными параметрами?""",
            parse_mode=ParseMode.HTML,
            reply_markup=get_confirm_buttons(AddServer, address="confirm", login=state_data['login'], password=message.text))

        await state.set_state(AdminServers.add_confirm)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(AddServer.filter(F.action == "confirm_change"), AdminServers.add_confirm)
async def clb_create_server_confirm(callback: CallbackQuery, callback_data: AddServer, state: FSMContext):
    data = await state.get_data()
    await add_server(data["address"], data["login"], data["password"])
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно! Сервер был создан",
        parse_mode=ParseMode.HTML)

    await show_servers(callback.message)
    await state.set_state(AdminServers.edit)
