#include <Wire.h>

/**
 * ESP32-S3 传感器桥接固件。
 *
 * 功能：
 * 1. 通过 I2C 读取 JY61P 姿态角（roll/pitch/yaw）
 * 2. 通过 ADC 读取单通道 sEMG 原始值并计算 RMS
 * 3. 持续输出统一 JSON 给龙芯边缘端
 *
 * 当前 JY61P 已确认使用 I2C 地址 0x50。
 */

const int EMG_PIN = 1;
const int SAMPLE_INTERVAL_MS = 200;  // 5Hz，先方便人工观察；后续联动再提频
const int RMS_WINDOW = 32;

const int I2C_SDA_PIN = 8;
const int I2C_SCL_PIN = 9;
const int HOST_BAUD = 115200;
const uint8_t IMU_I2C_ADDR = 0x50;
const uint8_t ANGLE_REG_START = 0x3D;

float emgWindow[RMS_WINDOW];
int emgIndex = 0;
unsigned long lastSampleMs = 0;
unsigned long lastImuUpdateMs = 0;

struct ImuValues {
  float roll;
  float pitch;
  float yaw;
  float acc[3];
  float gyro[3];
};

ImuValues lastImu = {
    0.0f,
    0.0f,
    0.0f,
    {0.0f, 0.0f, 9.8f},
    {0.0f, 0.0f, 0.0f},
};

bool readRegisters(uint8_t startReg, uint8_t* buffer, size_t length) {
  Wire.beginTransmission(IMU_I2C_ADDR);
  Wire.write(startReg);
  if (Wire.endTransmission(false) != 0) {
    while (Wire.available()) {
      Wire.read();
    }
    return false;
  }

  size_t received =
      Wire.requestFrom(static_cast<int>(IMU_I2C_ADDR), static_cast<int>(length), static_cast<int>(true));
  if (received != length) {
    while (Wire.available()) {
      Wire.read();
    }
    return false;
  }

  for (size_t i = 0; i < length; i++) {
    buffer[i] = Wire.read();
  }

  while (Wire.available()) {
    Wire.read();
  }
  return true;
}

float rawAngleToDegrees(int16_t raw) {
  return (static_cast<float>(raw) / 32768.0f) * 180.0f;
}

float shortestAngleDelta(float next, float prev) {
  float delta = next - prev;
  while (delta > 180.0f) {
    delta -= 360.0f;
  }
  while (delta < -180.0f) {
    delta += 360.0f;
  }
  return delta;
}

ImuValues readImu() {
  uint8_t data[6];
  if (!readRegisters(ANGLE_REG_START, data, sizeof(data))) {
    return lastImu;
  }

  ImuValues imu = lastImu;
  imu.roll = rawAngleToDegrees(static_cast<int16_t>(data[0] | (data[1] << 8)));
  imu.pitch = rawAngleToDegrees(static_cast<int16_t>(data[2] | (data[3] << 8)));
  imu.yaw = rawAngleToDegrees(static_cast<int16_t>(data[4] | (data[5] << 8)));
  imu.acc[0] = 0.0f;
  imu.acc[1] = 0.0f;
  imu.acc[2] = 9.8f;

  unsigned long now = millis();
  if (lastImuUpdateMs > 0 && now > lastImuUpdateMs) {
    float dt = (now - lastImuUpdateMs) / 1000.0f;
    if (dt > 0.0f && dt < 1.0f) {
      imu.gyro[0] = shortestAngleDelta(imu.roll, lastImu.roll) / dt;
      imu.gyro[1] = shortestAngleDelta(imu.pitch, lastImu.pitch) / dt;
      imu.gyro[2] = shortestAngleDelta(imu.yaw, lastImu.yaw) / dt;
    } else {
      imu.gyro[0] = 0.0f;
      imu.gyro[1] = 0.0f;
      imu.gyro[2] = 0.0f;
    }
  } else {
    imu.gyro[0] = 0.0f;
    imu.gyro[1] = 0.0f;
    imu.gyro[2] = 0.0f;
  }

  lastImu = imu;
  lastImuUpdateMs = now;
  return imu;
}

float emgRms() {
  float sumSquares = 0.0f;
  for (int i = 0; i < RMS_WINDOW; i++) {
    sumSquares += emgWindow[i] * emgWindow[i];
  }
  return sqrt(sumSquares / RMS_WINDOW);
}

void printTriple(float values[3]) {
  Serial.print(values[0], 3);
  Serial.print(",");
  Serial.print(values[1], 3);
  Serial.print(",");
  Serial.print(values[2], 3);
}

void setup() {
  Serial.begin(HOST_BAUD);
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setClock(100000);
  analogReadResolution(12);

  for (int i = 0; i < RMS_WINDOW; i++) {
    emgWindow[i] = 0.0f;
  }
}

void loop() {
  unsigned long now = millis();
  if (now - lastSampleMs < SAMPLE_INTERVAL_MS) {
    return;
  }
  lastSampleMs = now;

  float emgRaw = analogRead(EMG_PIN);
  emgWindow[emgIndex] = emgRaw;
  emgIndex = (emgIndex + 1) % RMS_WINDOW;

  ImuValues imu = readImu();
  float rms = emgRms();

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
