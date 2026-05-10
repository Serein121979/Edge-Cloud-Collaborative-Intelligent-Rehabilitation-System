# Demo Checklist

## 设备检查

- 龙芯板已开机，Python 环境可用。
- 摄像头能被系统识别。
- ESP32-S3 通过 USB 或 Wi-Fi 连接。
- JY61P6 与 sEMG 供电正常。
- 本地云端机器和龙芯板在同一局域网。

## 软件启动

```bash
uvicorn cloud.app.main:app --host 0.0.0.0 --port 8000
python -m edge.run_edge_demo --cloud-url http://<cloud-ip>:8000 --session-id edge_demo
```

## 演示顺序

1. 打开患者端，展示实时动作状态和评分。
2. 做一次标准上肢抬举，观察 `raising -> holding -> lowering -> completed`。
3. 故意弯曲肘关节，展示 `incorrect`。
4. 故意身体大幅代偿，展示 `anomaly`。
5. 打开医生端，展示训练曲线、平均分、异常记录。

## 备份方案

- 若 ESP32 未连接，使用 `edge.run_edge_demo` 模拟传感器。
- 若公网不可用，继续使用局域网本地云端。
- 若摄像头不可用，播放提前录制的数据 JSONL 或使用 synthetic pose。
