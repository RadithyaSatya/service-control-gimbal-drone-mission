import json
import logging
import math
import os
import shutil
import socket
import subprocess
import threading
from contextlib import closing
from enum import Enum
from dataclasses import dataclass
from time import sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from siyi_sdk import SIYISDK


@dataclass
class SiyiCameraSettings:
    enabled: bool = False
    ip: str = "192.168.144.25"
    port: int = 37260
    connect_max_wait_time: float = 3.0
    connect_max_retries: int = 3
    reconnect_delay_seconds: float = 5.0
    ping_enabled: bool = True
    ping_timeout_seconds: float = 1.0
    tcp_probe_enabled: bool = True
    tcp_probe_port: int = 82
    tcp_probe_timeout_seconds: float = 1.0


class SiyiCameraService:
    class MediaType(Enum):
        IMAGE = 0
        VIDEO = 1

    RECORDING_LABELS = {
        -1: "unknown",
        0: "off",
        1: "on",
        2: "tf_empty",
        3: "tf_data_loss",
    }

    def __init__(self, settings: SiyiCameraSettings):
        self.settings = settings
        self.logger = logging.getLogger("siyi-camera-service")
        self._lock = threading.RLock()
        self._sdk: SIYISDK | None = None
        self._connected = False
        self._last_healthcheck_log: str | None = None

    def _ping_host(self) -> bool:
        ping_path = shutil.which("ping")
        if ping_path is None:
            self.logger.warning("ping binary not found, skipping ICMP reachability check")
            return True

        timeout_seconds = max(1, int(math.ceil(self.settings.ping_timeout_seconds)))
        command = [ping_path, "-c", "1", "-W", str(timeout_seconds), self.settings.ip]
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return result.returncode == 0

    def _probe_tcp_port(self) -> bool:
        try:
            with socket.create_connection(
                (self.settings.ip, self.settings.tcp_probe_port),
                timeout=self.settings.tcp_probe_timeout_seconds,
            ):
                return True
        except OSError:
            return False

    def healthcheck(self) -> bool:
        if not self.settings.enabled:
            return False

        if self.settings.ping_enabled and not self._ping_host():
            message = f"camera host {self.settings.ip} is not reachable via ping"
            if self._last_healthcheck_log != message:
                self.logger.warning("%s", message)
                self._last_healthcheck_log = message
            return False

        if self.settings.tcp_probe_enabled and not self._probe_tcp_port():
            message = f"camera host {self.settings.ip} TCP port {self.settings.tcp_probe_port} is not reachable"
            if self._last_healthcheck_log != message:
                self.logger.warning("%s", message)
                self._last_healthcheck_log = message
            return False

        if self._last_healthcheck_log is not None:
            self.logger.info(
                "camera healthcheck recovered for %s:%s",
                self.settings.ip,
                self.settings.port,
            )
            self._last_healthcheck_log = None
        return True

    def connect(self) -> bool:
        if not self.settings.enabled:
            return False

        if not self.healthcheck():
            return False

        with self._lock:
            if self._connected and self._sdk is not None and self._sdk.isConnected():
                return True

            stale_sdk = self._sdk
            self._sdk = None
            self._connected = False

        if stale_sdk is not None:
            try:
                stale_sdk.disconnect()
            except Exception as exc:
                self.logger.warning("error while cleaning up stale SIYI connection: %s", exc)

        with self._lock:
            sdk = SIYISDK(server_ip=self.settings.ip, port=self.settings.port, debug=False)
            connected = sdk.connect(
                maxWaitTime=self.settings.connect_max_wait_time,
                maxRetries=self.settings.connect_max_retries,
            )
            if not connected:
                try:
                    sdk.disconnect()
                except Exception:
                    pass
                self.logger.warning("failed to connect to SIYI camera at %s:%s", self.settings.ip, self.settings.port)
                return False

            self._sdk = sdk
            self._connected = True
            self.logger.info("connected to SIYI camera at %s:%s", self.settings.ip, self.settings.port)
            return True

    def reconnect(self) -> bool:
        self.disconnect()
        return self.connect()

    def disconnect(self) -> None:
        with self._lock:
            sdk = self._sdk
            self._sdk = None
            self._connected = False

        if sdk is not None:
            try:
                sdk.disconnect()
            except Exception as exc:
                self.logger.warning("error while disconnecting SIYI camera: %s", exc)

    def is_connected(self) -> bool:
        with self._lock:
            return self._connected and self._sdk is not None and self._sdk.isConnected()

    def _require_sdk(self) -> SIYISDK:
        if not self.connect():
            raise RuntimeError("SIYI camera is not connected")
        assert self._sdk is not None
        return self._sdk

    def _refresh_state_locked(self, sdk: SIYISDK) -> None:
        sdk.requestGimbalInfo()
        sleep(0.15)
        sdk.requestCurrentZoomLevel()
        sleep(0.15)

    def _media_api_url(self, path: str, params: dict[str, Any]) -> str:
        return f"http://{self.settings.ip}:82{path}?{urlencode(params)}"

    def _get_json(self, path: str, params: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        url = self._media_api_url(path, params)
        with urlopen(url, timeout=timeout_seconds) as response:
            payload = response.read().decode("utf-8")

        return json.loads(payload)

    def _iter_media_directories(self, media_type: int, timeout_seconds: float) -> list[str]:
        payload = self._get_json(
            "/cgi-bin/media.cgi/api/v1/getdirectories",
            {"media_type": media_type},
            timeout_seconds,
        )
        if not payload.get("success"):
            raise RuntimeError(f"failed to get directories for media_type={media_type}")
        return [
            item["path"]
            for item in payload.get("data", {}).get("directories", [])
            if isinstance(item, dict) and isinstance(item.get("path"), str) and item["path"]
        ]

    def _iter_media_files(self, media_type: int, directory: str, timeout_seconds: float) -> list[dict[str, Any]]:
        payload = self._get_json(
            "/cgi-bin/media.cgi/api/v1/getmedialist",
            {
                "media_type": str(media_type),
                "path": directory,
                "start": 0,
                "count": 999,
            },
            timeout_seconds,
        )
        if not payload.get("success"):
            raise RuntimeError(f"failed to get media list for path={directory!r}")
        return [
            item
            for item in payload.get("data", {}).get("list", [])
            if isinstance(item, dict)
        ]

    @staticmethod
    def _safe_file_name(file_name: str) -> str:
        return os.path.basename(file_name.replace("\\", "/"))

    def _download_file(self, file_url: str, output_path: str, timeout_seconds: float) -> None:
        with closing(urlopen(file_url, timeout=timeout_seconds)) as response, open(output_path, "wb") as output_file:
            shutil.copyfileobj(response, output_file)

    def download_media(self, dest_dir: str, timeout_seconds: float) -> dict[str, Any]:
        os.makedirs(dest_dir, exist_ok=True)
        summary = {
            "download_root": os.path.abspath(dest_dir),
            "downloaded_file_count": 0,
            "failed_file_count": 0,
            "downloaded_files": [],
            "errors": [],
        }

        for media_type in self.MediaType:
            media_label = media_type.name.lower()
            media_dest_dir = os.path.join(dest_dir, media_label)
            os.makedirs(media_dest_dir, exist_ok=True)
            directories = self._iter_media_directories(media_type.value, timeout_seconds)

            for directory in directories:
                files = self._iter_media_files(media_type.value, directory, timeout_seconds)
                for file_info in files:
                    name = file_info.get("name")
                    url = file_info.get("url")
                    if not isinstance(name, str) or not isinstance(url, str):
                        continue

                    safe_name = self._safe_file_name(name)
                    if not safe_name:
                        continue

                    file_url = url.replace("192.168.2.119", self.settings.ip).replace(
                        "192.168.144.25", self.settings.ip
                    )
                    directory_slug = directory.replace("/", "_").replace("\\", "_")
                    if directory_slug:
                        output_name = f"{directory_slug}__{safe_name}"
                    else:
                        output_name = safe_name
                    output_path = os.path.join(media_dest_dir, output_name)

                    try:
                        self._download_file(file_url, output_path, timeout_seconds)
                        summary["downloaded_file_count"] += 1
                        summary["downloaded_files"].append(output_path)
                    except (URLError, HTTPError, OSError) as exc:
                        summary["failed_file_count"] += 1
                        summary["errors"].append(f"{safe_name}: {exc}")

        summary["download_ok"] = summary["failed_file_count"] == 0
        return summary

    def format_sd_card(self, wait_seconds: float = 2.0) -> dict[str, Any]:
        with self._lock:
            sdk = self._require_sdk()
            command_ok = sdk.requestFormatSdCard()
        if not command_ok:
            raise RuntimeError("camera format command failed to send")

        sleep(max(0.0, wait_seconds))
        feedback = None
        try:
            feedback = bool(sdk.getFormatSdCardFeedback())
        except Exception:
            feedback = None

        return {
            "format_command_sent": True,
            "format_feedback_ok": feedback,
            "format_ok": True if feedback is None else feedback,
        }

    def snapshot_state(self, refresh: bool = True) -> dict[str, Any]:
        with self._lock:
            sdk = self._sdk
            connected = self._connected and sdk is not None and sdk.isConnected()
            if not connected:
                self._connected = False

        if not connected:
            if refresh and self.reconnect():
                with self._lock:
                    sdk = self._sdk
                    connected = self._connected and sdk is not None and sdk.isConnected()
            if not connected:
                return {"connected": False}

        with self._lock:
            assert sdk is not None
            if refresh:
                try:
                    self._refresh_state_locked(sdk)
                except Exception as exc:
                    self.logger.warning("failed to refresh SIYI camera state: %s", exc)

            recording_state = sdk.getRecordingState()
            payload = {
                "connected": True,
                "recording_state": recording_state,
                "recording_label": self.RECORDING_LABELS.get(recording_state, "unknown"),
                "zoom_level": sdk.getCurrentZoomLevel(),
                "camera_type": sdk.getCameraTypeString(),
            }
            return payload

    def execute_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        command = str(payload.get("command", "")).lower()
        if not command:
            raise ValueError("camera command is required")

        with self._lock:
            sdk = self._require_sdk()

            if command == "take_photo":
                ok = sdk.requestPhoto()
            elif command == "toggle_recording":
                ok = sdk.requestRecording()
            elif command == "set_recording":
                desired = payload.get("enabled")
                if not isinstance(desired, bool):
                    raise ValueError("set_recording requires boolean enabled")
                self._refresh_state_locked(sdk)
                current = sdk.getRecordingState()
                should_toggle = (
                    (desired and current != sdk._record_msg.ON)
                    or (not desired and current == sdk._record_msg.ON)
                )
                ok = True if not should_toggle else sdk.requestRecording()
                sleep(0.2)
            elif command == "zoom_in":
                ok = sdk.requestZoomIn()
            elif command == "zoom_out":
                ok = sdk.requestZoomOut()
            elif command == "zoom_stop":
                ok = sdk.requestZoomHold()
            elif command == "set_zoom_level":
                try:
                    zoom_level = float(payload["zoom_level"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError("set_zoom_level requires numeric zoom_level") from exc
                ok = sdk.requestAbsoluteZoom(zoom_level)
                sleep(0.2)
            else:
                raise ValueError(f"unsupported camera command={command}")

            if not ok:
                raise RuntimeError(f"camera command failed: {command}")

        return self.snapshot_state(refresh=True)
