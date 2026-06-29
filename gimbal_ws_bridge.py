import asyncio
import json
import logging
import math
import os
import signal
import shutil
import threading
import time
from urllib.parse import urlsplit, urlunsplit
from dataclasses import dataclass
from typing import Any

import requests
import websockets
from dotenv import load_dotenv
from pymavlink import mavutil
from siyi_camera_service import SiyiCameraService, SiyiCameraSettings

load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
LOCAL_MEDIA_ROOT = os.path.join(PROJECT_ROOT, "downloads")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("gimbal-ws-bridge")


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return float(value)


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def infer_media_type(file_path: str) -> str | None:
    extension = os.path.splitext(file_path)[1].lower()
    if extension in {".jpg", ".jpeg", ".png", ".webp"}:
        return "image"
    if extension in {".mp4", ".m4", ".m4v"}:
        return "video"
    return None


def is_nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)


def compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value is not None and not is_nan(value)
    }


def quaternion_to_euler_degrees(q: list[float]) -> tuple[float, float, float]:
    w, x, y, z = q

    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    sinp = 2.0 * (w * y - z * x)
    if abs(sinp) >= 1.0:
        pitch = math.copysign(math.pi / 2.0, sinp)
    else:
        pitch = math.asin(sinp)

    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)

    return (
        math.degrees(roll),
        math.degrees(pitch),
        math.degrees(yaw),
    )


@dataclass
class Settings:
    MEDIA_DELIVERY_MODES = {"local_only", "upload", "register_move"}

    api_base_url: str = os.getenv("API_BASE_URL", "http://68.183.224.114:8081")
    ws_url: str = os.getenv("WS_URL", "")
    device_token: str = os.getenv("DEVICE_TOKEN", "uav-local-dev-token")
    uav_id: int = env_int("UAV_ID", 1)
    mavlink_endpoint: str = os.getenv("MAVLINK_ENDPOINT", "udp:127.0.0.1:14558")
    mavlink_source_system: int = env_int("MAVLINK_SOURCE_SYSTEM", 250)
    mavlink_source_component: int = env_int("MAVLINK_SOURCE_COMPONENT", 191)
    gimbal_target_system: int = env_int("MAVLINK_GIMBAL_SYSTEM", 1)
    gimbal_target_component: int = env_int("MAVLINK_GIMBAL_COMPONENT", 1)
    gimbal_device_id: int = env_int("MAVLINK_GIMBAL_DEVICE_ID", 0)
    metric_command: str = os.getenv("GIMBAL_COMMAND_METRIC", "gimbal_command")
    metric_state: str = os.getenv("GIMBAL_STATE_METRIC", "gimbal_state")
    state_interval_seconds: float = env_float("GIMBAL_STATE_INTERVAL_SECONDS", 0.2)
    connected_timeout_seconds: float = env_float("GIMBAL_CONNECTED_TIMEOUT_SECONDS", 2.0)
    siyi_enabled: bool = os.getenv("SIYI_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
    siyi_ip: str = os.getenv("SIYI_IP", "192.168.144.25")
    siyi_port: int = env_int("SIYI_PORT", 37260)
    siyi_connect_max_wait_time: float = env_float("SIYI_CONNECT_MAX_WAIT_TIME", 3.0)
    siyi_connect_max_retries: int = env_int("SIYI_CONNECT_MAX_RETRIES", 3)
    siyi_reconnect_delay_seconds: float = env_float("SIYI_RECONNECT_DELAY_SECONDS", 5.0)
    siyi_ping_enabled: bool = env_bool("SIYI_PING_ENABLED", True)
    siyi_ping_timeout_seconds: float = env_float("SIYI_PING_TIMEOUT_SECONDS", 1.0)
    siyi_tcp_probe_enabled: bool = env_bool("SIYI_TCP_PROBE_ENABLED", False)
    siyi_tcp_probe_port: int = env_int("SIYI_TCP_PROBE_PORT", 82)
    siyi_tcp_probe_timeout_seconds: float = env_float("SIYI_TCP_PROBE_TIMEOUT_SECONDS", 1.0)
    camera_command_metric: str = os.getenv("CAMERA_COMMAND_METRIC", "camera_command")
    camera_state_metric: str = os.getenv("CAMERA_STATE_METRIC", "camera_state")
    camera_state_interval_seconds: float = env_float("CAMERA_STATE_INTERVAL_SECONDS", 1.0)
    backend_connect_retry_seconds: float = env_float("BACKEND_CONNECT_RETRY_SECONDS", 5.0)
    mission_event_camera_actions_enabled: bool = env_bool("MISSION_EVENT_CAMERA_ACTIONS_ENABLED", True)
    mission_event_metric: str = os.getenv("MISSION_EVENT_METRIC", "mission_event")
    mission_post_landing_media_enabled: bool = env_bool("MISSION_POST_LANDING_MEDIA_ENABLED", False)
    mission_post_landing_media_download_enabled: bool = env_bool("MISSION_POST_LANDING_MEDIA_DOWNLOAD_ENABLED", True)
    mission_post_landing_media_format_enabled: bool = env_bool("MISSION_POST_LANDING_MEDIA_FORMAT_ENABLED", True)
    mission_post_landing_media_timeout_sec: float = env_float("MISSION_POST_LANDING_MEDIA_TIMEOUT_SEC", 120.0)
    mission_camera_media_delivery_mode: str = os.getenv("MISSION_CAMERA_MEDIA_DELIVERY_MODE", "local_only").strip().lower()
    mission_camera_media_register_root: str = os.getenv("MISSION_CAMERA_MEDIA_REGISTER_ROOT", "").strip()

    @property
    def resolved_ws_url(self) -> str:
        if self.ws_url:
            parsed = urlsplit(self.ws_url)
            path = parsed.path.rstrip("/")
            if path == "":
                path = "/ws/telemetry"
            return urlunsplit(parsed._replace(path=path))

        base = self.api_base_url.rstrip("/")
        ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
        return f"{ws_base}/ws/telemetry"


class BackendRealtimeClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.websocket = None
        self._connect_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._subscribed_metrics: list[str] = []

    def _fetch_ws_token(self) -> str:
        response = requests.post(
            f"{self.settings.api_base_url.rstrip('/')}/auth/ws-token",
            headers={"X-Device-Token": self.settings.device_token},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        for key in ("token", "ws_token", "access_token"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value

        nested = data.get("data")
        if isinstance(nested, dict):
            for key in ("token", "ws_token", "access_token"):
                value = nested.get(key)
                if isinstance(value, str) and value:
                    return value

        raise RuntimeError("response /auth/ws-token tidak mengandung token yang dikenali")

    async def connect(self) -> None:
        async with self._connect_lock:
            while True:
                try:
                    token = await asyncio.to_thread(self._fetch_ws_token)
                    ws_url = f"{self.settings.resolved_ws_url}?token={token}"
                    previous = self.websocket
                    self.websocket = await websockets.connect(
                        ws_url,
                        max_size=64 * 1024,
                        ping_interval=20,
                        ping_timeout=20,
                    )
                    if previous is not None and previous is not self.websocket:
                        try:
                            await previous.close()
                        except Exception:
                            pass
                    logger.info("connected to backend websocket: %s", ws_url)
                    return
                except Exception as exc:
                    logger.warning(
                        "backend connect failed: %s; retrying in %.1fs",
                        exc,
                        self.settings.backend_connect_retry_seconds,
                    )
                    await asyncio.sleep(self.settings.backend_connect_retry_seconds)

    async def reconnect(self, reason: str) -> None:
        if self.websocket is not None:
            try:
                await self.websocket.close()
            except Exception:
                pass
        logger.warning("backend websocket disconnected (%s), reconnecting", reason)
        await self.connect()
        if self._subscribed_metrics:
            await self.websocket.send(
                json.dumps(
                    {
                        "type": "subscribe",
                        "uav_ids": [self.settings.uav_id],
                        "metrics": self._subscribed_metrics,
                    }
                )
            )
            logger.info(
                "re-subscribed to metrics=%s for uav_id=%s",
                self._subscribed_metrics,
                self.settings.uav_id,
            )

    async def _send_json(self, message: dict[str, Any]) -> None:
        async with self._send_lock:
            try:
                await self.websocket.send(json.dumps(message))
            except websockets.ConnectionClosed as exc:
                await self.reconnect(str(exc))
                await self.websocket.send(json.dumps(message))

    async def subscribe(self, metrics: list[str]) -> None:
        self._subscribed_metrics = list(metrics)
        message = {
            "type": "subscribe",
            "uav_ids": [self.settings.uav_id],
            "metrics": metrics,
        }
        await self._send_json(message)
        logger.info("subscribed to metrics=%s for uav_id=%s", metrics, self.settings.uav_id)

    async def publish(self, metric: str, payload: dict[str, Any]) -> None:
        message = {
            "type": "publish",
            "uav_id": self.settings.uav_id,
            "kind": "telemetry",
            "metric": metric,
            "payload": compact_payload(payload),
        }
        await self._send_json(message)


class GimbalBridge:
    GIMBAL_MANAGER_FLAGS_YAW_LOCK = 16
    GIMBAL_MANAGER_FLAGS_YAW_IN_VEHICLE_FRAME = 32
    GIMBAL_MANAGER_FLAGS_YAW_IN_EARTH_FRAME = 64

    def __init__(self, settings: Settings):
        if settings.mission_camera_media_delivery_mode not in Settings.MEDIA_DELIVERY_MODES:
            raise ValueError(
                f"unsupported MISSION_CAMERA_MEDIA_DELIVERY_MODE={settings.mission_camera_media_delivery_mode!r}"
            )
        self.settings = settings
        self.backend = BackendRealtimeClient(settings)
        self.stop_event = asyncio.Event()
        self.mav = mavutil.mavlink_connection(
            settings.mavlink_endpoint,
            source_system=settings.mavlink_source_system,
            source_component=settings.mavlink_source_component,
        )
        self.mav_lock = threading.Lock()
        self.last_state_sent_at = 0.0
        self.last_status_at = 0.0
        self.connected = False
        self.last_published_at: dict[str, float] = {}
        self.last_published_payloads: dict[str, dict[str, Any]] = {}
        self.last_waypoint_reached_action_key: tuple[int | None, int | None, int | None, int | None, str] | None = None
        self.active_recording_waypoint_key: tuple[int | None, int | None, int | None, int | None, str] | None = None
        self.recording_stop_task: asyncio.Task | None = None
        self.active_media_processing_history_id: int | None = None
        self.last_completed_media_processing_history_id: int | None = None
        self.camera = None
        if settings.siyi_enabled:
            self.camera = SiyiCameraService(
                SiyiCameraSettings(
                    enabled=True,
                    ip=settings.siyi_ip,
                    port=settings.siyi_port,
                    connect_max_wait_time=settings.siyi_connect_max_wait_time,
                    connect_max_retries=settings.siyi_connect_max_retries,
                    reconnect_delay_seconds=settings.siyi_reconnect_delay_seconds,
                    ping_enabled=settings.siyi_ping_enabled,
                    ping_timeout_seconds=settings.siyi_ping_timeout_seconds,
                    tcp_probe_enabled=settings.siyi_tcp_probe_enabled,
                    tcp_probe_port=settings.siyi_tcp_probe_port,
                    tcp_probe_timeout_seconds=settings.siyi_tcp_probe_timeout_seconds,
                )
            )

    def _backend_headers(self) -> dict[str, str]:
        return {"X-Device-Token": self.settings.device_token}

    def _upload_downloaded_media(self, history_id: int, downloaded_files: list[str], timeout_seconds: float) -> dict[str, Any]:
        uploaded_count = 0
        failed_count = 0
        errors: list[str] = []

        for file_path in downloaded_files:
            media_type = infer_media_type(file_path)
            if media_type is None:
                failed_count += 1
                errors.append(f"{os.path.basename(file_path)}: unsupported media extension")
                continue

            with open(file_path, "rb") as file_handle:
                response = requests.post(
                    f"{self.settings.api_base_url.rstrip('/')}/mission-history/{history_id}/media/upload",
                    headers=self._backend_headers(),
                    data={"uav_id": str(self.settings.uav_id), "media_type": media_type},
                    files={"file": (os.path.basename(file_path), file_handle)},
                    timeout=timeout_seconds,
                )

            if not response.ok:
                failed_count += 1
                errors.append(f"{os.path.basename(file_path)}: upload failed with status {response.status_code}")
                continue

            uploaded_count += 1

        return {
            "delivery_ok": failed_count == 0,
            "delivered_file_count": uploaded_count,
            "delivery_failed_file_count": failed_count,
            "delivery_errors": errors,
        }

    def _register_move_downloaded_media(self, history_id: int, downloaded_files: list[str], timeout_seconds: float) -> dict[str, Any]:
        register_root = self.settings.mission_camera_media_register_root
        if not register_root:
            raise RuntimeError("MISSION_CAMERA_MEDIA_REGISTER_ROOT is required for register_move mode")

        register_root_abs = os.path.abspath(register_root)
        history_media_root = os.path.join(register_root_abs, f"history-{history_id}", "media")
        os.makedirs(history_media_root, exist_ok=True)

        items: list[dict[str, str]] = []
        moved_count = 0
        errors: list[str] = []

        for file_path in downloaded_files:
            media_type = infer_media_type(file_path)
            if media_type is None:
                errors.append(f"{os.path.basename(file_path)}: unsupported media extension")
                continue

            target_path = os.path.join(history_media_root, os.path.basename(file_path))
            if os.path.abspath(file_path) != os.path.abspath(target_path):
                shutil.move(file_path, target_path)
            storage_rel_path = os.path.relpath(target_path, register_root_abs)
            items.append(
                {
                    "media_type": media_type,
                    "media_role": "attachment",
                    "storage_rel_path": storage_rel_path,
                }
            )
            moved_count += 1

        response = requests.post(
            f"{self.settings.api_base_url.rstrip('/')}/mission-history/{history_id}/media/register",
            headers={**self._backend_headers(), "Content-Type": "application/json"},
            json={"items": items},
            timeout=timeout_seconds,
        )
        if not response.ok:
            raise RuntimeError(f"media register failed with status {response.status_code}")

        return {
            "delivery_ok": len(errors) == 0,
            "delivered_file_count": moved_count,
            "delivery_failed_file_count": len(errors),
            "delivery_errors": errors,
            "register_root": register_root_abs,
        }

    def _send_gimbal_command(
        self,
        pitch_deg: float,
        yaw_deg: float,
        pitch_rate_dps: float | None,
        yaw_rate_dps: float | None,
        flags: int,
        gimbal_device_id: int,
    ) -> None:
        with self.mav_lock:
            self.mav.mav.command_long_send(
                self.settings.gimbal_target_system,
                self.settings.gimbal_target_component,
                mavutil.mavlink.MAV_CMD_DO_GIMBAL_MANAGER_PITCHYAW,
                0,
                float(pitch_deg),
                float(yaw_deg),
                float("nan") if pitch_rate_dps is None else float(pitch_rate_dps),
                float("nan") if yaw_rate_dps is None else float(yaw_rate_dps),
                float(flags),
                0.0,
                float(gimbal_device_id),
            )

    def _read_mavlink_message(self):
        with self.mav_lock:
            return self.mav.recv_match(blocking=True, timeout=1)

    @staticmethod
    def _frame_label_from_flags(flags: int) -> str | None:
        if flags & GimbalBridge.GIMBAL_MANAGER_FLAGS_YAW_IN_EARTH_FRAME:
            return "earth"
        if flags & GimbalBridge.GIMBAL_MANAGER_FLAGS_YAW_IN_VEHICLE_FRAME:
            return "vehicle"
        if flags & GimbalBridge.GIMBAL_MANAGER_FLAGS_YAW_LOCK:
            return "earth"
        return "vehicle"

    @staticmethod
    def _command_flags(mode: str) -> int:
        normalized = mode.lower()
        if normalized == "lock":
            return GimbalBridge.GIMBAL_MANAGER_FLAGS_YAW_LOCK
        return GimbalBridge.GIMBAL_MANAGER_FLAGS_YAW_IN_VEHICLE_FRAME

    async def _handle_gimbal_command(self, payload: dict[str, Any]) -> None:
        command = str(payload.get("command", "set_pitch_yaw")).lower()
        if command != "set_pitch_yaw":
            logger.warning("unsupported gimbal command=%s", command)
            return

        try:
            pitch_deg = float(payload["pitch_deg"])
            yaw_deg = float(payload["yaw_deg"])
        except (KeyError, TypeError, ValueError):
            logger.warning("gimbal command requires numeric pitch_deg and yaw_deg")
            return

        pitch_rate = payload.get("pitch_rate_dps")
        yaw_rate = payload.get("yaw_rate_dps")
        pitch_rate_dps = None if pitch_rate is None else float(pitch_rate)
        yaw_rate_dps = None if yaw_rate is None else float(yaw_rate)

        mode = str(payload.get("mode", "follow"))
        flags = self._command_flags(mode)
        gimbal_device_id = int(payload.get("gimbal_device_id", self.settings.gimbal_device_id))

        await asyncio.to_thread(
            self._send_gimbal_command,
            pitch_deg,
            yaw_deg,
            pitch_rate_dps,
            yaw_rate_dps,
            flags,
            gimbal_device_id,
        )
        logger.info(
            "sent gimbal command pitch=%.2f yaw=%.2f mode=%s device_id=%s",
            pitch_deg,
            yaw_deg,
            mode,
            gimbal_device_id,
        )

    async def _handle_camera_command(self, payload: dict[str, Any]) -> None:
        if self.camera is None:
            logger.warning("ignoring camera command because SIYI camera is disabled")
            return

        try:
            state = await asyncio.to_thread(self.camera.execute_command, payload)
        except Exception as exc:
            logger.warning("camera command failed: %s", exc)
            return

        await self.publish_metric(
            self.settings.camera_state_metric,
            state,
            self.settings.camera_state_interval_seconds,
        )

    async def _publish_mission_event(self, payload: dict[str, Any]) -> None:
        await self.backend.publish(self.settings.mission_event_metric, payload)

    async def _process_post_landing_media(self, payload: dict[str, Any]) -> None:
        if not self.settings.mission_post_landing_media_enabled:
            return

        history_id = payload.get("history_id")
        try:
            history_id_value = int(history_id)
        except (TypeError, ValueError):
            logger.warning("ignoring media processing request without valid history_id: %r", history_id)
            return

        if self.active_media_processing_history_id == history_id_value:
            logger.info("media processing already in progress for history_id=%s", history_id_value)
            return
        if self.last_completed_media_processing_history_id == history_id_value:
            logger.info("ignoring duplicate media processing request for history_id=%s", history_id_value)
            return

        self.active_media_processing_history_id = history_id_value
        started_at = time.monotonic()
        local_root = LOCAL_MEDIA_ROOT
        history_media_dir = os.path.join(local_root, f"history-{history_id_value}", "media")
        delivery_mode = self.settings.mission_camera_media_delivery_mode
        download_ok = None
        delivery_ok = None
        format_ok = None
        downloaded_file_count = 0
        failed_file_count = 0
        delivered_file_count = 0
        delivery_failed_file_count = 0
        failure_reason = None
        result_event = "media_processing_completed"

        try:
            if self.camera is None:
                raise RuntimeError("SIYI camera is disabled")
            if not self.settings.mission_post_landing_media_download_enabled and not self.settings.mission_post_landing_media_format_enabled:
                raise RuntimeError("media processing is enabled but both download and format steps are disabled")
            if delivery_mode != "local_only" and not self.settings.mission_post_landing_media_download_enabled:
                raise RuntimeError("download step must be enabled for upload/register_move delivery mode")

            downloaded_files: list[str] = []

            if self.settings.mission_post_landing_media_download_enabled:
                download_result = await asyncio.wait_for(
                    asyncio.to_thread(
                        self.camera.download_media,
                        history_media_dir,
                        self.settings.mission_post_landing_media_timeout_sec,
                    ),
                    timeout=self.settings.mission_post_landing_media_timeout_sec,
                )
                download_ok = bool(download_result.get("download_ok"))
                downloaded_file_count = int(download_result.get("downloaded_file_count", 0) or 0)
                failed_file_count = int(download_result.get("failed_file_count", 0) or 0)
                if not download_ok and failed_file_count > 0:
                    failure_reason = "; ".join(download_result.get("errors", [])[:3]) or "one or more media downloads failed"
                downloaded_files = list(download_result.get("downloaded_files", []))
            else:
                download_ok = True

            if self.settings.mission_post_landing_media_format_enabled:
                elapsed = time.monotonic() - started_at
                remaining = self.settings.mission_post_landing_media_timeout_sec - elapsed
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                format_result = await asyncio.wait_for(
                    asyncio.to_thread(self.camera.format_sd_card),
                    timeout=remaining,
                )
                format_ok = bool(format_result.get("format_ok"))
                if not format_ok and failure_reason is None:
                    failure_reason = "format SD card reported failure"
            else:
                format_ok = True

            if download_ok and format_ok:
                if delivery_mode == "upload":
                    elapsed = time.monotonic() - started_at
                    remaining = self.settings.mission_post_landing_media_timeout_sec - elapsed
                    if remaining <= 0:
                        raise asyncio.TimeoutError()
                    delivery_result = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._upload_downloaded_media,
                            history_id_value,
                            downloaded_files,
                            remaining,
                        ),
                        timeout=remaining,
                    )
                    delivery_ok = bool(delivery_result.get("delivery_ok"))
                    delivered_file_count = int(delivery_result.get("delivered_file_count", 0) or 0)
                    delivery_failed_file_count = int(delivery_result.get("delivery_failed_file_count", 0) or 0)
                    if not delivery_ok and failure_reason is None:
                        failure_reason = "; ".join(delivery_result.get("delivery_errors", [])[:3]) or "media upload failed"
                elif delivery_mode == "register_move":
                    elapsed = time.monotonic() - started_at
                    remaining = self.settings.mission_post_landing_media_timeout_sec - elapsed
                    if remaining <= 0:
                        raise asyncio.TimeoutError()
                    delivery_result = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._register_move_downloaded_media,
                            history_id_value,
                            downloaded_files,
                            remaining,
                        ),
                        timeout=remaining,
                    )
                    delivery_ok = bool(delivery_result.get("delivery_ok"))
                    delivered_file_count = int(delivery_result.get("delivered_file_count", 0) or 0)
                    delivery_failed_file_count = int(delivery_result.get("delivery_failed_file_count", 0) or 0)
                    if not delivery_ok and failure_reason is None:
                        failure_reason = "; ".join(delivery_result.get("delivery_errors", [])[:3]) or "media register failed"
                else:
                    delivery_ok = True
            else:
                delivery_ok = delivery_mode == "local_only"

            if (download_ok is False or delivery_ok is False or format_ok is False) and result_event != "media_processing_timeout":
                result_event = "media_processing_failed"
        except asyncio.TimeoutError:
            result_event = "media_processing_timeout"
            failure_reason = "media processing exceeded configured timeout"
        except Exception as exc:
            result_event = "media_processing_failed"
            if failure_reason is None:
                failure_reason = str(exc)
            logger.warning("post-landing media processing failed for history_id=%s: %s", history_id_value, exc)
        finally:
            confirmation_payload = compact_payload(
                {
                    "history_id": history_id_value,
                    "event": result_event,
                    "message": {
                        "media_processing_completed": "Media processing finished",
                        "media_processing_failed": "Media processing finished with errors",
                        "media_processing_timeout": "Media processing timed out",
                    }[result_event],
                    "media_delivery_mode": delivery_mode,
                    "media_download_ok": download_ok,
                    "media_delivery_ok": delivery_ok,
                    "media_format_ok": format_ok,
                    "downloaded_file_count": downloaded_file_count,
                    "failed_file_count": failed_file_count,
                    "delivered_file_count": delivered_file_count,
                    "delivery_failed_file_count": delivery_failed_file_count,
                    "download_root": history_media_dir if self.settings.mission_post_landing_media_download_enabled else None,
                    "failure_reason": failure_reason,
                }
            )
            await self._publish_mission_event(confirmation_payload)
            self.active_media_processing_history_id = None
            self.last_completed_media_processing_history_id = history_id_value

    async def _handle_mission_event(self, payload: dict[str, Any]) -> None:
        event = str(payload.get("event", "")).strip().lower()
        if event == "media_processing_requested":
            await self._process_post_landing_media(payload)
            return

        if not self.settings.mission_event_camera_actions_enabled:
            return
        if event != "waypoint_reached":
            return

        action = str(payload.get("waypoint_action", "")).strip()
        if not action:
            return

        history_id = payload.get("history_id")
        mission_seq = payload.get("mission_seq")
        waypoint_sequence_order = payload.get("waypoint_sequence_order")
        try:
            history_id_value = None if history_id is None else int(history_id)
        except (TypeError, ValueError):
            history_id_value = None
        try:
            mission_seq_value = None if mission_seq is None else int(mission_seq)
        except (TypeError, ValueError):
            mission_seq_value = None
        try:
            waypoint_sequence_order_value = None if waypoint_sequence_order is None else int(waypoint_sequence_order)
        except (TypeError, ValueError):
            waypoint_sequence_order_value = None

        waypoint_index = payload.get("waypoint_index")
        try:
            waypoint_index_value = None if waypoint_index is None else int(waypoint_index)
        except (TypeError, ValueError):
            waypoint_index_value = None

        action_key = (
            history_id_value,
            mission_seq_value,
            waypoint_index_value,
            waypoint_sequence_order_value,
            action.lower(),
        )

        if action_key == self.last_waypoint_reached_action_key:
            return

        self.last_waypoint_reached_action_key = action_key

        if action.lower() == "take picture":
            await self._handle_camera_command({"command": "take_photo"})
            logger.info("triggered take_photo for waypoint action=%s on waypoint_reached", action_key)
            return

        if action.lower() != "record video":
            logger.warning("ignoring unsupported waypoint action=%s", action)
            return

        if self.active_recording_waypoint_key == action_key:
            return

        duration = payload.get("waypoint_hold_time", payload.get("waypoint_action_duration"))
        try:
            duration_seconds = float(duration)
        except (TypeError, ValueError):
            logger.warning("record video waypoint requires numeric hold duration, got=%r", duration)
            return
        if duration_seconds <= 0:
            logger.warning("record video waypoint requires hold duration > 0, got=%s", duration_seconds)
            return

        if self.recording_stop_task is not None:
            self.recording_stop_task.cancel()
            self.recording_stop_task = None

        await self._handle_camera_command({"command": "set_recording", "enabled": True})
        self.active_recording_waypoint_key = action_key
        self.recording_stop_task = asyncio.create_task(
            self._stop_recording_after(duration_seconds, action_key)
        )
        logger.info(
            "started recording for waypoint action=%s on waypoint_reached, stopping after %.2fs",
            action_key,
            duration_seconds,
        )

    async def _stop_recording_after(
        self,
        duration_seconds: float,
        waypoint_key: tuple[int | None, int | None, int | None, int | None, str],
    ) -> None:
        try:
            await asyncio.sleep(duration_seconds)
            if self.active_recording_waypoint_key != waypoint_key:
                return
            await self._handle_camera_command({"command": "set_recording", "enabled": False})
            logger.info("stopped recording for waypoint action=%s after %.2fs", waypoint_key, duration_seconds)
            self.active_recording_waypoint_key = None
            self.recording_stop_task = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("failed to stop recording for waypoint action=%s: %s", waypoint_key, exc)

    async def handle_ws_message(self, raw_message: str) -> None:
        try:
            data = json.loads(raw_message)
        except json.JSONDecodeError:
            logger.warning("ignoring non-json ws message")
            return

        if data.get("kind") != "telemetry":
            return
        if int(data.get("uav_id", 0) or 0) != self.settings.uav_id:
            return

        payload = data.get("payload")
        if not isinstance(payload, dict):
            logger.warning("ignoring ws command without object payload")
            return

        metric = str(data.get("metric", "")).lower()
        if metric == self.settings.metric_command.lower():
            await self._handle_gimbal_command(payload)
            return
        if metric == self.settings.camera_command_metric.lower():
            await self._handle_camera_command(payload)
            return
        if metric == self.settings.mission_event_metric.lower():
            await self._handle_mission_event(payload)
            return

        return

    async def publish_metric(self, metric: str, payload: dict[str, Any], interval_seconds: float) -> None:
        now = time.monotonic()
        last_payload = self.last_published_payloads.get(metric)
        last_sent_at = self.last_published_at.get(metric, 0.0)
        if payload == last_payload and now - last_sent_at < interval_seconds:
            return
        self.last_published_payloads[metric] = payload
        self.last_published_at[metric] = now
        await self.backend.publish(metric, payload)

    async def publish_state(self, payload: dict[str, Any]) -> None:
        await self.publish_metric(
            self.settings.metric_state,
            payload,
            self.settings.state_interval_seconds,
        )

    async def ws_receiver_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                async for message in self.backend.websocket:
                    await self.handle_ws_message(message)
            except websockets.ConnectionClosed as exc:
                if self.stop_event.is_set():
                    return
                await self.backend.reconnect(str(exc))

    async def mavlink_reader_loop(self) -> None:
        while not self.stop_event.is_set():
            message = await asyncio.to_thread(self._read_mavlink_message)
            if message is None:
                continue

            if message.get_type() != "GIMBAL_DEVICE_ATTITUDE_STATUS":
                continue

            self.last_status_at = time.monotonic()
            if not self.connected:
                self.connected = True

            roll_deg, pitch_deg, yaw_deg = quaternion_to_euler_degrees(list(message.q))
            payload = compact_payload(
                {
                    "connected": True,
                    "gimbal_device_id": message.get_srcComponent(),
                    "frame": self._frame_label_from_flags(int(message.flags)),
                    "roll_deg": round(roll_deg, 2),
                    "pitch_deg": round(pitch_deg, 2),
                    "yaw_deg": round(yaw_deg, 2),
                    "roll_rate_dps": None
                    if is_nan(message.angular_velocity_x)
                    else round(math.degrees(message.angular_velocity_x), 2),
                    "pitch_rate_dps": None
                    if is_nan(message.angular_velocity_y)
                    else round(math.degrees(message.angular_velocity_y), 2),
                    "yaw_rate_dps": None
                    if is_nan(message.angular_velocity_z)
                    else round(math.degrees(message.angular_velocity_z), 2),
                    "flags": int(message.flags),
                    "failure_flags": int(message.failure_flags),
                    "time_boot_ms": int(message.time_boot_ms),
                }
            )
            await self.publish_state(payload)

    async def connection_state_loop(self) -> None:
        while not self.stop_event.is_set():
            await asyncio.sleep(self.settings.connected_timeout_seconds / 2.0)
            timed_out = (
                self.connected
                and self.last_status_at > 0
                and time.monotonic() - self.last_status_at > self.settings.connected_timeout_seconds
            )
            if timed_out:
                self.connected = False
                await self.publish_state({"connected": False})

    async def camera_state_loop(self) -> None:
        if self.camera is None:
            return

        while not self.stop_event.is_set():
            try:
                if not await asyncio.to_thread(self.camera.is_connected):
                    connected = await asyncio.to_thread(self.camera.connect)
                    if not connected:
                        logger.warning(
                            "SIYI camera is not reachable yet, retrying in %.1fs",
                            self.camera.settings.reconnect_delay_seconds,
                        )
                        await self.publish_metric(
                            self.settings.camera_state_metric,
                            {"connected": False},
                            self.settings.camera_state_interval_seconds,
                        )
                        await asyncio.sleep(self.camera.settings.reconnect_delay_seconds)
                        continue

                payload = await asyncio.to_thread(self.camera.snapshot_state, True)
                await self.publish_metric(
                    self.settings.camera_state_metric,
                    payload,
                    self.settings.camera_state_interval_seconds,
                )
            except Exception as exc:
                logger.warning("camera state loop error: %s", exc)
                await self.publish_metric(
                    self.settings.camera_state_metric,
                    {"connected": False},
                    self.settings.camera_state_interval_seconds,
                )
            await asyncio.sleep(self.settings.camera_state_interval_seconds)

    async def run(self) -> None:
        await self.backend.connect()
        metrics = [self.settings.metric_command]
        if self.settings.mission_event_camera_actions_enabled:
            metrics.append(self.settings.mission_event_metric)
        tasks = [
            self.ws_receiver_loop(),
            self.mavlink_reader_loop(),
            self.connection_state_loop(),
        ]
        if self.camera is not None:
            metrics.append(self.settings.camera_command_metric)
            tasks.append(self.camera_state_loop())
        await self.backend.subscribe(metrics)
        await asyncio.gather(*tasks)

    async def shutdown(self) -> None:
        self.stop_event.set()
        if self.recording_stop_task is not None:
            self.recording_stop_task.cancel()
        if self.camera is not None:
            await asyncio.to_thread(self.camera.disconnect)
        if self.backend.websocket is not None:
            await self.backend.websocket.close()


async def main() -> None:
    settings = Settings()
    bridge = GimbalBridge(settings)
    loop = asyncio.get_running_loop()

    def _request_shutdown() -> None:
        asyncio.create_task(bridge.shutdown())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _request_shutdown)

    try:
        await bridge.run()
    finally:
        await bridge.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
