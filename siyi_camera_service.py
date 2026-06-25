import logging
import threading
from dataclasses import dataclass
from time import sleep
from typing import Any

from siyi_sdk import SIYISDK


@dataclass
class SiyiCameraSettings:
    enabled: bool = False
    ip: str = "192.168.144.25"
    port: int = 37260
    connect_max_wait_time: float = 3.0
    connect_max_retries: int = 3


class SiyiCameraService:
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

    def connect(self) -> bool:
        if not self.settings.enabled:
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
