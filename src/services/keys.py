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
panel_diag_logger = getLogger("panel.diagnostics")


class X3UI:
    def __init__(self, server):
        self.server = server
        self.ses = requests.Session()
        # Configure session to work with self-signed SSL certificates
        self.ses.verify = False
        # Set default timeout for requests
        self.timeout = 30
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
        parsed = urllib.parse.urlparse(host)
        
        # If no scheme provided, default to https for new X3UI panels with SSL
        if not parsed.scheme:
            host = "https://" + host
            parsed = urllib.parse.urlparse(host)
        
        if not parsed.netloc:
            logger.error(f"Invalid server host: {host}")
            return None

        path = parsed.path.rstrip("/") if parsed.path else ""
        normalized = f"{parsed.scheme}://{parsed.netloc}{path}"
        logger.debug(f"Normalized host: {host} -> {normalized}")
        return normalized

    def _build_url(self, path: str) -> str:
        if not self.host:
            raise ValueError("Server host is not configured")
        base = self.host if self.host.endswith("/") else self.host + "/"
        return urllib.parse.urljoin(base, path.lstrip("/"))

    def _request(self, method: str, path: str, **kwargs):
        url = self._build_url(path)
        # Ensure SSL verification is disabled for self-signed certificates
        kwargs.setdefault('verify', False)
        # Set timeout if not provided
        kwargs.setdefault('timeout', self.timeout)
        # Add headers if not provided
        if 'headers' not in kwargs:
            kwargs['headers'] = self.header.copy()
        
        try:
            logger.debug(f"Making {method.upper()} request to {url}")
            response = getattr(self.ses, method)(url, **kwargs)
            # Extra diagnostics for problematic panel
            if "194.147.149.107" in (self.host or ""):
                content_type = response.headers.get("Content-Type", "")
                if response.status_code != 200 or "application/json" not in content_type:
                    panel_diag_logger.warning(
                        "Panel diagnostics host=%s method=%s path=%s status=%s content-type=%s body=%s",
                        self.host,
                        method.upper(),
                        path,
                        response.status_code,
                        content_type,
                        (response.text or "")[:200],
                    )
            return response
        except InvalidURL as e:
            logger.error(f"InvalidURL for {url}: {e}", exc_info=True)
            raise
        except RequestException as e:
            logger.error(f"Request error for {method.upper()} {url}: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error for {method.upper()} {url}: {e}", exc_info=True)
            raise

    def auth(self):
        try:
            response = self._request("post", "/login", json=self.data)
            if not response:
                logger.warning("Auth: Empty response")
                return {"success": False, "error": "Empty response"}

            # Check status code
            if response.status_code != 200:
                logger.warning(f"Auth: HTTP {response.status_code} - {response.text[:200]}")
                return {"success": False, "error": f"HTTP {response.status_code}"}

            if response.text:
                try:
                    json_resp = response.json()
                    logger.debug(f"Auth response: {json_resp}")
                    return json_resp
                except ValueError as e:
                    logger.warning(f"Auth: Failed to parse JSON - {response.text[:200]}")
                    # Some panels return success even without JSON
                    if response.status_code == 200:
                        return {"success": True}
                    return {"success": False, "error": "Invalid JSON response"}
            return {"success": True}
        except Exception as e:
            logger.error(f"Auth error for host {self.host}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def users_list(self):
        self.auth()
        response = self._request("get", "/panel/api/inbounds/list")
        if not response:
            return {}
        if response.status_code != 200:
            logger.warning(
                "users_list: HTTP %s (content-type=%s, body=%s)",
                response.status_code,
                response.headers.get("Content-Type"),
                (response.text or "")[:200],
            )
            return {}
        try:
            return response.json()
        except ValueError:
            logger.warning(
                "users_list: Failed to parse JSON (status=%s, content-type=%s, body=%s)",
                response.status_code,
                response.headers.get("Content-Type"),
                (response.text or "")[:200],
            )
            return {}

    def _client_dict(self, key_name, x_time, enable, client_id=None, traffic_limit_gb=None):
        """Собирает словарь клиента для панели. flow добавляется только если у сервера flow_enabled=True."""
        d = {
            "id": client_id or str(uuid.uuid1()),
            "alterId": 90,
            "email": str(key_name),
            "limitIp": 1,
            "totalGB": traffic_limit_gb * 1024 * 1024 * 1024 if traffic_limit_gb else 0,
            "expiryTime": x_time,
            "enable": enable,
            "tgId": str(key_name),
            "subId": ""
        }
        if getattr(self.server, "flow_enabled", True):
            d["flow"] = "xtls-rprx-vision"
        return d

    def create_key(self, key_name, days, traffic_limit_gb=None):
        epoch = datetime.datetime.utcfromtimestamp(0)
        x_time = int((datetime.datetime.now() - epoch).total_seconds() * 1000)
        x_time += 86400000 * (days + 1) - 10800000

        client = self._client_dict(key_name, x_time, True, traffic_limit_gb=traffic_limit_gb)
        data = {
            "id": self.inbound_id,
            "settings": json.dumps({"clients": [client]})
        }

        self.auth()
        return self._request(
            "post",
            "/panel/api/inbounds/addClient",
            headers=self.header,
            json=data
        )

    def _get_client_settings(self, key_name: str) -> dict | None:
        """
        Возвращает dict клиента из настроек панели по его email (key_name).
        Нужен, чтобы при обновлении пользователя не затирать существующий flow.
        """
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
                    return client
        except Exception:
            logger.error("_get_client_settings failed", exc_info=True)

        return None

    def get_user_id(self, key_name):
        client = self._get_client_settings(key_name)
        if client:
            return client.get("id")
        return None

    def turn_off_user(self, key_name):
        epoch = datetime.datetime.utcfromtimestamp(0)
        x_time = int((datetime.datetime.now() - epoch).total_seconds() * 1000)

        user_id = self.get_user_id(key_name)
        if not user_id:
            logger.error("turn_off_user: user not found for key=%s", key_name)
            return None

        # При выключении пользователя не трогаем его flow:
        # берем существующие настройки клиента и только обновляем expiryTime/enable.
        existing = self._get_client_settings(key_name) or {}
        client = {
            "id": user_id,
            "alterId": existing.get("alterId", 90),
            "email": existing.get("email", str(key_name)),
            "limitIp": existing.get("limitIp", 1),
            "totalGB": existing.get("totalGB", 0),
            "expiryTime": x_time,
            "enable": False,
            "tgId": existing.get("tgId", str(key_name)),
            "subId": existing.get("subId", ""),
        }
        # Копируем flow как есть: если его не было — не добавляем.
        if "flow" in existing:
            client["flow"] = existing["flow"]

        data = {
            "id": self.inbound_id,
            "settings": json.dumps({"clients": [client]})
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

        # При продлении ключа не меняем flow у уже существующего клиента.
        existing = self._get_client_settings(key_name) or {}
        client = {
            "id": user_id,
            "alterId": existing.get("alterId", 90),
            "email": existing.get("email", str(key_name)),
            "limitIp": existing.get("limitIp", 1),
            "totalGB": existing.get("totalGB", 0),
            "expiryTime": x_time,
            "enable": True,
            "tgId": existing.get("tgId", str(key_name)),
            "subId": existing.get("subId", ""),
        }
        if "flow" in existing:
            client["flow"] = existing["flow"]

        data = {
            "id": self.inbound_id,
            "settings": json.dumps({"clients": [client]})
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

    def reset_client_traffic(self, key_name: str) -> bool:
        """Сбрасывает счётчик трафика клиента на панели. Возвращает True при успехе."""
        self.auth()
        path = f"/panel/api/inbounds/{self.inbound_id}/resetClientTraffic/{key_name}"
        try:
            response = self._request("post", path, headers=self.header)
            if response and response.status_code == 200:
                return True
            logger.warning(
                "reset_client_traffic: HTTP %s for key=%s",
                getattr(response, "status_code", None),
                key_name,
            )
            return False
        except Exception:
            logger.error("reset_client_traffic failed for key=%s", key_name, exc_info=True)
            return False

    def get_client_traffic(self, key_name: str) -> dict | None:
        """Возвращает статистику трафика клиента: {'up': bytes, 'down': bytes, 'total': bytes}.
        Возвращает None если клиент не найден или запрос не удался."""
        try:
            data = self.users_list()
            obj = data.get("obj") or []
            if not obj:
                return None
            for entry in obj[0].get("clientStats") or []:
                if str(entry.get("email")) == str(key_name):
                    return {
                        "up": entry.get("up", 0),
                        "down": entry.get("down", 0),
                        "total": entry.get("total", 0),
                    }
            return None
        except Exception:
            logger.error("get_client_traffic failed for key=%s", key_name, exc_info=True)
            return None

    def get_key(self, key_name: str):
        users = self.users_list().get("obj", [])
        if not users:
            return None

        inbound = users[0]
        settings_data = json.loads(inbound.get("settings", "{}"))
        stream = json.loads(inbound.get("streamSettings", "{}"))

        key_id = None
        flow = None
        for c in settings_data.get("clients", []):
            if str(c.get("email")) == key_name:
                key_id = c.get("id")
                flow = c.get("flow")  # Получаем flow из настроек клиента
                break

        if not key_id:
            return None

        parsed = urllib.parse.urlparse(self.host or "")
        ip = parsed.hostname or ""
        port = inbound.get("port")

        try:
            # Формируем VLESS URL в формате, совместимом с админкой и клиентами (Reality)
            # Порядок: type, encryption=none, security, pbk, fp, sni, sid, spx, flow (в конце)
            network = stream.get("network") or "tcp"
            security_val = stream.get("security") or "reality"
            url = (
                f"vless://{key_id}@{ip}:{port}/"
                f"?type={network}&encryption=none&security={security_val}"
                f"&pbk={stream['realitySettings']['settings']['publicKey']}"
                f"&fp=chrome"
                f"&sni={stream['realitySettings']['serverNames'][0]}"
                f"&sid={stream['realitySettings']['shortIds'][0]}"
                f"&spx=%2F"
            )
            # flow в конце (как в админке) — важно для совместимости клиентов
            if flow:
                url += f"&flow={flow}"
            url += f"#{settings.prefix}-{key_name}"
            return url
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
