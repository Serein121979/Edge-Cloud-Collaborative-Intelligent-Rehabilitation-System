#include <Wire.h>

/**
 * ESP32-S3 JY61P I2C 角度读取器。
 *
 * 已确认 I2C 地址为 0x50。
 * 本固件每 200ms 读取一次角度寄存器，并打印 roll / pitch / yaw。
 */

const int I2C_SDA_PIN = 8;
const int I2C_SCL_PIN = 9;
const int HOST_BAUD = 115200;
const uint8_t IMU_I2C_ADDR = 0x50;
const uint8_t ANGLE_REG_START = 0x3D;  // Roll/Pitch/Yaw 起始寄存器

unsigned long lastReadMs = 0;

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

void setup() {
  Serial.begin(HOST_BAUD);
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setClock(100000);

  Serial.println();
  Serial.println("=== JY61P I2C angle reader ===");
  Serial.println("I2C addr -> 0x50");
  Serial.println("SDA -> GPIO8");
  Serial.println("SCL -> GPIO9");
  Serial.println("I2C clock -> 100kHz");
}

void loop() {
  if (millis() - lastReadMs < 200) {
    return;
  }
  lastReadMs = millis();

  uint8_t data[6];
  if (!readRegisters(ANGLE_REG_START, data, sizeof(data))) {
    Serial.println("read failed");
    return;
  }

  int16_t rollRaw = static_cast<int16_t>(data[0] | (data[1] << 8));
  int16_t pitchRaw = static_cast<int16_t>(data[2] | (data[3] << 8));
  int16_t yawRaw = static_cast<int16_t>(data[4] | (data[5] << 8));

  Serial.print("roll=");
  Serial.print(rawAngleToDegrees(rollRaw), 3);
  Serial.print(" pitch=");
  Serial.print(rawAngleToDegrees(pitchRaw), 3);
  Serial.print(" yaw=");
  Serial.println(rawAngleToDegrees(yawRaw), 3);
}
