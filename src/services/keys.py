import datetime
import json
import uuid
import requests
import asyncio
import urllib.parse
import urllib3
from requests.exceptions import InvalidURL, RequestException

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from src.config import settings
from src.database.crud.keys import get_all_keys, update_key, delete_key
from src.database.crud.servers import get_server_by_id
from src.logs import getLogger
from src.utils.utils import get_key_name_without_user_id, get_days_hours_by_ts

logger = getLogger(__name__)


class X3UI:
    def __init__(self, server):
        self.server = server
        self.ses = requests.Session()
        self.host = self._normalize_host(getattr(server, "host", None))
        self.login = server.login
        self.password = server.password
        self.data = {"username": self.login, "password": self.password}
        self.header = {"Accept": "application/json"}
        self.inbound_id = 1

    def _normalize_host(self, host: str | None) -> str | None:
        if not host:
            logger.error("Server host is empty")
            return None

        host = str(host).strip()
        if not urllib.parse.urlparse(host).scheme:
            host = "http://" + host

        parsed = urllib.parse.urlparse(host)
        if not parsed.netloc:
            logger.error(f"Invalid server host: {host}")
            return None

        path = parsed.path.rstrip("/") if parsed.path else ""
        return f"{parsed.scheme}://{parsed.netloc}{path}"

    def _build_url(self, path: str) -> str:
        if not self.host:
            raise ValueError("Server host is not configured")
        base = self.host if self.host.endswith("/") else self.host + "/"
        return urllib.parse.urljoin(base, path.lstrip("/"))

    def _request(self, method: str, path: str, **kwargs):
        url = self._build_url(path)
        # Disable SSL verification for self-signed certificates
        # WARNING: This is a security risk in production. Use only for internal servers.
        kwargs.setdefault('verify', False)
        try:
            return getattr(self.ses, method)(url, **kwargs)
        except InvalidURL:
            logger.error(f"InvalidURL {url}", exc_info=True)
            raise
        except RequestException:
            logger.error(f"Request error {url}", exc_info=True)
            raise

    def auth(self):
        try:
            response = self._request("post", "/login", json=self.data)
            if not response:
                return {"success": False}

            if response.text:
                try:
                    return response.json()
                except ValueError:
                    return {"success": False}
            return {"success": True}
        except Exception as e:
            logger.error("Auth error", exc_info=True)
            return {"success": False, "error": str(e)}

    def users_list(self):
        self.auth()
        response = self._request("get", "/panel/api/inbounds/list")
        return response.json() if response else {}

    def create_key(self, key_name, days):
        epoch = datetime.datetime.utcfromtimestamp(0)
        x_time = int((datetime.datetime.now() - epoch).total_seconds() * 1000)
        x_time += 86400000 * (days + 1) - 10800000

        data = {
            "id": self.inbound_id,
            "settings":
                "{\"clients\":"
                "[{\"id\":\"" + str(uuid.uuid1()) + "\","
                                                    "\"alterId\":90,\"email\":\"" + str(key_name) + "\","
                                                                                                    "\"flow\":\"xtls-rprx-vision\",\"limitIp\":1,\"totalGB\":0,"
                                                                                                    "\"expiryTime\":" + str(
                    x_time) + ",\"enable\":true,\"tgId\":\"" + str(key_name) + "\",\"subId\":\"\"}]}"
        }

        self.auth()
        return self._request(
            "post",
            "/panel/api/inbounds/addClient",
            headers=self.header,
            json=data
        )

    def get_user_id(self, key_name):
        data = self.users_list()

        obj = data.get("obj") or []
        if not obj:
            return None

        settings_raw = obj[0].get("settings")
        if not settings_raw:
            return None

        try:
            users = json.loads(settings_raw)
            for client in users.get("clients", []):
                if str(client.get("email")) == str(key_name):
                    return client.get("id")
        except Exception:
            logger.error("get_user_id failed", exc_info=True)

        return None

    def turn_off_user(self, key_name):
        epoch = datetime.datetime.utcfromtimestamp(0)
        x_time = int((datetime.datetime.now() - epoch).total_seconds() * 1000)

        user_id = self.get_user_id(key_name)
        if not user_id:
            logger.error("turn_off_user: user not found for key=%s", key_name)
            return None

        data = {
            "id": self.inbound_id,
            "settings": json.dumps({
                "clients": [{
                    "id": user_id,
                    "alterId": 90,
                    "email": str(key_name),
                    "flow": "xtls-rprx-vision",
                    "limitIp": 1,
                    "totalGB": 0,
                    "expiryTime": x_time,
                    "enable": False,
                    "tgId": str(key_name),
                    "subId": ""
                }]
            })
        }

        self.auth()
        path = f"/panel/api/inbounds/updateClient/{user_id}"
        return self._request("post", path, headers=self.header, json=data)

    def turn_on_user(self, key_name, days):
        epoch = datetime.datetime.utcfromtimestamp(0)
        x_time = int((datetime.datetime.now() - epoch).total_seconds() * 1000)
        x_time += 86400000 * (days + 1) - 10800000

        user_id = self.get_user_id(key_name)
        if not user_id:
            logger.error("turn_on_user: user not found for key=%s", key_name)
            return None

        data = {
            "id": self.inbound_id,
            "settings": json.dumps({
                "clients": [{
                    "id": user_id,
                    "alterId": 90,
                    "email": str(key_name),
                    "flow": "xtls-rprx-vision",
                    "limitIp": 1,
                    "totalGB": 0,
                    "expiryTime": x_time,
                    "enable": True,
                    "tgId": str(key_name),
                    "subId": ""
                }]
            })
        }

        self.auth()
        path = f"/panel/api/inbounds/updateClient/{user_id}"
        return self._request("post", path, headers=self.header, json=data)

    def delete_user(self, key_name):
        self.auth()
        user_id = self.get_user_id(key_name)
        if not user_id:
            return None
        path = f"/panel/api/inbounds/{self.inbound_id}/delClient/{user_id}"
        return self._request("post", path, headers=self.header, json=self.data)

    def get_key(self, key_name: str):
        users = self.users_list().get("obj", [])
        if not users:
            return None

        inbound = users[0]
        settings_data = json.loads(inbound.get("settings", "{}"))
        stream = json.loads(inbound.get("streamSettings", "{}"))

        key_id = None
        for c in settings_data.get("clients", []):
            if str(c.get("email")) == key_name:
                key_id = c.get("id")
                break

        if not key_id:
            return None

        parsed = urllib.parse.urlparse(self.host or "")
        ip = parsed.hostname or ""
        port = inbound.get("port")

        try:
            return (
                f"vless://{key_id}@{ip}:{port}"
                f"?type={stream.get('network')}&security={stream.get('security')}"
                f"&fp=chrome"
                f"&pbk={stream['realitySettings']['settings']['publicKey']}"
                f"&sni={stream['realitySettings']['serverNames'][0]}"
                f"&sid={stream['realitySettings']['shortIds'][0]}"
                f"&spx=%2F#{settings.prefix}-{key_name}"
            )
        except Exception:
            logger.error("get_key failed", exc_info=True)
            return None


async def keys_control_task(bot):
    await asyncio.sleep(20)

    while True:
        # Используем московское время и избавляемся от naive/aware конфликтов
        msk = datetime.timezone(datetime.timedelta(hours=3))
        now = datetime.datetime.now(msk)
        keys = await get_all_keys()

        for key in keys:
            try:
                finish = key.finish.astimezone(msk) if key.finish.tzinfo else key.finish.replace(tzinfo=msk)

                if finish >= now:
                    ts = (finish - now).total_seconds()
                    days, hours, minutes = get_days_hours_by_ts(ts)
                    hours += days * 60

                    if 1 <= hours <= 24 and not key.alerted:
                        key.alerted = True
                        await update_key(key)

                    elif hours == 0 and key.active:
                        server = await get_server_by_id(key.server_id)
                        x3 = X3UI(server)
                        x3.turn_off_user(key.name)
                        key.active = False
                        await update_key(key)

                else:
                    ts = (now - finish).total_seconds()
                    days, hours, minutes = get_days_hours_by_ts(ts)
                    hours += days * 60

                    if hours >= 24:
                        server = await get_server_by_id(key.server_id)
                        x3 = X3UI(server)
                        if key.active:
                            x3.turn_off_user(key.name)
                        x3.delete_user(key.name)
                        await delete_key(key)

            except Exception as e:
                logger.error(f"ERROR_KEY {key}\n{e}", exc_info=True)

        await asyncio.sleep(60)