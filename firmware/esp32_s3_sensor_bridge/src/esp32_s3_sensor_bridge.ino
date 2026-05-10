/**
 * ESP32-S3 开发板通断性验证固件。
 *
 * 功能：纯板级测试，不依赖任何外部传感器连接。
 *       定期（20ms 间隔）通过 USB 串口输出 JSON 格式的帧计数，
 *       用于验证 USB 串口通信、开发板供电和烧录链路的正常性。
 *
 * 使用场景：硬件焊接完成后、连接 IMU/EMG 之前，先烧录此固件，
 *           通过串口助手观察是否持续输出 JSON，确认板子正常工作。
 *
 * 输出格式：每 20ms 输出一行 JSON，包含时间戳和递增帧号。
 *           龙芯边缘端 Python 端用 json.loads 即可解析。
 */

// 采样间隔 20ms，对应约 50Hz 输出频率。
const int SAMPLE_INTERVAL_MS = 20;
unsigned long lastSample = 0;

// 累加帧计数器，每次 loop 输出后自增。
unsigned long frameCount = 0;

void setup() {
  // 初始化 USB 串口，波特率 115200。
  Serial.begin(115200);
}

void loop() {
  // 固定采样周期，避免串口输出过快。
  unsigned long now = millis();
  if (now - lastSample < SAMPLE_INTERVAL_MS) {
    return;
  }
  lastSample = now;
  frameCount++;

  // 手动拼接 JSON，避免引入额外库。
  Serial.print("{\"timestamp_ms\":");
  Serial.print(now);
  Serial.print(",\"device\":\"esp32_s3\",\"mode\":\"board_sanity\",\"frame\":");
  Serial.print(frameCount);
  Serial.println("}");
}