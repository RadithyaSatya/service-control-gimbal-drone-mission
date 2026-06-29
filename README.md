# siyi_sdk (Legacy)

> [!IMPORTANT]
> **A newer, async-native version of this SDK is available in the [`siyi-sdk-v2`](https://github.com/mzahana/siyi_sdk/tree/siyi-sdk-v2) branch.**
> It is recommended to use the new version for better performance, type safety, and modern asyncio support.

Python implementation of the SDK of SIYI camera-gimbal systems.

* [Camera-gimbal products](https://shop.siyi.biz/collections/gimbal-camera-optical-pod)
* Documentation: [A8 mini](https://siyi.biz/siyi_file/A8%20mini/A8%20mini%20User%20Manual%20v1.6.pdf)

**If you find this code useful, kindly give a STAR to this repository. Thanks!**

# Components
This repo now contains three related parts:

* Core SIYI Python SDK in `siyi_sdk.py`
* WebSocket bridge service in `gimbal_ws_bridge.py`
* Static frontend for gimbal and camera control in `gimbal-control/`

# Setup
* Clone this package
    ```bash
    git clone https://github.com/mzahana/siyi_sdk.git
    ```
* Connect the camera to PC or onboard computer using the ethernet cable that comes with it. The current implementation uses UDP communication.
* Power on the camera
* Do the PC wired network configuration. Make sure to assign a manual IP address to your computer
  * For example, IP `192.168.144.12`
  * Gateway `192.168.144.25`
  * Netmask `255.255.255.0`
* Done. 

# Usage
* Check the scripts in the `siyi_sdk/tests` directory to learn how to use the SDK

* To import this module in your code, copy the `siyi_sdk.py` `siyi_message.py` `utils.py` `crc16_python.py` `cameras.py` scripts in your code directory, and import as follows, and then follow the test examples
    ```python
    from siyi_sdk import SIYISDK
    ```
* Example: To run the `test_gimbal_rotation.py` run,
    ```bash
    cd siyi_sdk/tests
    python3 test_gimbal_rotation.py
  
    ```

* Use gui

    ```bash
    python3 gui/tkgui.py
    ```

    <video src="gui/demo.mp4" controls title="Demo"></video>
    
    <img src="gui/gui_tkinter.png" width=200> </img>

# WebSocket Bridge
`gimbal_ws_bridge.py` bridges backend realtime WebSocket with:

* MAVLink gimbal control for pitch/yaw rotation
* SIYI SDK camera control for photo, recording, and zoom

Flow:

1. service requests WS token from backend using `X-Device-Token`
2. service connects to `GET /ws/telemetry?token=<WS_TOKEN>`
3. service subscribes to `gimbal_command` and optionally `camera_command`
4. service reads `GIMBAL_DEVICE_ATTITUDE_STATUS` from MAVLink UDP
5. service publishes `gimbal_state`
6. service translates `camera_command` to SIYI SDK calls and publishes `camera_state`

Post-landing media flow:

1. download media from camera SD card to local storage
2. format camera SD card after local download finishes
3. if format succeeds, continue with delivery mode:
4. `local_only`: stop after local copy + format
5. `upload`: upload downloaded files from local storage to backend
6. `register_move`: move downloaded files to register root, then call backend register endpoint

## Run The Bridge

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 gimbal_ws_bridge.py
```

## Environment
The bridge loads `.env` automatically. Default values are already provided in the root `.env`.

Important variables:

```bash
API_BASE_URL=http://127.0.0.1:8000
DEVICE_TOKEN=uav-local-dev-token
UAV_ID=1

MAVLINK_ENDPOINT=udpin:0.0.0.0:14551
MAVLINK_SOURCE_SYSTEM=250
MAVLINK_SOURCE_COMPONENT=191
MAVLINK_GIMBAL_SYSTEM=1
MAVLINK_GIMBAL_COMPONENT=1
MAVLINK_GIMBAL_DEVICE_ID=0

SIYI_ENABLED=true
SIYI_IP=192.168.144.25
SIYI_PORT=37260

GIMBAL_COMMAND_METRIC=gimbal_command
GIMBAL_STATE_METRIC=gimbal_state
CAMERA_COMMAND_METRIC=camera_command
CAMERA_STATE_METRIC=camera_state
MISSION_EVENT_CAMERA_ACTION_ETA_OFFSET_SECONDS=0
```

Notes:

* `MAVLINK_ENDPOINT` is the UDP stream the bridge listens to for gimbal telemetry.
* `MAVLINK_SOURCE_*` is the sender identity used by this bridge when transmitting MAVLink commands.
* `MAVLINK_GIMBAL_*` is the target identity used for `MAV_CMD_DO_GIMBAL_MANAGER_PITCHYAW`.
* `SIYI_ENABLED=true` enables camera control through the SIYI SDK.
* `MISSION_EVENT_CAMERA_ACTION_ETA_OFFSET_SECONDS` can be used to fire mission camera actions slightly earlier than ETA, to compensate command latency.
* `MISSION_SNAPSHOT_REFRESH_INTERVAL_SECONDS` controls how often the bridge refreshes the active mission snapshot from backend when waypoint runtime data is needed.

Mission camera actions:

* The bridge reads waypoint actions from the active mission snapshot returned by `GET /missions/safe-to-fly/device`.
* Runtime prediction uses official realtime metrics: `mission_progress.current_waypoint`, `location.latitude/longitude/ground_speed`, and `vehicle_state.flight_speed`.
* `take picture` and `record video` are scheduled from ETA computed as `distance_to_waypoint / speed`, not from a custom `waypoint_reached` event payload.

## Realtime Metrics

Gimbal path:

* `gimbal_command`
* `gimbal_state`

Camera path:

* `camera_command`
* `camera_state`

References:

* `WEBSOCKET_CONTRACT.md`
* `gimbal-ws-contract.md`

# Gimbal Control Frontend
`gimbal-control/` is a static frontend for:

* gimbal pitch/yaw control via `gimbal_command`
* camera actions via `camera_command`
* live state display from `gimbal_state` and `camera_state`

## Run The Frontend

1. Open `gimbal-control/index.html` directly in the browser, or serve the folder using a static server
2. Fill `Backend Base URL` and `Device Token`
3. Click `Connect`
4. Use the joystick for gimbal rotation
5. Use the camera panel for `take picture`, `start/stop record`, `toggle record`, and `zoom`

## Frontend Messages

Gimbal command:

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

Camera command:

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

Subscribe:

```json
{
  "type": "subscribe",
  "uav_ids": [1],
  "metrics": ["gimbal_state", "camera_state"]
}
```

## Camera Commands Supported

* `take_photo`
* `toggle_recording`
* `set_recording` with `enabled: true|false`
* `zoom_in`
* `zoom_out`
* `zoom_stop`
* `set_zoom_level` with `zoom_level`

## Frontend Notes

* The joystick flow still uses only `gimbal_command`; camera actions do not change the existing rotation contract.
* Initial target is taken from live `gimbal_state`, not forced to `0,0` on connect.
* For fuller frontend guidance, see `gimbal-control/FE_INTEGRATION.md`.

# Video Streaming
## Requirements
* OpenCV `sudo apt-get install python3-opencv -y`
* imutils `pip install imutils`
* Gstreamer `https://gstreamer.freedesktop.org/documentation/installing/index.html?gi-language=c`
    
    Ubuntu:
    ```bash
    sudo apt-get install libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev libgstreamer-plugins-bad1.0-dev gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav gstreamer1.0-tools gstreamer1.0-x gstreamer1.0-alsa gstreamer1.0-gl gstreamer1.0-gtk3 gstreamer1.0-qt5 gstreamer1.0-pulseaudio -y
    ```
- Deepstream (only for Nvidia Jetson boards)
    (https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_Quickstart.html#jetson-setup)
- For RTMP streaming
    ```bash
    sudo apt install ffmpeg -y
    pip install ffmpeg-python
    ```

## Examples
* An example of how to receive image frames from camera, see `tests/test_rtsp.py`
* An example of how to stream image frames to an RTMP server, see `tests/test_rtmp_stream.py`
* An example of how to receive an image stream from camera using RTSP and send them to an RTMP server, see `tests/test_from_rtsp_to_rtmp.py`
* C++ application that uses GStreamer to recieve RTSP stream in the camera is available in the `src` directory.
    It can be compiled using
    ```bash
     g++ rtsp_gstreamer.cpp -o rtsp_gstreamer `pkg-config --cflags --libs opencv4 gstreamer-1.0 gstreamer-app-1.0`
    ```
    Then, you can run it using `./rtsp_gstreamer RTSP_URL`

# Tools
* To run a nginx-rtmp server from a docker container 
```bash
docker run -d -p 1935:1935 --name nginx-rtmp tiangolo/nginx-rtmp
```
[Reference](https://hub.docker.com/r/tiangolo/nginx-rtmp/)

* To play an rtmp stream, you can use the following command in a terminal (you will need to install mpv `sudo apt install mpv`)
```bash
mpv   --msg-color=yes   --msg-module=yes   --keepaspect=yes   --no-correct-pts   --untimed   --vd-lavc-threads=1   --cache=no   --cache-pause=no   --demuxer-lavf-o-add="fflags=+nobuffer+fastseek+flush_packets"   --demuxer-lavf-probe-info=nostreams   --demuxer-lavf-analyzeduration=0.1   --demuxer-max-bytes=500MiB   --demuxer-readahead-secs=0.1     --interpolation=no   --hr-seek-framedrop=no   --video-sync=display-resample   --temporal-dither=yes   --framedrop=decoder+vo     --deband=no   --dither=no     --hwdec=auto-copy   --hwdec-codecs=all     --video-latency-hacks=yes   --profile=low-latency   --linear-downscaling=no   --correct-downscaling=yes   --sigmoid-upscaling=yes   --scale=ewa_hanning   --scale-radius=3.2383154841662362   --cscale=ewa_lanczossoft   --dscale=mitchell     --fs   --osc=no   --osd-duration=450   --border=no   --no-pause   --no-resume-playback   --keep-open=no   --network-timeout=0 --stream-lavf-o=reconnect_streamed=1   rtmp://127.0.0.1/live/webcam
```
**OR you can use VLC, but you may notice high latency!**
