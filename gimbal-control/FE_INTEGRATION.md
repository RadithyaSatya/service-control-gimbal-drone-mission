# FE Agent Brief: Gimbal And Camera Control via WebSocket

Dokumen ini ditulis khusus agar mudah dilempar ke agent/frontend engineer lain.

Tujuannya: implement UI kontrol gimbal di frontend yang membaca posisi live gimbal, mengirim command gimbal lewat WebSocket backend, dan menambah kontrol kamera untuk zoom, record, dan take picture.

## Objective

Bangun fitur frontend gimbal dan camera control dengan behavior berikut:

1. frontend ambil WS token dari backend
2. frontend connect ke realtime WebSocket
3. frontend subscribe `gimbal_state` dan `camera_state`
4. frontend membaca posisi live gimbal
5. posisi live itu dipakai sebagai initial target
6. joystick frontend menghitung target pitch/yaw baru
7. frontend publish `gimbal_command`
8. frontend publish `camera_command` untuk aksi kamera
9. frontend tidak boleh auto mengirim `0,0` saat baru connect

## Non-Negotiable Rules

Agent harus mengikuti semua rule ini:

1. Jangan set target awal ke `0,0` saat connect.
2. Initial target wajib diambil dari `gimbal_state.payload.pitch_deg` dan `gimbal_state.payload.yaw_deg`.
3. Jangan publish command sebelum initial target didapat dari telemetry live, kecuali user sudah eksplisit menekan control manual/joystick/center.
4. Frontend harus subscribe `gimbal_state` setelah WS `open`.
5. Frontend harus publish `gimbal_command` dengan envelope WS yang benar.
6. Joystick harus dihitung sebagai perubahan sudut terhadap waktu, bukan kirim nilai joystick mentah.
7. Yang dikirim ke backend adalah target akhir `pitch_deg` dan `yaw_deg`.
8. Flow `gimbal_command` tidak boleh diubah untuk aksi kamera; gunakan `camera_command` terpisah.
9. Frontend harus subscribe `camera_state` jika ingin menampilkan status recording/zoom kamera.

## Backend Contracts

Referensi utama:

- [WEBSOCKET_CONTRACT.md](/Users/macbook/Workdir/Office/Projects/drone/service-camera-drone-mission/WEBSOCKET_CONTRACT.md)
- [gimbal-ws-contract.md](/Users/macbook/Workdir/Office/Projects/drone/service-camera-drone-mission/gimbal-ws-contract.md)
- [GIMBAL_ONLY.md](/Users/macbook/Workdir/Office/Projects/drone/service-camera-drone-mission/GIMBAL_ONLY.md)

## Required Flow

Frontend flow yang benar:

1. call `POST /auth/ws-token`
2. kirim header `X-Device-Token: <DEVICE_TOKEN>` atau auth flow backend yang berlaku
3. ambil token dari response
4. connect ke `GET /ws/telemetry?token=<WS_TOKEN>`
5. saat WS open, kirim subscribe `gimbal_state` dan `camera_state`
6. tunggu telemetry `gimbal_state`
7. pakai `pitch_deg` dan `yaw_deg` dari telemetry pertama sebagai initial target
8. saat user menggerakkan joystick, hitung target baru
9. publish `gimbal_command`
10. saat user memakai panel kamera, publish `camera_command`

## Subscribe Message

Kirim message ini setelah WebSocket connect:

```json
{
  "type": "subscribe",
  "uav_ids": [1],
  "metrics": ["gimbal_state", "camera_state"]
}
```

## Telemetry Event Received

Frontend akan menerima event seperti ini:

```json
{
  "uav_id": 1,
  "kind": "telemetry",
  "metric": "gimbal_state",
  "ts": "2026-06-19T08:15:30Z",
  "payload": {
    "connected": true,
    "gimbal_device_id": 1,
    "frame": "vehicle",
    "roll_deg": 0.4,
    "pitch_deg": -18.7,
    "yaw_deg": 42.1,
    "roll_rate_dps": 0.0,
    "pitch_rate_dps": -1.4,
    "yaw_rate_dps": 5.8,
    "flags": 32,
    "failure_flags": 0,
    "time_boot_ms": 285019
  }
}
```

Frontend minimal harus membaca field ini:

- `payload.connected`
- `payload.pitch_deg`
- `payload.yaw_deg`

## Camera State Event Received

Frontend juga bisa menerima event seperti ini:

```json
{
  "uav_id": 1,
  "kind": "telemetry",
  "metric": "camera_state",
  "ts": "2026-06-22T08:15:30Z",
  "payload": {
    "connected": true,
    "recording_state": 1,
    "recording_label": "on",
    "zoom_level": 3.0,
    "camera_type": "A8 mini"
  }
}
```

Frontend minimal bisa membaca field ini:

- `payload.connected`
- `payload.recording_state`
- `payload.recording_label`
- `payload.zoom_level`
- `payload.camera_type`

## Initial Target Logic

Gunakan logic ini:

```js
let targetPitch = 0;
let targetYaw = 0;
let targetInitialized = false;
let userHasTakenControl = false;

function onGimbalState(payload) {
  if (
    payload.connected === true &&
    Number.isFinite(payload.pitch_deg) &&
    Number.isFinite(payload.yaw_deg) &&
    !userHasTakenControl
  ) {
    targetPitch = payload.pitch_deg;
    targetYaw = payload.yaw_deg;
    targetInitialized = true;
  }
}
```

Makna rule ini:

- sebelum user menyentuh kontrol, posisi live gimbal menjadi sumber kebenaran
- setelah user mulai mengontrol, jangan terus-menerus menimpa target lokal dari telemetry

## Publish Command Message

Frontend harus mengirim message ini saat mengontrol gimbal:

```json
{
  "type": "publish",
  "uav_id": 1,
  "kind": "telemetry",
  "metric": "gimbal_command",
  "payload": {
    "command": "set_pitch_yaw",
    "pitch_deg": -12,
    "yaw_deg": 63,
    "mode": "follow",
    "gimbal_device_id": 0
  }
}
```

Format lengkap jika ingin kirim rate:

```json
{
  "type": "publish",
  "uav_id": 1,
  "kind": "telemetry",
  "metric": "gimbal_command",
  "payload": {
    "command": "set_pitch_yaw",
    "pitch_deg": -20,
    "yaw_deg": 45,
    "pitch_rate_dps": 15,
    "yaw_rate_dps": 25,
    "mode": "follow",
    "gimbal_device_id": 0
  }
}
```

## Meaning Of Command Fields

- `command`: gunakan `set_pitch_yaw`
- `pitch_deg`: target pitch akhir
- `yaw_deg`: target yaw akhir
- `pitch_rate_dps`: opsional
- `yaw_rate_dps`: opsional
- `mode`: `follow` atau `lock`
- `gimbal_device_id`: default aman `0`

## Camera Command Messages

### Take picture

```json
{
  "type": "publish",
  "uav_id": 1,
  "kind": "telemetry",
  "metric": "camera_command",
  "payload": {
    "command": "take_photo"
  }
}
```

### Start record

```json
{
  "type": "publish",
  "uav_id": 1,
  "kind": "telemetry",
  "metric": "camera_command",
  "payload": {
    "command": "set_recording",
    "enabled": true
  }
}
```

### Stop record

```json
{
  "type": "publish",
  "uav_id": 1,
  "kind": "telemetry",
  "metric": "camera_command",
  "payload": {
    "command": "set_recording",
    "enabled": false
  }
}
```

### Toggle record

```json
{
  "type": "publish",
  "uav_id": 1,
  "kind": "telemetry",
  "metric": "camera_command",
  "payload": {
    "command": "toggle_recording"
  }
}
```

### Zoom in, zoom out, zoom stop

```json
{
  "type": "publish",
  "uav_id": 1,
  "kind": "telemetry",
  "metric": "camera_command",
  "payload": {
    "command": "zoom_in"
  }
}
```

```json
{
  "type": "publish",
  "uav_id": 1,
  "kind": "telemetry",
  "metric": "camera_command",
  "payload": {
    "command": "zoom_out"
  }
}
```

```json
{
  "type": "publish",
  "uav_id": 1,
  "kind": "telemetry",
  "metric": "camera_command",
  "payload": {
    "command": "zoom_stop"
  }
}
```

### Set absolute zoom level

```json
{
  "type": "publish",
  "uav_id": 1,
  "kind": "telemetry",
  "metric": "camera_command",
  "payload": {
    "command": "set_zoom_level",
    "zoom_level": 3.0
  }
}
```

## Camera UI Rules

Rule untuk panel kamera:

1. Command kamera boleh dikirim segera setelah WebSocket `OPEN`.
2. Command kamera tidak bergantung pada initial target gimbal.
3. `start/stop record` sebaiknya memakai `set_recording` dengan `enabled: true|false`, bukan raw toggle.
4. Tampilkan `camera_state` terakhir di UI agar user tahu status zoom dan recording aktual.

## Recommended Control Model

Frontend model yang benar:

- joystick = input kecepatan
- target yang dikirim = sudut absolut

Jangan kirim:

- raw `dx`
- raw `dy`
- raw `normalizedX`
- raw `normalizedY`

Yang dikirim harus hasil akhirnya:

- `pitch_deg`
- `yaw_deg`

## Recommended Parameters

Gunakan default ini kecuali ada requirement lain:

```js
const maxPitch = 90;
const maxYaw = 180;
const pitchSpeed = 38;
const yawSpeed = 65;
const joystickDeadzone = 0.12;
const sendIntervalMs = 100;
```

## Joystick Math

### Step 1: hitung offset dari pusat joystick

```js
const rect = joystick.getBoundingClientRect();
const radius = rect.width / 2;
const cx = rect.left + rect.width / 2;
const cy = rect.top + rect.height / 2;

let dx = pointerX - cx;
let dy = pointerY - cy;
```

### Step 2: clamp ke radius joystick

```js
const distance = Math.sqrt(dx * dx + dy * dy);

if (distance > radius) {
  dx = (dx / distance) * radius;
  dy = (dy / distance) * radius;
}
```

### Step 3: normalize dan apply deadzone

```js
function applyDeadzone(value, deadzone) {
  if (Math.abs(value) < deadzone) {
    return 0;
  }

  const direction = Math.sign(value);
  const scaled = (Math.abs(value) - deadzone) / (1 - deadzone);
  return direction * scaled;
}

const normalizedX = applyDeadzone(dx / radius, joystickDeadzone);
const normalizedY = applyDeadzone(dy / radius, joystickDeadzone);
```

### Step 4: integrasi ke target sudut

```js
const dt = (now - lastTick) / 1000;

targetYaw = clamp(
  targetYaw + normalizedX * yawSpeed * dt,
  -maxYaw,
  maxYaw
);

targetPitch = clamp(
  targetPitch + -normalizedY * pitchSpeed * dt,
  -maxPitch,
  maxPitch
);
```

Behavior:

- kanan: yaw bertambah
- kiri: yaw berkurang
- atas: pitch bertambah
- bawah: pitch berkurang
- lepas stick: laju jadi `0`, target terakhir tetap

## Publish Rule

Frontend hanya boleh publish jika:

1. WebSocket sudah `OPEN`
2. target sudah initialized

Contoh:

```js
if (ws.readyState === WebSocket.OPEN && targetInitialized) {
  publishCurrentTarget();
}
```

## Manual Input Rule

Kalau ada manual form:

1. user isi pitch/yaw
2. clamp ke batas
3. set `userHasTakenControl = true`
4. set `targetInitialized = true`
5. publish `gimbal_command`

## Center Button Rule

Kalau ada tombol center:

```js
targetPitch = 0;
targetYaw = 0;
targetInitialized = true;
userHasTakenControl = true;
publishCurrentTarget();
```

Center hanya boleh terjadi karena aksi user.

Center tidak boleh otomatis saat initial connect.

## Reconnect Rule

Saat reconnect:

```js
targetInitialized = false;
userHasTakenControl = false;
```

Lalu:

1. subscribe ulang `gimbal_state`
2. tunggu live state lagi
3. pakai state live itu lagi sebagai initial target

## Recommended Frontend State

Minimal state yang harus ada:

```js
const state = {
  websocket: null,
  isConnected: false,
  targetPitch: 0,
  targetYaw: 0,
  targetInitialized: false,
  userHasTakenControl: false,
  normalizedX: 0,
  normalizedY: 0,
  lastTick: 0,
  lastSentAt: 0,
};
```

## Acceptance Criteria

Implementasi dianggap benar jika semua poin ini terpenuhi:

1. Saat baru connect, frontend tidak langsung mengirim `pitch=0 yaw=0`.
2. Frontend menunggu `gimbal_state` lebih dulu.
3. Initial target mengikuti posisi live gimbal.
4. Setelah joystick digerakkan, target berubah mulus berdasarkan `dt`.
5. Frontend mengirim `gimbal_command` dengan format WS yang benar.
6. Saat reconnect, frontend subscribe ulang dan reinitialize target.
7. Tombol center hanya center saat user menekan tombol.
8. Frontend subscribe ulang `camera_state` saat reconnect.
9. Tombol kamera mengirim `camera_command` dengan format WS yang benar.

## Common Mistakes To Avoid

Jangan lakukan ini:

1. set target default ke `0,0` lalu langsung publish
2. kirim raw joystick ke backend
3. publish command sebelum live telemetry didapat
4. overwrite target lokal terus-menerus dari telemetry saat user sedang mengontrol
5. lupa subscribe `gimbal_state`
6. mengirim `take_photo` atau `set_recording` lewat `gimbal_command`

## Minimal Pseudocode

```js
let targetPitch = 0;
let targetYaw = 0;
let targetInitialized = false;
let userHasTakenControl = false;

function onWsOpen() {
  ws.send(JSON.stringify({
    type: "subscribe",
    uav_ids: [uavId],
    metrics: ["gimbal_state", "camera_state"],
  }));
}

function onTelemetryEvent(message) {
  if (message.metric !== "gimbal_state") {
    return;
  }

  const payload = message.payload;

  if (
    payload.connected === true &&
    Number.isFinite(payload.pitch_deg) &&
    Number.isFinite(payload.yaw_deg) &&
    !userHasTakenControl
  ) {
    targetPitch = payload.pitch_deg;
    targetYaw = payload.yaw_deg;
    targetInitialized = true;
  }
}

function onJoystickMove(normalizedX, normalizedY, dt) {
  userHasTakenControl = true;
  targetInitialized = true;

  targetYaw = clamp(targetYaw + normalizedX * yawSpeed * dt, -maxYaw, maxYaw);
  targetPitch = clamp(targetPitch + -normalizedY * pitchSpeed * dt, -maxPitch, maxPitch);
}

function publishCurrentTarget() {
  if (!targetInitialized || ws.readyState !== WebSocket.OPEN) {
    return;
  }

  ws.send(JSON.stringify({
    type: "publish",
    uav_id: uavId,
    kind: "telemetry",
    metric: "gimbal_command",
    payload: {
      command: "set_pitch_yaw",
      pitch_deg: Math.round(targetPitch),
      yaw_deg: Math.round(targetYaw),
      mode: "follow",
      gimbal_device_id: 0,
    },
  }));
}

function sendCameraCommand(payload) {
  if (ws.readyState !== WebSocket.OPEN) {
    return;
  }

  ws.send(JSON.stringify({
    type: "publish",
    uav_id: uavId,
    kind: "telemetry",
    metric: "camera_command",
    payload,
  }));
}
```

## Demo Reference

Kalau agent butuh contoh implementasi nyata di repo ini:

- [index.html](/Users/macbook/Workdir/Office/Projects/drone/service-camera-drone-mission/gimbal-control/index.html)
- [app.js](/Users/macbook/Workdir/Office/Projects/drone/service-camera-drone-mission/gimbal-control/app.js)
- [README.md](/Users/macbook/Workdir/Office/Projects/drone/service-camera-drone-mission/gimbal-control/README.md)
