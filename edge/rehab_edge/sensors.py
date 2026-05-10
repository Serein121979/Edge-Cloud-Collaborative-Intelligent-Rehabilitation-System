from __future__ import annotations

import json
import math
import time
from collections.abc import Iterator
from typing import TextIO

from shared.rehab_protocol import EmgSample, ImuSample, SensorFrame, now_ms


class SimulatedSensorReader:
    """模拟 IMU/sEMG 数据源，用来在硬件未完全联通时先跑软件闭环。"""

    def __init__(self, interval_s: float = 0.05) -> None:
        self.interval_s = interval_s
        self.step = 0

    def __iter__(self) -> Iterator[SensorFrame]:
        while True:
            # 用正弦曲线模拟身体轻微摆动和肌电变化。
            t = self.step / 20.0
            roll = 5.0 * math.sin(t / 2.0)
            pitch = 8.0 * math.sin(t / 3.0)
            yaw = 15.0 * math.sin(t / 6.0)
            emg_raw = 420.0 + 160.0 * max(0.0, math.sin(t))
            if self.step % 300 > 245:
                emg_raw = 980.0
            yield SensorFrame(
                timestamp_ms=now_ms(),
                imu=ImuSample(
                    roll=roll,
                    pitch=pitch,
                    yaw=yaw,
                    acc=[0.0, 0.0, 9.8],
                    gyro=[0.1 * math.sin(t), 0.2 * math.cos(t), 0.0],
                ),
                emg=EmgSample(channels=[emg_raw], rms=[emg_raw]),
            )
            self.step += 1
            time.sleep(self.interval_s)


class JsonLineSensorReader:
    """从文本流读取 JSON Lines，适合读取串口日志或离线数据文件。"""

    def __init__(self, stream: TextIO) -> None:
        self.stream = stream

    def __iter__(self) -> Iterator[SensorFrame]:
        for line in self.stream:
            line = line.strip()
            if not line:
                continue
            yield SensorFrame.from_dict(json.loads(line))


class SerialSensorReader:
    """从真实串口读取 ESP32-S3 输出的数据。"""

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0) -> None:
        import serial  # type: ignore

        self.serial = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)

    def __iter__(self) -> Iterator[SensorFrame]:
        while True:
            raw = self.serial.readline().decode("utf-8", errors="ignore").strip()
            if not raw:
                continue
            yield SensorFrame.from_dict(json.loads(raw))


def imu_features(frame: SensorFrame) -> dict[str, float | list[float]]:
    """把 IMU 原始数据整理成规则引擎和云端展示需要的特征。"""
    return {
        "roll": frame.imu.roll,
        "pitch": frame.imu.pitch,
        "yaw": frame.imu.yaw,
        "acc": frame.imu.acc,
        "gyro": frame.imu.gyro,
    }


def emg_features(frame: SensorFrame) -> dict[str, float | list[float]]:
    """计算肌电展示特征：平均 RMS、最大 RMS 和峰值。"""
    channels = frame.emg.channels
    rms_values = frame.emg.rms or channels
    return {
        "channels": channels,
        "rms": rms_values,
        "rms_mean": sum(rms_values) / len(rms_values) if rms_values else 0.0,
        "rms_max": max(rms_values) if rms_values else 0.0,
        "peak": max(channels) if channels else 0.0,
    }
