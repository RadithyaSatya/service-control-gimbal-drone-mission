# Gimbal Control UI

Frontend statis untuk kontrol gimbal dan kamera via WebSocket.

Dokumentasi implementasi frontend yang lebih lengkap ada di [FE_INTEGRATION.md](/Users/macbook/Workdir/Office/Projects/drone/service-camera-drone-mission/gimbal-control/FE_INTEGRATION.md).

## Cara pakai

1. buka file `index.html` langsung di browser, atau serve folder ini dengan static server
2. isi `Backend Base URL` dan `Device Token`
3. klik `Connect`
4. gerakkan joystick untuk kirim `gimbal_command`
5. gunakan panel camera untuk `take picture`, `start/stop record`, dan `zoom`
6. UI otomatis subscribe `gimbal_state` dan `camera_state`

## Message yang dikirim

UI ini mengirim:

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

UI ini subscribe:

```json
{
  "type": "subscribe",
  "uav_ids": [1],
  "metrics": ["gimbal_state", "camera_state"]
}
```

UI ini juga bisa mengirim command kamera:

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

## Catatan

- UI akan memanggil `POST /auth/ws-token` di background dengan header `X-Device-Token`
- lalu UI akan otomatis connect ke `/ws/telemetry?token=...`
- target awal joystick tidak lagi dipaksa ke `0,0`; UI akan menunggu `gimbal_state` lalu memakai `pitch_deg` dan `yaw_deg` live sebagai initial target
- command baru mulai dipublish setelah target awal sudah diketahui dari telemetry, atau setelah user mengambil alih lewat joystick / manual input / tombol center
- panel camera mengirim `camera_command` terpisah, jadi flow `gimbal_command` lama tidak berubah
- kalau frontend ini dibuka dari origin berbeda, backend harus mengizinkan CORS untuk `POST /auth/ws-token`
