# Demo Checklist

## 设备检查

- 龙芯板已开机，Python 环境可用。
- x86 PC 摄像头能被系统识别。
- ESP32-S3 通过 USB 串口连接龙芯 controller。
- JY61P6 与 sEMG 供电正常。
- 本地云端机器、x86 视觉节点、龙芯板在同一局域网。

## 软件启动

```bash
uvicorn cloud.app.main:app --host 0.0.0.0 --port 8000

python -m edge.run_controller_node \
  --serial-port /dev/ttyUSB1 \
  --serial-baud 115200 \
  --cloud-url http://<cloud-ip>:8000 \
  --listen-host 0.0.0.0 \
  --listen-port 9001

python -m edge.run_vision_node \
  --camera-index 1 \
  --side auto \
  --model-path models/pose_landmarker_full.task \
  --controller-url http://<loongson-ip>:9001
```

## 演示顺序

1. 打开患者端，展示实时动作状态和评分。
2. 做一次标准上肢抬举，观察 `raising -> holding -> lowering -> completed`。
3. 故意弯曲肘关节，展示 `incorrect`。
4. 故意身体大幅代偿，展示 `anomaly`。
5. 打开医生端，展示训练曲线、平均分、异常记录。

## 备份方案

- 若 ESP32 未连接，controller 加 `--simulate-sensors`。
- 若龙芯未到，controller 可先在 x86 PC 上运行，明天再把命令搬到龙芯。
- 若公网不可用，继续使用局域网本地云端。
- 若摄像头不可用，先用 `edge.run_camera_demo --no-preview --frames 100` 做单机调试。
