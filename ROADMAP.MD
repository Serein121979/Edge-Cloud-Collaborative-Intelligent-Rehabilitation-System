
#编译烧录ESP32-S3的步骤
cd C:\Users\18374\OneDrive\Desktop\Edge-Cloud-Collaborative-Intelligent-Rehabilitation-System\firmware\esp32_s3_sensor_bridge
pio run
pio run -t upload --upload-port COM10
python -m serial.tools.miniterm COM10 115200


#摄像头启动命令
python -m edge.run_camera_demo \
  --camera-index 1 \
  --side auto \
  --model-path models/pose_landmarker_full.task \
  --disable-upload \
  --fps 20 \
  --infer-width 640 \
  --report-interval 0.5
