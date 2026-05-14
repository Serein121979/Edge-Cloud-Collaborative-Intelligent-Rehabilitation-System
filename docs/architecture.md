# 系统架构

## 竞赛推荐架构：龙芯主控 + x86 视觉服务

```text
                         Physical Sensor Layer
       +------------------------------------------------------+
       |                                                      |
       |  Camera / Depth Camera              JY61P6 + sEMG    |
       |          |                                  |         |
       +----------|----------------------------------|---------+
                  |                                  |
                  v                                  v
        +-------------------+              +-------------------+
        | x86 Vision Node   |              | ESP32-S3 Bridge   |
        | PC / Laptop       |              | Sensor Collector  |
        |                   |              |                   |
        | MediaPipe Pose    |              | IMU + EMG JSON    |
        | PoseFrame output  |              | SensorFrame JSON  |
        +---------|---------+              +---------|---------+
                  |                                  |
                  | PoseFrame over HTTP/WS           | USB Serial JSON Lines
                  v                                  v
       +------------------------------------------------------+
       | Loongson Edge Controller                             |
       |                                                      |
       | Module A: Preprocessing & Fusion                     |
       | - receive PoseFrame from x86 vision node             |
       | - read SensorFrame from ESP32-S3                     |
       | - align latest camera + sensor frames                |
       |                                                      |
       | Module B: Local Intelligence Engine                  |
       | - rule-based posture recognition                     |
       | - anomaly detection                                 |
       | - score and repetition counting                      |
       |                                                      |
       | Module C: Local Feedback UI                          |
       | - patient feedback                                  |
       | - doctor dashboard                                  |
       | - local JSONL recording                              |
       +--------------------------|---------------------------+
                                  |
                                  | RehabFrame / lightweight logs
                                  v
       +------------------------------------------------------+
       | Local Cloud / Communication Hub                      |
       | - FastAPI receive frames                             |
       | - WebSocket realtime push                            |
       | - session storage                                    |
       | - future Fibocom / 4G upload                         |
       +------------------------------------------------------+
```

这个架构里，龙芯是整个边缘计算控制器，不需要直接运行 MediaPipe。摄像头侧的 MediaPipe 可以放在 x86 PC 上作为视觉服务节点，向龙芯发送已经结构化的 `PoseFrame`。龙芯负责接收视觉结果、读取 ESP32 传感器、做融合、规则判断、本地记录和云端上传。

对评委可以这样解释：视觉节点负责高算力姿态预处理，龙芯主控负责多模态融合、实时判定、边缘控制和通信上传。这符合真实边缘计算系统里“前端感知节点 + 边缘控制器”的分层设计。

## 当前软件闭环

```text
Camera -> MediaPipe -> PoseFrame
ESP32-S3 -> SensorFrame
PoseFrame + SensorFrame -> RehabFusionPipeline -> RehabFrame
RehabFrame -> JSONL recorder + FastAPI cloud + Web UI
```

当前仓库已经实现了这些核心模块：

- 摄像头姿态识别：`edge/rehab_edge/pose.py`
- x86 视觉节点主入口：`edge/run_vision_node.py`
- 龙芯 controller 主入口：`edge/run_controller_node.py`
- 单机备用调试入口：`edge/run_camera_demo.py`
- ESP32-S3 传感器固件：`firmware/esp32_s3_sensor_bridge/src/esp32_s3_sensor_bridge.ino`
- 传感器读取器：`edge/rehab_edge/sensors.py`
- 多模态融合：`edge/rehab_edge/fusion.py`
- 规则判断：`edge/rehab_edge/rules.py`
- 数据协议：`shared/rehab_protocol/models.py`
- 云端 API 与 WebSocket：`cloud/app/main.py`
- 患者端和医生端网页：`web/`

## 数据对象流向

```text
ESP32-S3 JSON
  -> SensorFrame
  -> imu_features / emg_features
  -> RehabFusionPipeline

MediaPipe keypoints
  -> PoseFrame
  -> shoulder_angle / elbow_angle / forearm_angle / trunk_angle
  -> RehabFusionPipeline

PoseFrame + SensorFrame
  -> RehabFrame
  -> local JSONL
  -> HTTP POST /api/frames
  -> WebSocket /ws/realtime/{session_id}
  -> patient.html / doctor.html
```

## 对应论文图里的模块

| 论文模块 | 项目里的落点 | 当前状态 |
|---|---|---|
| Data Acquisition Layer | 摄像头、ESP32-S3、JY61P6、sEMG | 摄像头和 ESP32 JSON 已跑通，JY61P6/sEMG 正在硬件联调 |
| Module A Preprocessing & Fusion | `edge/rehab_edge/fusion.py`、`edge/rehab_edge/sensors.py` | 已有融合骨架 |
| Module B Local Intelligence Engine | `edge/rehab_edge/rules.py`、`edge/rehab_edge/pose.py` | 已实现规则版轻量智能 |
| Module C Local Feedback UI | `web/patient.html`、`web/doctor.html`、`web/app.js` | 已有基础 UI |
| Module D Communication Hub | `edge/rehab_edge/uploader.py`、`cloud/app/main.py` | 已有 HTTP 上传，4G/Fibocom 未实现 |
| Module E High-Precision Inference | 云端重模型 / ST-GCN | 未实现，后期扩展 |
| Module F Medical Decision & Storage | `cloud/app/storage.py`、医生端页面 | 基础存储已实现，医疗决策未实现 |

## 还没接上的关键点

1. JY61P6 当前固件按 CSV 文本协议解析，若传感器实际输出官方二进制协议，需要后续补二进制解析。
2. sEMG 第一版只读取单通道 ADC 与 RMS，明天需要看真实模块输出范围再做标定。
3. Fibocom / 4G 通信、安全上传策略、云端 ST-GCN、LLM 医疗建议都属于后期模块。
4. v1 融合采用“最新视觉帧 + 当前传感器帧”，尚未做严格时间同步。

## 出问题看哪里

| 现象 | 先看文件 |
|---|---|
| 摄像头打不开 | `edge/run_vision_node.py`、`edge/run_camera_demo.py` |
| MediaPipe 模型找不到 | `edge/rehab_edge/pose.py` |
| 肩角、肘角、躯干角不对 | `edge/rehab_edge/pose.py` |
| x86 视觉帧发不到龙芯 | `edge/run_vision_node.py`、`edge/run_controller_node.py` |
| ESP32 串口 JSON 不对 | `firmware/esp32_s3_sensor_bridge/src/esp32_s3_sensor_bridge.ino` |
| Python 读串口失败 | `edge/rehab_edge/sensors.py` |
| 摄像头和传感器融合不对 | `edge/rehab_edge/fusion.py` |
| 动作判断不对 | `edge/rehab_edge/rules.py` |
| 数据格式报错 | `shared/rehab_protocol/models.py` |
| 本地云端收不到数据 | `edge/rehab_edge/uploader.py`、`cloud/app/main.py` |
| 网页没有实时刷新 | `cloud/app/main.py`、`web/app.js` |
| 历史记录找不到 | `cloud/app/storage.py`、`data/sessions/` |

## 稳定性原则

- 比赛现场默认使用局域网本地云端，不依赖公网。
- 算法先规则兜底，再逐步加入轻量模型。
- 传感器缺失时仍保留摄像头姿态演示能力。
- 上传失败时先保存本地 JSONL，后续再补传。
- 龙芯作为 controller，不强依赖本机 MediaPipe；视觉预处理可由 x86 服务节点完成。
