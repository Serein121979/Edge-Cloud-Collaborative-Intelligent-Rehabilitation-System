
#编译烧录ESP32-S3的步骤
cd C:\Users\18374\OneDrive\Desktop\Edge-Cloud-Collaborative-Intelligent-Rehabilitation-System\firmware\esp32_s3_sensor_bridge
pio run
pio run -t upload --upload-port COM10
python -m serial.tools.miniterm COM10 115200


# 摄像头启动命令

注意：摄像头 + MediaPipe 要进入 `rehab311` 隔离环境，并且必须在项目根目录运行。
如果当前在 `firmware/esp32_s3_sensor_bridge` 目录里，直接运行会报：
`ModuleNotFoundError: No module named 'edge'`。

```bash
conda activate rehab311
cd ~/桌面/Edge-Cloud-Collaborative-Intelligent-Rehabilitation-System

python -c "import cv2, mediapipe; print('camera env ok')"

python -m edge.run_camera_demo \
  --camera-index 1 \
  --side auto \
  --model-path models/pose_landmarker_full.task \
  --disable-upload \
  --fps 20 \
  --infer-width 640 \
  --report-interval 0.5
```

如果摄像头打不开，把 `--camera-index 1` 改成 `--camera-index 0` 再试。
