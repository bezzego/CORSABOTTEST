from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from src.database.crud.keys import get_user_keys, get_key_by_id
from src.handlers.user_handlers.func_create_menu import create_menu_tariffs
from src.keyboards.inline_user import get_inline_markup_my_keys, get_key_stats
from src.keyboards.user_callback_datas import MyKeys
from src.logs import getLogger

router = Router(name=__name__)
logger = getLogger(__name__)


"""───────────────────────────────────────────── Callbacks My Keys ─────────────────────────────────────────────"""


@router.callback_query(MyKeys.filter(F.button_type == "pagination"))
async def clb_paginate_keys(callback: CallbackQuery, callback_data: MyKeys):
    keys = await get_user_keys(callback.from_user.id)
    new_markup = await get_inline_markup_my_keys(keys, callback_data.page)

    await callback.message.edit_reply_markup(reply_markup=new_markup)
    await callback.answer()


@router.callback_query(MyKeys.filter(F.button_type == "download"))
async def clb_download_key(callback: CallbackQuery, callback_data: MyKeys):
    key = await get_key_by_id(callback_data.key_id)
    await callback.answer()
    await callback.message.answer(
        text=key.key)


@router.callback_query(MyKeys.filter(F.button_type == "title"))
async def clb_title_key(callback: CallbackQuery, callback_data: MyKeys):
    key_stats_text = await get_key_stats(callback_data.key_id)
    await callback.answer()
    await callback.message.answer(
        text=key_stats_text)


@router.callback_query(MyKeys.filter(F.button_type == "prolong"))
async def clb_prolong_key(callback: CallbackQuery, callback_data: MyKeys, state: FSMContext):
    logger.debug(f"clb_prolong_key: data: {callback_data}")
    await callback.answer()
    await state.clear()
    await create_menu_tariffs(callback.message, callback_data.key_id)
