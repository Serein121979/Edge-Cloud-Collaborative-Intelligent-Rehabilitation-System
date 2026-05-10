# 系统架构

## 第一版闭环

```text
ESP32-S3 + JY61P6 + sEMG
        |
        | JSON Lines over USB serial / Wi-Fi
        v
Loongson Edge Node
  - RGB Camera + MediaPipe Pose
  - Sensor preprocessing
  - Shoulder/elbow angle calculation
  - Rule-based state recognition
  - Local JSONL recording
        |
        | HTTP POST / WebSocket
        v
Local Cloud Simulator
  - Session storage
  - Doctor dashboard
  - Patient feedback page
```

## 数据流

1. ESP32-S3 周期采样 IMU 与 sEMG。
2. 龙芯端读取传感器 JSON Lines，同时处理 RGB 摄像头姿态关键点。
3. 融合模块生成 `RehabFrame`。
4. 规则引擎输出动作状态、评分与异常标签。
5. 龙芯端本地记录完整帧，并上传轻量日志到本地云端。
6. 本地云端保存会话并通过 WebSocket 推送给患者端和医生端。

## 稳定性原则

- 比赛现场默认使用局域网本地云端，不依赖公网。
- 算法先规则兜底，再逐步加入轻量模型。
- 传感器缺失时仍保留摄像头姿态演示能力。
- 上传失败时先保存本地 JSONL，后续再补传。
