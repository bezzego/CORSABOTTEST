import psutil


def get_key_name_without_user_id(key) -> str:
    """Возвращает название ключа без айди юзера"""
    key_name = key.name.replace(f'_{str(key.user_id)}_', '')
    return key_name[:6] + "_" + key_name[6:]


def get_days_hours_by_ts(ts: float):
    """Возвращает дни, часы, минуты"""
    days = int(ts // (24 * 3600))
    hours = int((ts % (24 * 3600)) // 3600)
    minutes = int((ts % 3600) // 60)
    return days, hours, minutes


def get_host_stats():
    """Получение состояния сервера"""
    hdd = psutil.disk_usage('/')
    return f"""
Состояние сервера:
SSD: Использовано {round(hdd.used / (2 ** 30), 2)}/{round(hdd.total / (2 ** 30), 2)} GB -- {round(hdd.used * 100 / hdd.total, 2)}%
Память: Использовано {round(psutil.virtual_memory().used / (2 ** 20), 2)}/{round(psutil.virtual_memory().total / (2 ** 20), 2)}Mb -- {round(psutil.virtual_memory().used * 100 / psutil.virtual_memory().total, 2)}%
ЦП: Нагрузка {psutil.cpu_percent()}%
"""
