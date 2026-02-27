import argparse
import json
import logging
import os
import signal
import sys
import tempfile
import time
import tomllib
from datetime import datetime, timezone
from os import SEEK_END
from pathlib import Path

import fcntl
import requests
import urllib3
from bitstring import BitArray
from requests.adapters import HTTPAdapter
from requests.cookies import cookiejar_from_dict
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)


class KospelSnapshot:
    def __init__(self, settings, username, password):
        self.settings = settings
        self.username = username
        self.password = password

        output_settings = settings["output"]
        polling_settings = settings["polling"]
        api_settings = settings["api"]

        self.data_dir = Path(output_settings["data_dir"])
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.csv_prefix = output_settings["csv_prefix"]
        self.json_path = self.data_dir / output_settings["json_filename"]
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        self.delimiter = output_settings["delimiter"]
        self.use_comma_decimal = output_settings.get("use_comma_decimal", True)
        self.poll_seconds = int(polling_settings["seconds"])
        self.request_timeout = float(polling_settings["request_timeout_seconds"])
        self.verify_tls = bool(polling_settings.get("verify_tls", True))

        sessid_path = Path(api_settings["session_cookie_file"])
        if not sessid_path.is_absolute():
            sessid_path = self.data_dir / sessid_path
        self.sessid_filename = sessid_path

        self.base_url = api_settings["base_url"].rstrip("/")
        self.module_id = str(api_settings["module_id"])
        self.dev_type = str(api_settings["dev_type"])
        self.device_serial = api_settings["device_serial"]
        self.connected_device_path = api_settings["connected_device_path"]
        self.cmi_read_id = str(api_settings["cmi_read_id"])

        self.labels = [(entry["key"], entry["label"]) for entry in settings["labels"]]
        self.temperature_params = {
            entry["key"] for entry in settings["labels"] if entry.get("is_temperature", False)
        }

        self.session = requests.Session()
        self.session.verify = self.verify_tls
        if not self.verify_tls:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self.session.headers.update(
            {
                "X-Requested-With": "XMLHttpRequest",
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                ),
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
                "Connection": "keep-alive",
                "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
            }
        )

        retries = Retry(
            total=int(polling_settings.get("request_retries", 3)),
            connect=int(polling_settings.get("request_retries", 3)),
            read=int(polling_settings.get("request_retries", 3)),
            backoff_factor=float(polling_settings.get("request_backoff_factor", 1.0)),
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "POST"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        sessid = self._get_sessid()
        if sessid:
            self.session.cookies = cookiejar_from_dict({"KOSPELSESSID": sessid})

    def run_once(self):
        utc_now = datetime.now(timezone.utc)
        now = utc_now.strftime("%Y-%m-%d %H:%M:%S")
        payload = self._get_data()

        if int(payload.get("status", 0)) != 0 or not payload.get("regs"):
            log.info("Re-authenticating against Kospel API")
            self._login()
            payload = self._get_data()

        if not payload.get("regs"):
            log.warning("Missing regs in API payload: %s", payload)
            return

        new_values = self._format_values(payload)
        if not any(new_values):
            log.info("Skipping empty payload values: %s", new_values)
            return

        output_dict = self._format_output_dict(new_values, now)
        self._store_values_json(output_dict)

        csv_path = self.data_dir / f"{self.csv_prefix}-{utc_now.strftime('%Y%m')}.csv"
        prev_values = self._get_prev_values(csv_path)
        if new_values != prev_values:
            log.debug("Storing %s", new_values)
            self._store_values_csv(csv_path, now, new_values)
        else:
            log.info("Skipping unchanged values: %s", new_values)

    def _get_sessid(self):
        try:
            with open(self.sessid_filename, "r", encoding="utf-8") as file_handle:
                log.debug("Getting sessid from file")
                return file_handle.read().strip()
        except IOError:
            log.debug("Sessid file not found")
            return None

    def _set_sessid(self):
        sessid = self.session.cookies.get("KOSPELSESSID")
        if sessid:
            with open(self.sessid_filename, "w", encoding="utf-8") as file_handle:
                log.debug("Storing sessid in file")
                file_handle.write(sessid)

    def _get_prev_values(self, csv_path):
        try:
            with open(csv_path, "rb") as file_handle:
                try:
                    file_handle.seek(-128, SEEK_END)
                except OSError:
                    file_handle.seek(0)
                lines = file_handle.readlines()
                if not lines:
                    return []
                last_line = lines[-1].decode("utf-8").strip().replace(",", ".")

            values = []
            for value in last_line.split(self.delimiter)[1:]:
                try:
                    values.append(int(value))
                except ValueError:
                    values.append(float(value))
            return values
        except (IOError, ValueError):
            return []

    def _format_values(self, payload):
        values = []
        for key, _ in self.labels:
            value = payload["regs"][key]
            if key in self.temperature_params:
                values.append(self._format_float(value))
            else:
                values.append(int(value))
        return values

    @staticmethod
    def _format_float(value):
        bit_array = BitArray(uint=int(value), length=16)
        return bit_array.int / 10

    def _format_output_dict(self, values, now):
        retval = {self.labels[i][0].removeprefix("TEMP_"): value for i, value in enumerate(values)}
        retval["UPDATED"] = now
        return retval

    def _store_values_csv(self, csv_path, now, values):
        line_values = [now] + [str(value) for value in values]
        line = self.delimiter.join(line_values)
        if self.use_comma_decimal:
            line = line.replace(".", ",")

        with open(csv_path, "a", encoding="utf-8") as file_handle:
            fcntl.flock(file_handle.fileno(), fcntl.LOCK_EX)
            try:
                file_handle.write(line + "\n")
                file_handle.flush()
                os.fsync(file_handle.fileno())
            finally:
                fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)

    def _store_values_json(self, values):
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=self.json_path.parent,
                prefix=f".{self.json_path.name}.",
                suffix=".tmp",
                delete=False,
                encoding="utf-8",
            ) as file_handle:
                json.dump(values, file_handle)
                tmp_path = file_handle.name
            os.replace(tmp_path, self.json_path)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _login(self):
        self._dologin()
        self._seldev()
        self._api1()
        self._read()
        self._select_module()
        self._session_device()

    def _get_data(self):
        headers = {
            "Accept": "application/vnd.kospel.cmi-v1+json",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/ekd",
        }
        data = '["{}"]'.format('","'.join([label[0] for label in self.labels]))
        response = self.session.post(
            f"{self.base_url}/api/ekd/read/{self.module_id}",
            headers=headers,
            data=data,
            timeout=self.request_timeout,
        )
        response.raise_for_status()
        return response.json()

    def _dologin(self):
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/json; charset=UTF-8",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/",
        }
        data = json.dumps({"username": self.username, "password": self.password})
        response = self.session.post(
            f"{self.base_url}/api/dologin",
            headers=headers,
            data=data,
            timeout=self.request_timeout,
        )
        log.debug(response.text.strip())
        if response.ok:
            self._set_sessid()

    def _seldev(self):
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/json; charset=UTF-8",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/mdevs",
        }
        data = json.dumps({"dev": self.connected_device_path, "devSN": self.device_serial})
        response = self.session.post(
            f"{self.base_url}/api/seldev",
            headers=headers,
            data=data,
            timeout=self.request_timeout,
        )
        log.debug(response.text.strip())

    def _api1(self):
        headers = {
            "Accept": "application/vnd.kospel.cmi-v1+json",
            "Referer": f"{self.base_url}{self.connected_device_path}",
        }
        response = self.session.get(
            f"{self.base_url}/api",
            headers=headers,
            timeout=self.request_timeout,
        )
        log.debug(response.text.strip())

    def _read(self):
        headers = {
            "Accept": "application/vnd.kospel.cmi-v1+json",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}{self.connected_device_path}",
        }
        data = '["CMI__NAME"]'
        response = self.session.post(
            f"{self.base_url}/api/cmi/read/{self.cmi_read_id}",
            headers=headers,
            data=data,
            timeout=self.request_timeout,
        )
        log.debug(response.text.strip())

    def _select_module(self):
        headers = {
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}{self.connected_device_path}",
        }
        data = {"id": self.module_id, "devType": self.dev_type}
        response = self.session.post(
            f"{self.base_url}/api/selectModule",
            headers=headers,
            data=data,
            timeout=self.request_timeout,
        )
        log.debug(response.text.strip())

    def _session_device(self):
        headers = {
            "Accept": "application/vnd.kospel.cmi-v1+json",
            "Referer": f"{self.base_url}/ekd",
        }
        response = self.session.get(
            f"{self.base_url}/api/sessionDevice",
            headers=headers,
            timeout=self.request_timeout,
        )
        log.debug(response.text.strip())


def resolve_settings_path(cli_settings_path):
    if cli_settings_path:
        return Path(cli_settings_path)

    env_settings_path = os.getenv("KOSPEL_SETTINGS_PATH")
    if env_settings_path:
        return Path(env_settings_path)

    base_dir = Path(__file__).resolve().parent
    default_paths = [
        base_dir / "config" / "settings.toml",
        base_dir / "config" / "settings.example.toml",
    ]
    for candidate in default_paths:
        if candidate.exists():
            return candidate

    raise FileNotFoundError("No settings file found")


def load_settings(settings_path):
    with open(settings_path, "rb") as file_handle:
        settings = tomllib.load(file_handle)

    if not settings.get("labels"):
        raise ValueError("settings.toml must define at least one label")

    return settings


def resolve_credentials(username, password):
    resolved_username = username or os.getenv("KOSPEL_USERNAME")
    resolved_password = password or os.getenv("KOSPEL_PASSWORD")
    if not resolved_username or not resolved_password:
        raise ValueError("KOSPEL credentials are required via args or env vars")
    return resolved_username, resolved_password


def run_loop(service, poll_seconds):
    should_stop = False

    def stop_loop(signum, _frame):
        nonlocal should_stop
        should_stop = True
        log.info("Received signal %s, stopping", signum)

    signal.signal(signal.SIGTERM, stop_loop)
    signal.signal(signal.SIGINT, stop_loop)

    while not should_stop:
        try:
            service.run_once()
        except requests.RequestException:
            log.exception("HTTP error while syncing Kospel data")
        except Exception:
            log.exception("Unexpected error while syncing Kospel data")

        if should_stop:
            break
        time.sleep(poll_seconds)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-u", "--username")
    parser.add_argument("-p", "--password")
    parser.add_argument("--settings")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()

    logging.basicConfig(
        stream=sys.stdout,
        level={0: logging.WARNING, 1: logging.INFO, 2: logging.DEBUG}.get(args.verbose, logging.DEBUG),
        format="%(asctime)s %(levelname)s: %(message)s",
    )
    logging.getLogger("urllib3").setLevel(logging.CRITICAL)

    settings_file = resolve_settings_path(args.settings)
    settings = load_settings(settings_file)
    username, password = resolve_credentials(args.username, args.password)

    service = KospelSnapshot(settings=settings, username=username, password=password)
    if args.once:
        service.run_once()
    else:
        run_loop(service, service.poll_seconds)
