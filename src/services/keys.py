import datetime
import json
import uuid
import requests
import asyncio
import urllib.parse
from requests.exceptions import InvalidURL, RequestException

from src.config import settings
from src.database.crud.keys import get_all_keys, update_key, delete_key
from src.database.crud.servers import get_server_by_id
from src.logs import getLogger
from src.utils.utils import get_key_name_without_user_id, get_days_hours_by_ts
from src.utils.utils_async import send_notification_to_user

logger = getLogger(__name__)


class X3UI:
    def __init__(self, server):
        self.server = server
        self.ses = requests.Session()
        # Normalize and validate host early to avoid creating malformed URLs later
        self.host = self._normalize_host(getattr(server, 'host', None))
        self.login = server.login
        self.password = server.password
        self.data = {"username": self.login, "password": self.password}
        self.header = {"Accept": "application/json"}
        self.inbound_id = 1

    def _normalize_host(self, host: str | None) -> str | None:
        """Try to normalize host: strip, ensure scheme, validate netloc.

        Returns normalized host (with scheme) or None if invalid.
        """
        if not host:
            logger.error(f"Server host is empty or missing: {host}")
            return None
        host = str(host).strip()
        # If scheme missing, default to http
        if not urllib.parse.urlparse(host).scheme:
            host = 'http://' + host

        parsed = urllib.parse.urlparse(host)
        # netloc must be present (domain or host:port)
        if not parsed.netloc:
            logger.error(f"Invalid server.host after parsing: {host}")
            return None
        # Rebuild normalized URL including any path prefix the admin stored
        # e.g. host may be '89.110.77.126:38373/hgv82NFGBxUETzfl1U'
        path = parsed.path.rstrip('/') if parsed.path else ''
        normalized = f"{parsed.scheme}://{parsed.netloc}{path}"
        return normalized

    def _build_url(self, path: str) -> str:
        """Build full URL for a given path using normalized host."""
        if not self.host:
            raise ValueError(f"Invalid host configured for server id={getattr(self.server,'id',None)}")
        # Ensure single slash join
        base = self.host if self.host.endswith('/') else self.host + '/'
        return urllib.parse.urljoin(base, path.lstrip('/'))

    def _request(self, method: str, path: str, **kwargs):
        url = self._build_url(path)
        try:
            resp = getattr(self.ses, method)(url, **kwargs)
            return resp
        except InvalidURL as e:
            logger.error(f"InvalidURL when requesting {url} (host={self.host}): {e}", exc_info=True)
            raise
        except RequestException as e:
            logger.error(f"RequestException when requesting {url} (host={self.host}): {e}", exc_info=True)
            raise

    def auth(self):
        """Авторизация на сервисе"""
        try:
            # use json payload (server expects 'username') and keep cookies in session
            logger.debug("Auth request to host=%s path=/login payload_keys=%s", self.host, list(self.data.keys()))
            response = self._request('post', '/login', json=self.data)
            if response is None:
                logger.error(f"No response received during auth for host={self.host}")
                return {"success": False, "error": "no_response"}

            status = response.status_code
            headers = dict(response.headers)
            cookies = response.cookies.get_dict()
            text = (response.text or "").strip()

            logger.debug("Auth response for host=%s status=%s headers=%s cookies=%s", self.host, status,
                         {k: headers.get(k) for k in ("Content-Type", "Set-Cookie")}, cookies)

            if not text:
                # empty body — but if cookie present, consider authentication successful
                if status == 200 and cookies:
                    logger.info("Auth succeeded by cookie for host=%s", self.host)
                    return {"success": True, "status_code": status, "cookies": cookies}

                logger.error(f"Empty response body during auth for host={self.host} status={status}")
                return {"success": False, "status_code": status, "text": text, "headers": headers, "cookies": cookies}

            try:
                json_resp = response.json()
                logger.debug(f"Auth status: {json_resp}")
                if isinstance(json_resp, dict):
                    return json_resp
                return {"success": False, "data": json_resp}

            except ValueError as e:
                logger.error(f"Error parsing JSON auth response for host={self.host}: {e}", exc_info=True)
                return {"success": False, "status_code": status, "text": text, "headers": headers, "cookies": cookies}

        except Exception as e:
            logger.error(f"Error auth to service servers: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def users_list(self):
        """Получение списка пользователей"""
        self.auth()
        response = self._request('get', '/panel/api/inbounds/list', json=self.data)
        return response.json() if response is not None else {}

    def create_key(self, key_name, days):
        """Создание ключа на сервере"""
        epoch = datetime.datetime.utcfromtimestamp(0)
        x_time = int((datetime.datetime.now() - epoch).total_seconds() * 1000.0)
        x_time += 86400000 * (days + 1) - 10800000
        data = {
            "id": self.inbound_id,
            "settings":
                "{\"clients\":"
                "[{\"id\":\"" + str(uuid.uuid1()) + "\","
                                                    "\"alterId\":90,\"email\":\"" + str(key_name) + "\","
                                                                                                    "\"limitIp\":1,\"totalGB\":0,"
                                                                                                    "\"expiryTime\":" + str(
                    x_time) + ",\"enable\":true,\"tgId\":\"" + str(key_name) + "\",\"subId\":\"\"}]}"
        }
        self.auth()
        response = self._request('post', '/panel/api/inbounds/addClient', headers=self.header, json=data)
        logger.debug(f"create_key response: {response}")
        return response

    def get_user_id(self, key_name):
        users = json.loads(self.users_list().get('obj', [])[0]['settings'])
        logger.debug(users)
        for i in users["clients"]:
            if str(i['email']) == key_name:
                return i['id']

    def turn_off_user(self, key_name):
        """Выключение ключа на панели"""
        epoch = datetime.datetime.utcfromtimestamp(0)
        x_time = int((datetime.datetime.now() - epoch).total_seconds() * 1000.0)
        data = {
            "id": self.inbound_id,
            "settings":
                "{\"clients\":"
                "[{\"id\":\"" + self.get_user_id(key_name) + "\","
                                                             "\"alterId\":90,\"email\":\"" + str(key_name) + "\","
                                                                                                             "\"limitIp\":1,\"totalGB\":0,"
                                                                                                             "\"expiryTime\":" + str(
                    x_time) + ",\"enable\":false,\"tgId\":\"" + str(key_name) + "\",\"subId\":\"\"}]}"
        }
        self.auth()
        path = f"/panel/api/inbounds/updateClient/{self.get_user_id(key_name)}"
        response = self._request('post', path, headers=self.header, json=data)
        return response

    def turn_on_user(self, key_name, days):
        epoch = datetime.datetime.utcfromtimestamp(0)
        x_time = int((datetime.datetime.now() - epoch).total_seconds() * 1000.0)
        x_time += 86400000 * (days + 1) - 10800000
        data = {
            "id": self.inbound_id,
            "settings":
                "{\"clients\":"
                "[{\"id\":\"" + self.get_user_id(key_name) + "\","
                                                             "\"alterId\":90,\"email\":\"" + str(key_name) + "\","
                                                                                                             "\"limitIp\":1,\"totalGB\":0,"
                                                                                                             "\"expiryTime\":" + str(
                    x_time) + ",\"enable\":true,\"tgId\":\"" + str(key_name) + "\",\"subId\":\"\"}]}"
        }
        self.auth()
        path = f"/panel/api/inbounds/updateClient/{self.get_user_id(key_name)}"
        response = self._request('post', path, headers=self.header, json=data)
        return response

    def delete_user(self, key_name):
        """Удаление пользователя из панели"""
        self.auth()
        users = json.loads(self.users_list().get('obj', [])[0]['settings'])
        for i in users["clients"]:
            if str(i['email']) == key_name:
                key_name = i['id']
        path = f'/panel/api/inbounds/{self.inbound_id}/delClient/{key_name}'
        response = self._request('post', path, headers=self.header, json=self.data)
        return response

    def get_key(self, key_name: str):
        """Получение ссылки ключа"""
        key_id = ''
        y = json.loads(self.users_list().get('obj', [])[0]['settings'])
        for i in y["clients"]:
            if str(i['email']) == key_name:
                key_id = i["id"]
        x = json.loads(self.users_list().get('obj', [])[0]['streamSettings'])
        tcp = x['network']
        reality = x['security']
        port = self.users_list().get('obj', [])[0]['port']
        # Extract host/IP for constructing the vless link
        parsed = urllib.parse.urlparse(self.host or '')
        ip = parsed.hostname or ''
        pbk = json.loads(self.users_list().get('obj', [])[0]['streamSettings'])['realitySettings']['settings']['publicKey']
        sni = json.loads(self.users_list().get('obj', [])[0]['streamSettings'])['realitySettings']['serverNames'][0]
        sid = json.loads(self.users_list().get('obj', [])[0]['streamSettings'])['realitySettings']['shortIds'][0]
        val = f"vless://{key_id}@{ip}:{port}?type={tcp}&security={reality}&fp=chrome&pbk={pbk}&sni={sni}&sid={sid}&spx=%2F#{settings.prefix}-{key_name}"
        return val

    def is_active(self, key_name: str):
        """Проверка active статуса ключа"""
        dict_x = {}
        epoch = datetime.datetime.utcfromtimestamp(0)
        x_time = int((datetime.datetime.now() - epoch).total_seconds() * 1000.0)
        y = json.loads(self.users_list().get('obj', [])[0]['settings'])
        for i in y["clients"]:
            if str(i['email']) == key_name:
                print(i)
                if i['enable'] and i['expiryTime'] > x_time:
                    dict_x['activ'] = 'Активен'
                    ts = i['expiryTime']
                    ts /= 1000
                    ts += 10800
                    dict_x['time'] = datetime.datetime.utcfromtimestamp(ts).strftime('%d-%m-%Y %H:%M') + ' МСК'
                    return dict_x
                else:
                    dict_x['activ'] = 'Не Активен'
                    ts = i['expiryTime']
                    ts /= 1000
                    ts += 10800
                    dict_x['time'] = datetime.datetime.utcfromtimestamp(ts).strftime('%d-%m-%Y %H:%M') + ' МСК'
                    return dict_x
        else:
            dict_x['activ'] = 'Не зарегистрирован'
            dict_x['time'] = '-'
        return dict_x


async def keys_control_task(bot):
    """Фоновая задача для контроля сроков действия ключей."""
    await asyncio.sleep(20)
    while True:
        now = datetime.datetime.now()
        keys = await get_all_keys()
        for key in keys:
            try:
                if key.finish >= now:
                    ts = (key.finish - datetime.datetime.now()).total_seconds()
                    days, hours, minutes = get_days_hours_by_ts(ts)
                    hours += days * 60
                    if 1 <= hours <= 24:
                        if not key.alerted:
                            text_test = f"⚠️ Тестовый ключа 🔑{get_key_name_without_user_id(key)} будет отключен через 24 часа, оформите подписку для получения нового ключа"
                            text_not_test = f"⚠️ Срок действия ключа 🔑{get_key_name_without_user_id(key)} истекает через 24 часа, продлите оплату, иначе ключ будет удален"
                            text = text_test if key.is_test else text_not_test
                            if not settings.disable_key_notifications:
                                await send_notification_to_user(bot, key.user_id, text)
                            key.alerted = True
                            await update_key(key)

                            logger.debug(f"Key get alert: {key}")

                    elif hours == 0:
                        if key.active:
                            if not settings.disable_key_notifications:
                                await send_notification_to_user(bot, key.user_id, text)
                            server = await get_server_by_id(key.server_id)
                            x3_class = X3UI(server)
                            x3_class.turn_off_user(key.name)
                            key.active = False
                            await update_key(key)

                            logger.debug(f"Ket turn_off: {key}")
                            logger.info(f"Ключ выключен из-за просроченного срока: {key}")

                else:
                    ts = (datetime.datetime.now() - key.finish).total_seconds()
                    days, hours, minutes = get_days_hours_by_ts(ts)
                    hours += days * 60
                    if hours >= 24:
                        server = await get_server_by_id(key.server_id)
                        x3_class = X3UI(server)
                        if key.active:
                            x3_class.turn_off_user(key.name)

                        x3_class.delete_user(key.name)
                        await delete_key(key)

                        logger.debug(f"Key deleted: {key}")
                        logger.info(f"Ключ удален ключ из-за просроченного срока: {key}")

            except Exception as e:
                logger.error(f"ERROR_KEY {key}\n {e}", exc_info=True)

        await asyncio.sleep(60)
