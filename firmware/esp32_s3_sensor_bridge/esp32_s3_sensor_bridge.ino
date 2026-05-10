// ESP32-S3 传感器桥接固件。
// 功能：读取 JY61P6 IMU 和 sEMG 模拟量，并输出给龙芯边缘端。
// 输出格式：每个采样周期输出一行 JSON，便于 Python 串口端直接解析。

const int EMG_PIN = 1;
// 20 ms 对应约 50 Hz，第一版足够支撑动作训练演示。
const int SAMPLE_INTERVAL_MS = 20;
const int RMS_WINDOW = 32;

float emgWindow[RMS_WINDOW];
int emgIndex = 0;
unsigned long lastSample = 0;

struct ImuValues {
  // 统一保存 IMU 姿态角、加速度和角速度。
  float roll;
  float pitch;
  float yaw;
  float acc[3];
  float gyro[3];
};

void setup() {
  // Serial 连接龙芯板，Serial1 预留给 JY61P6。
  Serial.begin(115200);
  Serial1.begin(115200, SERIAL_8N1, 18, 17);
  analogReadResolution(12);
  for (int i = 0; i < RMS_WINDOW; i++) {
    emgWindow[i] = 0;
  }
}

void loop() {
  // 固定采样周期，避免串口输出过快影响边缘端解析。
  unsigned long now = millis();
  if (now - lastSample < SAMPLE_INTERVAL_MS) {
    return;
  }
  lastSample = now;

  // sEMG 第一版先读取单通道 ADC，并计算滑动窗口 RMS。
  float emgRaw = analogRead(EMG_PIN);
  emgWindow[emgIndex] = emgRaw;
  emgIndex = (emgIndex + 1) % RMS_WINDOW;

  ImuValues imu = readImu();
  float rms = emgRms();

  // 手动拼 JSON 可以避免 Arduino 端引入额外库，便于快速烧录测试。
  Serial.print("{\"timestamp_ms\":");
  Serial.print(now);
  Serial.print(",\"device\":\"esp32_s3\",\"imu\":{\"roll\":");
  Serial.print(imu.roll, 3);
  Serial.print(",\"pitch\":");
  Serial.print(imu.pitch, 3);
  Serial.print(",\"yaw\":");
  Serial.print(imu.yaw, 3);
  Serial.print(",\"acc\":[");
  printTriple(imu.acc);
  Serial.print("],\"gyro\":[");
  printTriple(imu.gyro);
  Serial.print("]},\"emg\":{\"channels\":[");
  Serial.print(emgRaw, 3);
  Serial.print("],\"rms\":[");
  Serial.print(rms, 3);
  Serial.println("]}}");
}

ImuValues readImu() {
  // 默认值保证 IMU 暂时没接好时，JSON 仍然结构完整。
  ImuValues imu;
  imu.roll = 0;
  imu.pitch = 0;
  imu.yaw = 0;
  imu.acc[0] = 0;
  imu.acc[1] = 0;
  imu.acc[2] = 9.8;
  imu.gyro[0] = 0;
  imu.gyro[1] = 0;
  imu.gyro[2] = 0;

  // 第一阶段硬件联调用简单 CSV：
  // roll,pitch,yaw,ax,ay,az,gx,gy,gz\n
  // 等 JY61P6 在台架上确认稳定后，再替换成官方二进制协议解析。
  if (Serial1.available()) {
    String line = Serial1.readStringUntil('\n');
    float values[9];
    int parsed = parseCsv9(line, values);
    if (parsed == 9) {
      imu.roll = values[0];
      imu.pitch = values[1];
      imu.yaw = values[2];
      imu.acc[0] = values[3];
      imu.acc[1] = values[4];
      imu.acc[2] = values[5];
      imu.gyro[0] = values[6];
      imu.gyro[1] = values[7];
      imu.gyro[2] = values[8];
    }
  }
  return imu;
}

float emgRms() {
  // 均方根能反映肌肉激活强度，比瞬时 ADC 值更稳定。
  float sumSquares = 0;
  for (int i = 0; i < RMS_WINDOW; i++) {
    sumSquares += emgWindow[i] * emgWindow[i];
  }
  return sqrt(sumSquares / RMS_WINDOW);
}

void printTriple(float values[3]) {
  // 打印长度为 3 的数组，减少 JSON 拼接重复代码。
  Serial.print(values[0], 3);
  Serial.print(",");
  Serial.print(values[1], 3);
  Serial.print(",");
  Serial.print(values[2], 3);
}

int parseCsv9(String line, float values[9]) {
  // 解析 9 个逗号分隔浮点数；解析失败时返回已解析数量。
  int start = 0;
  int count = 0;
  line.trim();
  while (count < 9) {
    int comma = line.indexOf(',', start);
    String token = comma >= 0 ? line.substring(start, comma) : line.substring(start);
    token.trim();
    if (token.length() == 0) {
      return count;
    }
    values[count++] = token.toFloat();
    if (comma < 0) {
      break;
    }
    start = comma + 1;
  }
  return count;
}
