
#编译烧录ESP32-S3的步骤
cd C:\Users\18374\OneDrive\Desktop\Edge-Cloud-Collaborative-Intelligent-Rehabilitation-System\firmware\esp32_s3_sensor_bridge
pio run
pio run -t upload --upload-port COM10
python -m serial.tools.miniterm COM10 115200

