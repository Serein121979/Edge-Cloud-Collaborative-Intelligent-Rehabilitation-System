# API and Data Contracts

## ESP32 Sensor Frame

ESP32-S3 每行输出一个 JSON 对象：

```json
{
  "timestamp_ms": 0,
  "device": "esp32_s3",
  "imu": {
    "roll": 0,
    "pitch": 0,
    "yaw": 0,
    "acc": [0, 0, 0],
    "gyro": [0, 0, 0]
  },
  "emg": {
    "channels": [0],
    "rms": [0]
  }
}
```

## Controller Pose API

x86 视觉节点把 MediaPipe 结果发送给龙芯 controller：

- `POST /api/pose`

请求体使用 `PoseFrame.to_dict()`：

```json
{
  "shoulder_angle": 90,
  "elbow_angle": 170,
  "forearm_angle": 80,
  "trunk_angle": 3,
  "landmarks_2d": []
}
```

返回：

```json
{
  "ok": true
}
```

controller 会保存最新一帧 `PoseFrame`。每次串口读到新的 `SensorFrame`，就用“最新视觉帧 + 当前传感器帧”生成 `RehabFrame`。

## RehabFrame

龙芯端上传到云端的数据：

```json
{
  "session_id": "edge_20260510T000000Z_12345678",
  "timestamp_ms": 0,
  "pose": {
    "shoulder_angle": 0,
    "elbow_angle": 180,
    "forearm_angle": 0,
    "trunk_angle": 0,
    "landmarks_2d": []
  },
  "imu_features": {
    "roll": 0,
    "pitch": 0,
    "yaw": 0,
    "repetitions": 0
  },
  "emg_features": {
    "rms_mean": 0,
    "rms_max": 0,
    "peak": 0
  },
  "state": "idle",
  "score": 0,
  "anomalies": []
}
```

合法状态：

`idle`、`raising`、`holding`、`lowering`、`completed`、`incorrect`、`anomaly`

## Cloud API

- `POST /api/sessions`
  - 输入：`session_id` 可选，`participant` 可选，`scenario` 可选。
  - 输出：创建后的 session。
- `POST /api/frames`
  - 输入：`RehabFrame`。
  - 输出：`ok` 与当前帧数。
- `GET /api/sessions/{session_id}/summary`
  - 输出：帧数、时长、状态计数、异常计数、平均分、完成次数、最新帧。
- `GET /api/sessions/{session_id}/frames?limit=120`
  - 输出：最近若干帧。
- `WS /ws/realtime/{session_id}`
  - 首次发送 summary。
  - 新帧到达时发送 `{ "type": "frame", "payload": RehabFrame }`。
