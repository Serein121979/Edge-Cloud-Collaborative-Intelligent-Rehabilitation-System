# Edge-Cloud Collaborative Intelligent Rehabilitation System

面向嵌入式大赛的边云协同智能康复系统第一版骨架。当前目标是建立可运行、可扩展、可演示的双节点闭环：

- x86 视觉节点：RGB 摄像头 + MediaPipe，生成 `PoseFrame` 并发送给龙芯 controller。
- 龙芯 controller：接收 `PoseFrame`，读取 ESP32-S3 串口，融合、规则判定、数据记录、上传。
- ESP32-S3：汇聚 JY61P6 IMU 与 sEMG，输出统一 JSON Lines。
- 本地云端：FastAPI 接收训练帧、保存会话、WebSocket 推送实时数据。
- Web 展示：患者实时反馈页、医生端训练仪表盘。

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 启动本地云端和网页
uvicorn cloud.app.main:app --reload --host 0.0.0.0 --port 8000

# 另开一个终端，先用模拟传感器运行 controller
python -m edge.run_controller_node \
  --simulate-sensors \
  --cloud-url http://127.0.0.1:8000 \
  --listen-port 9001
```

打开：

- 患者端：`http://127.0.0.1:8000/patient`
- 医生端：`http://127.0.0.1:8000/doctor`
- API 文档：`http://127.0.0.1:8000/docs`

如果要运行 x86 摄像头视觉节点，请使用 Python 3.10/3.11 环境额外安装：

```bash
pip install -r requirements-vision.txt
```

部分较新的 Linux `mediapipe` 安装包只提供 Tasks API，不再暴露 `mp.solutions.pose`。
如果你遇到 `module 'mediapipe' has no attribute 'solutions'`，请下载官方
`pose_landmarker_full.task` 模型文件，放到项目根目录下的 `models/` 目录，
或在运行时通过 `--model-path` 指定。

```bash
python -m edge.run_vision_node \
  --camera-index 0 \
  --side auto \
  --controller-url http://127.0.0.1:9001 \
  --model-path models/pose_landmarker_full.task
```

龙芯板到货后，controller 命令换成真实串口即可：

```bash
python -m edge.run_controller_node \
  --serial-port /dev/ttyUSB1 \
  --serial-baud 115200 \
  --cloud-url http://127.0.0.1:8000 \
  --listen-host 0.0.0.0 \
  --listen-port 9001
```

单机备用调试仍然保留：

```bash
python -m edge.run_camera_demo \
  --camera-index 0 \
  --side auto \
  --model-path models/pose_landmarker_full.task \
  --serial-port /dev/ttyUSB1
```

## Repository Layout

```text
edge/      x86 视觉节点、龙芯 controller、融合、规则识别、上传
cloud/     本地云端模拟：API、WebSocket、会话存储
web/       患者端和医生端静态页面
firmware/  ESP32-S3 传感器桥接固件草稿
shared/    边缘端和云端共用数据协议
docs/      架构、接口、周计划、演示 checklist
tests/     纯 Python 单元测试
```

## Current Milestone

当前可运行目标：

1. 共享数据协议稳定。
2. x86 视觉节点生成 `PoseFrame`。
3. 龙芯 controller 接收视觉帧，读取真实或模拟 ESP32 传感器帧。
4. 融合流水线输出 `RehabFrame`，写本地 JSONL 并上传云端。
5. 网页能展示实时角度、动作阶段、次数和趋势。

## Tests

```bash
python -m unittest discover -s tests
```

这些测试不依赖摄像头或 MediaPipe，适合在龙芯板上先验证 controller 基础逻辑。
