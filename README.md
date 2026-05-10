# Edge-Cloud Collaborative Intelligent Rehabilitation System

面向嵌入式大赛的边云协同智能康复系统第一版骨架。当前目标不是一次性做成最终作品，而是先建立可运行、可扩展、可演示的最小闭环：

- 龙芯边缘端：RGB 摄像头姿态识别、ESP32-S3 传感器接入、规则判定、数据记录、上传。
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

# 另开一个终端，运行边缘端模拟数据闭环
python -m edge.run_edge_demo --cloud-url http://127.0.0.1:8000 --frames 300
```

打开：

- 患者端：`http://127.0.0.1:8000/patient`
- 医生端：`http://127.0.0.1:8000/doctor`
- API 文档：`http://127.0.0.1:8000/docs`

如果要运行真实摄像头 + MediaPipe 姿态识别，请使用 Python 3.10/3.11 环境额外安装：

```bash
pip install -r requirements-vision.txt
```

当前模拟闭环不依赖 MediaPipe，所以可以先在 Python 3.13 上跑通云端、网页和规则引擎。

## Repository Layout

```text
edge/      龙芯边缘端：采集、姿态、融合、规则识别、上传
cloud/     本地云端模拟：API、WebSocket、会话存储
web/       患者端和医生端静态页面
firmware/  ESP32-S3 传感器桥接固件草稿
shared/    边缘端和云端共用数据协议
docs/      架构、接口、周计划、演示 checklist
tests/     纯 Python 单元测试
```

## Current Milestone

Week 1 的可运行目标：

1. 共享数据协议稳定。
2. 边缘端可以生成模拟 IMU/sEMG + 模拟姿态帧。
3. 规则引擎可以输出 `idle`、`raising`、`holding`、`lowering`、`completed`、`incorrect`、`anomaly`。
4. 本地云端可以创建会话、接收帧、生成 summary、推送 WebSocket。
5. 两个网页能展示实时角度、动作阶段、次数和趋势。

## Tests

```bash
python -m unittest discover -s tests
```

这些测试不依赖摄像头、MediaPipe 或 FastAPI，适合在龙芯板上先验证基础逻辑。
