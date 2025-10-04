from aiogram.fsm.state import State, StatesGroup


class AdminMenu(StatesGroup):
    main_menu = State()
    tariffs_menu = State()
    servers_menu = State()
    support_menu = State()
    test_sub_menu = State()
    users_menu = State()
    promo_menu = State()
    statistics_menu = State()
    inst_menu = State()
    notifications_menu = State()


class AdminTariffs(StatesGroup):
    edit = State()
    change_name = State()
    change_name_confirm = State()

    change_price = State()
    change_price_confirm = State()

    change_days = State()
    change_days_confirm = State()

    delete_confirm = State()

    add_name = State()
    add_price = State()
    add_days = State()
    add_confirm = State()


class AdminServers(StatesGroup):
    edit = State()

    change_address = State()
    change_address_confirm = State()

    change_login = State()
    change_login_confirm = State()

    change_password = State()
    change_password_confirm = State()

    change_max_users = State()
    change_max_users_confirm = State()

    change_test = State()
    change_test_confirm = State()

    delete_confirm = State()

    add_address = State()
    add_login = State()
    add_password = State()
    add_confirm = State()


class AdminInst(StatesGroup):
    device = State()

    change_video = State()

    change_link = State()


class AdminUsers(StatesGroup):
    ban_or_unban = State()
    ban_or_unban_confirm = State()

    add_days_select_user = State()
    add_days_select_key = State()
    add_days_send = State()
    add_days_confirm = State()

    transfer_key_select_user = State()
    transfer_key_select_key = State()
    transfer_key_select_server = State()

    transfer_all_keys_select_first = State()
    transfer_all_keys_select_second = State()

    spam_messages = State()
    spam_messages_user_select = State()
    spam_messages_get_message = State()
    spam_messages_confirm = State()


class AdminPromo(StatesGroup):
    edit = State()

    change_code = State()
    change_code_confirm = State()

    change_price = State()
    change_price_confirm = State()

    change_max_users = State()
    change_max_users_confirm = State()

    change_finish_date = State()
    change_finish_date_confirm = State()

    change_tariffs = State()

    add_code = State()
    add_price = State()
    add_max_users = State()
    add_finish_date = State()
    add_tariffs = State()
    add_confirm = State()

    delete_confirm = State()


class AdminNotifications(StatesGroup):
    select_action = State()
    create_type = State()
    create_name = State()
    create_offset = State()
    create_repeat = State()
    create_weekday = State()
    create_time = State()
    create_timezone = State()
    collect_template = State()
    # states for button constructor
    create_buttons = State()
    add_button_text = State()
    add_button_type = State()
    add_button_value = State()
    confirm = State()

    edit_select_rule = State()
    edit_toggle = State()
