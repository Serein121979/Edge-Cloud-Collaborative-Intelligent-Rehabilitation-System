/**
 * ESP32-S3 传感器桥接固件。
 *
 * 功能：读取 JY61P6 IMU（六轴姿态传感器）和 sEMG（表面肌电）模拟量，
 *       并通过串口输出 JSON 格式数据给龙芯边缘端。
 *       龙芯边缘端通过串口接收这些数据，处理后上传云端。
 *
 * 通信架构：
 *   JY61P6 (UART)  →  ESP32-S3 (主控)  →  龙芯边缘端 (Serial)
 *
 * 输出格式：每个采样周期（20ms，约 50Hz）输出一行 JSON，
 *           包含时间戳、IMU 姿态/加速度/角速度、肌电原始值和 RMS。
 *
 * 硬件连接：
 *   - EMG 模拟信号 → GPIO 1 (ADC)
 *   - JY61P6 TX → GPIO 18 (Serial1 RX)
 *   - JY61P6 RX → GPIO 17 (Serial1 TX)
 *   - ESP32-S3 Serial → 龙芯边缘端串口 (115200 baud)
 */

// 肌电传感器模拟输入引脚。
const int EMG_PIN = 1;

// 20 ms 对应约 50 Hz，第一版足够支撑动作训练演示。
const int SAMPLE_INTERVAL_MS = 20;

// RMS 滑动窗口大小：32 个样本约 0.64 秒（@ 50Hz），能稳定反映肌肉激活水平。
const int RMS_WINDOW = 32;

// 肌电采样滑动窗口缓冲区。
float emgWindow[RMS_WINDOW];
int emgIndex = 0;
unsigned long lastSample = 0;

/**
 * IMU 数据结构体，统一保存姿态角和运动数据。
 * 包含：欧拉角（roll/pitch/yaw）、三轴加速度和三轴角速度。
 */
struct ImuValues {
  // 统一保存 IMU 姿态角、加速度和角速度。
  float roll;      // 横滚角（度）
  float pitch;     // 俯仰角（度）
  float yaw;       // 偏航角（度）
  float acc[3];    // 三轴加速度（m/s²）
  float gyro[3];   // 三轴角速度（°/s）
};

void setup() {
  // Serial 连接龙芯板（115200 baud），Serial1 预留给 JY61P6（115200 baud）。
  Serial.begin(115200);
  Serial1.begin(115200, SERIAL_8N1, 18, 17);

  // ESP32-S3 ADC 默认 12 位分辨率（0-4095）。
  analogReadResolution(12);

  // 初始化肌电滑动窗口缓冲区为 0。
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

  // 读取 IMU 数据（从 JY61P6 通过串口获取）。
  ImuValues imu = readImu();
  float rms = emgRms();

  // 手动拼 JSON 可以避免 Arduino 端引入额外库，便于快速烧录测试。
  // 输出格式紧凑，龙芯 Python 端直接用 json.loads 解析。
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

/**
 * 从 JY61P6 读取 IMU 数据。
 *
 * 第一阶段硬件联调使用简单 CSV 协议：
 *   roll,pitch,yaw,ax,ay,az,gx,gy,gz
 *
 * 等 JY61P6 在台架上确认稳定后，可替换成官方二进制协议解析。
 *
 * @return ImuValues 结构体，读取失败时返回默认值（重力加速度 9.8 m/s² 朝下）。
 */
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

/**
 * 计算肌电信号滑动窗口 RMS（均方根）。
 *
 * 均方根能反映肌肉激活强度，比瞬时 ADC 值更稳定。
 * RMS 值越大表示肌肉收缩越强。
 *
 * @return 当前滑动窗口的 RMS 值
 */
float emgRms() {
  // 均方根能反映肌肉激活强度，比瞬时 ADC 值更稳定。
  float sumSquares = 0;
  for (int i = 0; i < RMS_WINDOW; i++) {
    sumSquares += emgWindow[i] * emgWindow[i];
  }
  return sqrt(sumSquares / RMS_WINDOW);
}

/**
 * 打印长度为 3 的浮点数数组（逗号分隔），用于 JSON 拼接。
 * 减少 JSON 拼接重复代码。
 *
 * @param values[3] 要打印的三元素浮点数组
 */
void printTriple(float values[3]) {
  // 打印长度为 3 的数组，减少 JSON 拼接重复代码。
  Serial.print(values[0], 3);
  Serial.print(",");
  Serial.print(values[1], 3);
  Serial.print(",");
  Serial.print(values[2], 3);
}

/**
 * 解析 9 个逗号分隔的浮点数 CSV 行。
 *
 * JY61P6 输出格式示例：
 *   "0.12,0.34,-0.56,9.8,0.0,0.0,0.01,0.02,0.03"
 *
 * @param line   要解析的字符串行
 * @param values 用于存放解析后浮点数的数组（至少 9 个元素）
 * @return 成功解析的浮点数个数（期望值 9）
 */
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