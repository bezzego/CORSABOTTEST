from sys import prefix

from aiogram.filters.callback_data import CallbackData


class EditTariffs(CallbackData, prefix="edit_tariffs"):
    action: str
    tariff_id: None | int
    page: int


class AddTariff(CallbackData, prefix="add_tariff"):
    action: str
    name: str
    price: int
    days: int


class EditServers(CallbackData, prefix="edit_servers"):
    action: str
    server_id: None | int
    page: int


class AddServer(CallbackData, prefix="add_server"):
    action: str
    address: str
    login: str
    password: str


class EditInst(CallbackData, prefix="edit_inst"):
    action: str
    device: str


class EditUserBanned(CallbackData, prefix="edit_user_ban"):
    action: str


class EditPromo(CallbackData, prefix="edit_promo"):
    action: str
    promo_id: None | str
    page: int


class AddDaysKey(CallbackData, prefix="add_days_key"):
    action: str
    key_id: None | str
    page: int


class TransferKey(CallbackData, prefix="admin_transfer_key"):
    action: str
    key_id: None | str
    page: int


class TransferKeyServer(CallbackData, prefix="admin_transfer_key_server"):
    action: str
    server_id: None | str
    page: int


class SpamMessages(CallbackData, prefix="admin_spam_messages"):
    action: str


class AddTariffsToPromo(CallbackData, prefix="admin_edit_tariffs"):
    action: str
    tariff_id: None | str


class NotificationRuleCb(CallbackData, prefix="admin_notify_rule"):
    action: str
    rule_id: None | int


class NotificationTypeCb(CallbackData, prefix="admin_notify_type"):
    action: str
    type_name: str


class NotificationWeekdayCb(CallbackData, prefix="admin_notify_weekday"):
    action: str
    weekday: int
