const state = {
  websocket: null,
  isConnected: false,
  isDragging: false,
  targetPitch: 0,
  targetYaw: 0,
  cameraConnected: false,
  targetInitialized: false,
  userHasTakenControl: false,
  normalizedX: 0,
  normalizedY: 0,
  lastTick: 0,
  lastSentAt: 0,
  rafId: 0,
};

const elements = {
  connectButton: document.getElementById("connectButton"),
  centerButton: document.getElementById("centerButton"),
  clearLogButton: document.getElementById("clearLogButton"),
  sendManualButton: document.getElementById("sendManualButton"),
  wsStatus: document.getElementById("wsStatus"),
  gimbalStatus: document.getElementById("gimbalStatus"),
  cameraStatus: document.getElementById("cameraStatus"),
  baseUrlInput: document.getElementById("baseUrlInput"),
  deviceTokenInput: document.getElementById("deviceTokenInput"),
  uavIdInput: document.getElementById("uavIdInput"),
  modeInput: document.getElementById("modeInput"),
  gimbalDeviceIdInput: document.getElementById("gimbalDeviceIdInput"),
  maxPitchInput: document.getElementById("maxPitchInput"),
  maxYawInput: document.getElementById("maxYawInput"),
  pitchSpeedInput: document.getElementById("pitchSpeedInput"),
  yawSpeedInput: document.getElementById("yawSpeedInput"),
  deadzoneInput: document.getElementById("deadzoneInput"),
  sendIntervalInput: document.getElementById("sendIntervalInput"),
  manualPitchInput: document.getElementById("manualPitchInput"),
  manualYawInput: document.getElementById("manualYawInput"),
  joystick: document.getElementById("joystick"),
  joystickStick: document.getElementById("joystickStick"),
  targetPitchValue: document.getElementById("targetPitchValue"),
  targetYawValue: document.getElementById("targetYawValue"),
  livePitchValue: document.getElementById("livePitchValue"),
  liveYawValue: document.getElementById("liveYawValue"),
  frameValue: document.getElementById("frameValue"),
  flagsValue: document.getElementById("flagsValue"),
  recordingStateValue: document.getElementById("recordingStateValue"),
  zoomLevelValue: document.getElementById("zoomLevelValue"),
  cameraTypeValue: document.getElementById("cameraTypeValue"),
  takePhotoButton: document.getElementById("takePhotoButton"),
  startRecordingButton: document.getElementById("startRecordingButton"),
  stopRecordingButton: document.getElementById("stopRecordingButton"),
  toggleRecordingButton: document.getElementById("toggleRecordingButton"),
  zoomInButton: document.getElementById("zoomInButton"),
  zoomOutButton: document.getElementById("zoomOutButton"),
  zoomStopButton: document.getElementById("zoomStopButton"),
  zoomLevelInput: document.getElementById("zoomLevelInput"),
  setZoomButton: document.getElementById("setZoomButton"),
  logOutput: document.getElementById("logOutput"),
};

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function toNumber(input, fallback) {
  const value = Number(input.value);
  return Number.isFinite(value) ? value : fallback;
}

function getConfig() {
  const baseUrl = elements.baseUrlInput.value.trim().replace(/\/+$/, "");
  return {
    baseUrl,
    wsUrl: `${baseUrl.replace(/^http:/, "ws:").replace(/^https:/, "wss:")}/ws/telemetry`,
    deviceToken: elements.deviceTokenInput.value.trim(),
    uavId: Math.max(1, Math.trunc(toNumber(elements.uavIdInput, 1))),
    mode: elements.modeInput.value,
    gimbalDeviceId: Math.max(0, Math.trunc(toNumber(elements.gimbalDeviceIdInput, 0))),
    maxPitch: Math.max(1, toNumber(elements.maxPitchInput, 90)),
    maxYaw: Math.max(1, toNumber(elements.maxYawInput, 180)),
    pitchSpeed: Math.max(1, toNumber(elements.pitchSpeedInput, 38)),
    yawSpeed: Math.max(1, toNumber(elements.yawSpeedInput, 65)),
    deadzone: clamp(toNumber(elements.deadzoneInput, 0.12), 0, 0.5),
    sendIntervalMs: Math.max(50, toNumber(elements.sendIntervalInput, 100)),
  };
}

function log(message, data) {
  const timestamp = new Date().toLocaleTimeString();
  const suffix = data === undefined ? "" : ` ${JSON.stringify(data)}`;
  elements.logOutput.textContent = `[${timestamp}] ${message}${suffix}\n${elements.logOutput.textContent}`;
}

function setWsStatus(label, className = "") {
  elements.wsStatus.textContent = label;
  elements.wsStatus.className = "status-pill";
  if (className) {
    elements.wsStatus.classList.add(className);
  }
}

function setGimbalStatus(label, className = "") {
  elements.gimbalStatus.textContent = label;
  elements.gimbalStatus.className = "status-pill";
  if (className) {
    elements.gimbalStatus.classList.add(className);
  }
}

function setCameraStatus(label, className = "") {
  elements.cameraStatus.textContent = label;
  elements.cameraStatus.className = "status-pill";
  if (className) {
    elements.cameraStatus.classList.add(className);
  }
}

function updateTargetReadout() {
  elements.targetPitchValue.textContent = `${Math.round(state.targetPitch)}°`;
  elements.targetYawValue.textContent = `${Math.round(state.targetYaw)}°`;
}

function syncManualInputs() {
  elements.manualPitchInput.value = String(Math.round(state.targetPitch));
  elements.manualYawInput.value = String(Math.round(state.targetYaw));
}

function updateStickPosition(dx = 0, dy = 0) {
  elements.joystickStick.style.transform = `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px))`;
}

function resetStick() {
  state.normalizedX = 0;
  state.normalizedY = 0;
  updateStickPosition(0, 0);
}

function applyDeadzone(value, deadzone) {
  if (Math.abs(value) < deadzone) {
    return 0;
  }

  const direction = Math.sign(value);
  const scaled = (Math.abs(value) - deadzone) / (1 - deadzone);
  return direction * scaled;
}

function sendJson(payload) {
  if (!state.websocket || state.websocket.readyState !== WebSocket.OPEN) {
    return false;
  }

  state.websocket.send(JSON.stringify(payload));
  return true;
}

function subscribeGimbalState() {
  const config = getConfig();
  return sendJson({
    type: "subscribe",
    uav_ids: [config.uavId],
    metrics: ["gimbal_state", "camera_state"],
  });
}

function buildCommandPayload() {
  const config = getConfig();
  return {
    type: "publish",
    uav_id: config.uavId,
    kind: "telemetry",
    metric: "gimbal_command",
    payload: {
      command: "set_pitch_yaw",
      pitch_deg: Math.round(state.targetPitch),
      yaw_deg: Math.round(state.targetYaw),
      mode: config.mode,
      gimbal_device_id: config.gimbalDeviceId,
    },
  };
}

function sendCurrentTarget(reason) {
  if (!state.targetInitialized) {
    return;
  }
  const payload = buildCommandPayload();
  if (!sendJson(payload)) {
    return;
  }
  state.lastSentAt = performance.now();
  log(`sent ${reason}`, payload);
}

function sendCameraCommand(payload, reason) {
  const config = getConfig();
  const message = {
    type: "publish",
    uav_id: config.uavId,
    kind: "telemetry",
    metric: "camera_command",
    payload,
  };
  if (!sendJson(message)) {
    log("camera command gagal dikirim, websocket belum open");
    return false;
  }
  log(`sent ${reason}`, message);
  return true;
}

function animate(now) {
  const config = getConfig();

  if (!state.lastTick) {
    state.lastTick = now;
  }

  const dt = (now - state.lastTick) / 1000;
  state.lastTick = now;

  state.targetYaw = clamp(
    state.targetYaw + state.normalizedX * config.yawSpeed * dt,
    -config.maxYaw,
    config.maxYaw,
  );
  state.targetPitch = clamp(
    state.targetPitch + -state.normalizedY * config.pitchSpeed * dt,
    -config.maxPitch,
    config.maxPitch,
  );

  updateTargetReadout();

  if (state.isConnected && state.targetInitialized && now - state.lastSentAt >= config.sendIntervalMs) {
    sendCurrentTarget("joystick target");
  }

  state.rafId = window.requestAnimationFrame(animate);
}

function handleTelemetryEvent(message) {
  if (!message.payload) {
    return;
  }

  const payload = message.payload;
  if (message.metric === "gimbal_state") {
    elements.livePitchValue.textContent = payload.pitch_deg === undefined ? "-" : `${payload.pitch_deg}°`;
    elements.liveYawValue.textContent = payload.yaw_deg === undefined ? "-" : `${payload.yaw_deg}°`;
    elements.frameValue.textContent = payload.frame ?? "-";
    elements.flagsValue.textContent = payload.flags === undefined ? "-" : String(payload.flags);

    if (
      payload.connected === true &&
      Number.isFinite(payload.pitch_deg) &&
      Number.isFinite(payload.yaw_deg) &&
      !state.userHasTakenControl
    ) {
      state.targetPitch = payload.pitch_deg;
      state.targetYaw = payload.yaw_deg;
      state.targetInitialized = true;
      updateTargetReadout();
      syncManualInputs();
    }

    if (payload.connected === true) {
      setGimbalStatus("Gimbal connected", "is-connected");
    } else if (payload.connected === false) {
      setGimbalStatus("Gimbal disconnected", "is-warning");
    }
    return;
  }

  if (message.metric === "camera_state") {
    state.cameraConnected = payload.connected === true;
    elements.recordingStateValue.textContent = payload.recording_label ?? "-";
    elements.zoomLevelValue.textContent = payload.zoom_level === undefined ? "-" : `${payload.zoom_level}x`;
    elements.cameraTypeValue.textContent = payload.camera_type ?? "-";

    if (payload.connected === true) {
      setCameraStatus("Camera connected", "is-connected");
    } else if (payload.connected === false) {
      setCameraStatus("Camera disconnected", "is-warning");
    }
  }
}

function takePhoto() {
  sendCameraCommand({ command: "take_photo" }, "take photo");
}

function startRecording() {
  sendCameraCommand({ command: "set_recording", enabled: true }, "start recording");
}

function stopRecording() {
  sendCameraCommand({ command: "set_recording", enabled: false }, "stop recording");
}

function toggleRecording() {
  sendCameraCommand({ command: "toggle_recording" }, "toggle recording");
}

function zoomIn() {
  sendCameraCommand({ command: "zoom_in" }, "zoom in");
}

function zoomOut() {
  sendCameraCommand({ command: "zoom_out" }, "zoom out");
}

function zoomStop() {
  sendCameraCommand({ command: "zoom_stop" }, "zoom stop");
}

function setZoomLevel() {
  const zoomLevel = Number(elements.zoomLevelInput.value);
  if (!Number.isFinite(zoomLevel)) {
    log("zoom level harus angka");
    return;
  }
  sendCameraCommand({ command: "set_zoom_level", zoom_level: zoomLevel }, "set zoom level");
}

function connectWebSocket() {
  const config = getConfig();

  if (!config.baseUrl) {
    log("backend base url wajib diisi");
    return;
  }

  if (!config.deviceToken) {
    log("device token wajib diisi");
    return;
  }

  if (state.websocket) {
    state.websocket.close();
  }

  setWsStatus("WS connecting");
  fetch(`${config.baseUrl}/auth/ws-token`, {
    method: "POST",
    headers: {
      "X-Device-Token": config.deviceToken,
    },
  })
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`ws token request failed: ${response.status}`);
      }
      return response.json();
    })
    .then((data) => {
      const token = data.token ?? data.ws_token ?? data.access_token ?? data?.data?.token ?? data?.data?.ws_token ?? data?.data?.access_token;
      if (!token) {
        throw new Error("response /auth/ws-token tidak mengandung token");
      }

      const ws = new WebSocket(`${config.wsUrl}?token=${encodeURIComponent(token)}`);
      state.websocket = ws;

      ws.addEventListener("open", () => {
        state.isConnected = true;
        state.targetInitialized = false;
        state.userHasTakenControl = false;
        state.lastSentAt = 0;
        setWsStatus("WS connected", "is-connected");
        subscribeGimbalState();
        log("websocket connected");
      });

      ws.addEventListener("message", (event) => {
        try {
          const message = JSON.parse(event.data);
          handleTelemetryEvent(message);
        } catch (error) {
          log("invalid ws message", { raw: event.data });
        }
      });

      ws.addEventListener("close", () => {
        state.isConnected = false;
        setWsStatus("WS disconnected", "is-warning");
        log("websocket disconnected");
      });

      ws.addEventListener("error", () => {
        setWsStatus("WS error", "is-warning");
        log("websocket error");
      });
    })
    .catch((error) => {
      state.isConnected = false;
      setWsStatus("WS auth failed", "is-warning");
      log("gagal ambil ws token", { message: error.message });
    });
}

function updateJoystickFromPoint(clientX, clientY) {
  const rect = elements.joystick.getBoundingClientRect();
  const radius = rect.width / 2;
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;

  let dx = clientX - cx;
  let dy = clientY - cy;

  const distance = Math.sqrt(dx * dx + dy * dy);
  if (distance > radius) {
    dx = (dx / distance) * radius;
    dy = (dy / distance) * radius;
  }

  const config = getConfig();
  state.normalizedX = applyDeadzone(dx / radius, config.deadzone);
  state.normalizedY = applyDeadzone(dy / radius, config.deadzone);
  updateStickPosition(dx, dy);
}

function beginDrag(event) {
  state.isDragging = true;
  state.userHasTakenControl = true;
  state.targetInitialized = true;
  elements.joystick.setPointerCapture(event.pointerId);
  updateJoystickFromPoint(event.clientX, event.clientY);
}

function moveDrag(event) {
  if (!state.isDragging) {
    return;
  }
  updateJoystickFromPoint(event.clientX, event.clientY);
}

function endDrag(event) {
  if (!state.isDragging) {
    return;
  }

  state.isDragging = false;
  if (event.pointerId !== undefined) {
    elements.joystick.releasePointerCapture(event.pointerId);
  }
  resetStick();
}

function centerTarget() {
  state.targetPitch = 0;
  state.targetYaw = 0;
  state.targetInitialized = true;
  state.userHasTakenControl = true;
  updateTargetReadout();
  syncManualInputs();
  resetStick();
  if (state.isConnected) {
    sendCurrentTarget("center target");
  }
}

function sendManualTarget() {
  const config = getConfig();
  state.targetPitch = clamp(toNumber(elements.manualPitchInput, 0), -config.maxPitch, config.maxPitch);
  state.targetYaw = clamp(toNumber(elements.manualYawInput, 0), -config.maxYaw, config.maxYaw);
  state.targetInitialized = true;
  state.userHasTakenControl = true;
  updateTargetReadout();
  sendCurrentTarget("manual target");
}

function bindEvents() {
  elements.connectButton.addEventListener("click", connectWebSocket);
  elements.centerButton.addEventListener("click", centerTarget);
  elements.clearLogButton.addEventListener("click", () => {
    elements.logOutput.textContent = "";
  });
  elements.sendManualButton.addEventListener("click", sendManualTarget);
  elements.takePhotoButton.addEventListener("click", takePhoto);
  elements.startRecordingButton.addEventListener("click", startRecording);
  elements.stopRecordingButton.addEventListener("click", stopRecording);
  elements.toggleRecordingButton.addEventListener("click", toggleRecording);
  elements.zoomInButton.addEventListener("click", zoomIn);
  elements.zoomOutButton.addEventListener("click", zoomOut);
  elements.zoomStopButton.addEventListener("click", zoomStop);
  elements.setZoomButton.addEventListener("click", setZoomLevel);

  elements.joystick.addEventListener("pointerdown", beginDrag);
  elements.joystick.addEventListener("pointermove", moveDrag);
  elements.joystick.addEventListener("pointerup", endDrag);
  elements.joystick.addEventListener("pointercancel", endDrag);
  elements.joystick.addEventListener("pointerleave", (event) => {
    if (state.isDragging && event.buttons === 0) {
      endDrag(event);
    }
  });
}

function init() {
  bindEvents();
  updateTargetReadout();
  syncManualInputs();
  resetStick();
  setWsStatus("WS disconnected", "is-warning");
  setGimbalStatus("Gimbal unknown", "is-warning");
  setCameraStatus("Camera unknown", "is-warning");
  state.rafId = window.requestAnimationFrame(animate);
  log("ui ready");
}

init();
