# Gimbal WS Contract

Dokumen ini menambahkan metric realtime untuk gimbal dengan tetap mengikuti envelope pada [telemetry-payloads.md](/Users/macbook/Workdir/Office/Projects/drone/service-camera-drone-mission/telemetry-payloads.md) dan rule subscribe/publish pada [WEBSOCKET_CONTRACT.md](/Users/macbook/Workdir/Office/Projects/drone/service-camera-drone-mission/WEBSOCKET_CONTRACT.md).

## Metric Baru

- `gimbal_state`: telemetry posisi/status gimbal yang dipublish bridge service
- `gimbal_command`: command WS yang diterima bridge service lalu diterjemahkan menjadi `MAV_CMD_DO_GIMBAL_MANAGER_PITCHYAW`
- `camera_state`: telemetry status kamera SIYI yang dipublish bridge service
- `camera_command`: command WS yang diterima bridge service lalu diterjemahkan menjadi call SDK SIYI

## Subscribe

Client yang ingin menerima posisi gimbal subscribe seperti ini:

```json
{
  "type": "subscribe",
  "uav_ids": [1],
  "metrics": ["gimbal_state"]
}
```

Bridge service sendiri subscribe ke command:

```json
{
  "type": "subscribe",
  "uav_ids": [1],
  "metrics": ["gimbal_command", "camera_command"]
}
```

## Publish Telemetry `gimbal_state`

Format outer message mengikuti kontrak telemetry:

```json
{
  "type": "publish",
  "uav_id": 1,
  "kind": "telemetry",
  "metric": "gimbal_state",
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

Format event yang diterima subscriber dari server tetap:

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

Arti field:

- `connected`: `true` bila `GIMBAL_DEVICE_ATTITUDE_STATUS` masih diterima dalam timeout service
- `gimbal_device_id`: source MAVLink component dari status gimbal yang diterima
- `frame`: `vehicle` atau `earth`, diturunkan dari flag yaw frame MAVLink
- `roll_deg`, `pitch_deg`, `yaw_deg`: hasil konversi quaternion status gimbal ke derajat
- `*_rate_dps`: kecepatan sudut derajat per detik
- `flags`: raw `GIMBAL_DEVICE_ATTITUDE_STATUS.flags`
- `failure_flags`: raw `GIMBAL_DEVICE_ATTITUDE_STATUS.failure_flags`
- `time_boot_ms`: timestamp boot dari message MAVLink

Jika gimbal timeout, bridge akan publish minimal:

```json
{
  "type": "publish",
  "uav_id": 1,
  "kind": "telemetry",
  "metric": "gimbal_state",
  "payload": {
    "connected": false
  }
}
```

## Publish Command `gimbal_command`

Ini format message yang bisa dikirim oleh service/controller lain ke hub WS:

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

Arti field:

- `command`: saat ini hanya `set_pitch_yaw`
- `pitch_deg`: target pitch derajat
- `yaw_deg`: target yaw derajat
- `pitch_rate_dps`: opsional, target pitch rate derajat/detik
- `yaw_rate_dps`: opsional, target yaw rate derajat/detik
- `mode`: `follow` atau `lock`
- `gimbal_device_id`: opsional, default `0` untuk semua gimbal pada manager target

Mapping ke MAVLink:

- `pitch_deg` -> `param1` `MAV_CMD_DO_GIMBAL_MANAGER_PITCHYAW`
- `yaw_deg` -> `param2`
- `pitch_rate_dps` -> `param3`
- `yaw_rate_dps` -> `param4`
- `mode=follow` -> `GIMBAL_MANAGER_FLAGS_YAW_IN_VEHICLE_FRAME`
- `mode=lock` -> `GIMBAL_MANAGER_FLAGS_YAW_LOCK`
- `gimbal_device_id` -> `param7`

## Rekomendasi Format Untuk Joystick

Karena [GIMBAL_ONLY.md](/Users/macbook/Workdir/Office/Projects/drone/service-camera-drone-mission/GIMBAL_ONLY.md) sudah menghitung sudut absolut di frontend, format yang paling aman adalah tetap mengirim target akhir `pitch_deg` dan `yaw_deg`, bukan nilai joystick mentah:

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
    "mode": "follow"
  }
}
```

Kalau nanti mau stream lebih rapat dari command low-rate ini, jalur MAVLink-nya sebaiknya dinaikkan ke `GIMBAL_MANAGER_SET_PITCHYAW`, tapi untuk flow yang dijelaskan di dokumen lokal saat ini `MAV_CMD_DO_GIMBAL_MANAGER_PITCHYAW` tetap paling konsisten.

## Publish Telemetry `camera_state`

Format outer message:

```json
{
  "type": "publish",
  "uav_id": 1,
  "kind": "telemetry",
  "metric": "camera_state",
  "payload": {
    "connected": true,
    "recording_state": 1,
    "recording_label": "on",
    "zoom_level": 3.0,
    "camera_type": "A8 mini"
  }
}
```

Field utama:

- `connected`: status koneksi bridge ke kamera SIYI
- `recording_state`: raw state dari SDK
- `recording_label`: label human-readable
- `zoom_level`: current zoom level hasil poll ke kamera
- `camera_type`: tipe kamera dari hardware info SDK

## Publish Command `camera_command`

Format message:

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

Command yang didukung:

- `take_photo`
- `toggle_recording`
- `set_recording` dengan field `enabled: true|false`
- `zoom_in`
- `zoom_out`
- `zoom_stop`
- `set_zoom_level` dengan field `zoom_level`
