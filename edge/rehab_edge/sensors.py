from __future__ import annotations
import json
import math
import time
from collections.abc import Iterator
from typing import TextIO

from shared.rehab_protocol import EmgSample, ImuSample, SensorFrame, now_ms


class SimulatedSensorReader:
    """模拟 IMU/sEMG 传感器数据源，用于在硬件未完全联通时先跑通软件闭环。

    此生成器会持续产生模拟的传感器帧，包含：
    - IMU 数据：用正弦波模拟身体轻微摆动和转动
    - sEMG 数据：周期性变化的肌电信号，每隔一段时间模拟一次高负荷异常

    通过迭代此对象，可以像操作真实传感器数据流一样测试整个流水线。

    属性:
        interval_s: 每次生成帧之间的间隔时间（秒），默认 0.05 秒 = 20Hz
        step: 内部步数计数器，用于控制模拟数据的相位
    """

    def __init__(self, interval_s: float = 0.05) -> None:
        """初始化模拟传感器读取器。

        参数:
            interval_s: 模拟帧的生成间隔（秒），默认 50ms 对应 20Hz 采样率
        """
        self.interval_s = interval_s
        self.step = 0

    def __iter__(self) -> Iterator[SensorFrame]:
        """无限生成模拟传感器数据帧。

        使用正弦波模拟各种传感器值随时间的周期性变化：
        - roll: 躯干横滚角，范围 ±5°，模拟身体的轻微左右晃动
        - pitch: 躯干俯仰角，范围 ±8°，模拟身体的前后摆动
        - yaw: 躯干偏航角，范围 ±15°，模拟身体的左右转动
        - emg_raw: 肌电原始值，范围 420~580，每 300 步中出现一次高值（~980）

        Yields:
            SensorFrame: 模拟的传感器数据帧
        """
        while True:
            # 使用 step/20 作为时间参数，控制正弦波的变化速度
            t = self.step / 20.0
            roll = 5.0 * math.sin(t / 2.0)           # 横滚角正弦变化
            pitch = 8.0 * math.sin(t / 3.0)          # 俯仰角正弦变化
            yaw = 15.0 * math.sin(t / 6.0)           # 偏航角正弦变化
            emg_raw = 420.0 + 160.0 * max(0.0, math.sin(t))  # 肌电值正半周期变化
            if self.step % 300 > 245:                 # 每 300 步模拟一次肌电异常高值
                emg_raw = 980.0
            yield SensorFrame(
                timestamp_ms=now_ms(),
                imu=ImuSample(
                    roll=roll,
                    pitch=pitch,
                    yaw=yaw,
                    acc=[0.0, 0.0, 9.8],             # 静止状态下仅重力加速度
                    gyro=[0.1 * math.sin(t), 0.2 * math.cos(t), 0.0],  # 角速度小幅度波动
                ),
                emg=EmgSample(channels=[emg_raw], rms=[emg_raw]),
            )
            self.step += 1
            time.sleep(self.interval_s)


class JsonLineSensorReader:
    """从文本流逐行读取 JSON Lines 格式的传感器数据。

    适用于读取预先录制的串口日志或离线数据文件进行回放分析。
    每行应为独立的 JSON 对象，格式与 ESP32-S3 输出的 JSON Lines 一致。

    属性:
        stream: 可读文本流对象（如文件句柄、StringIO 等）
    """

    def __init__(self, stream: TextIO) -> None:
        """初始化 JSON Lines 读取器。

        参数:
            stream: 打开的文本流对象，每行是一个 JSON 字符串
        """
        self.stream = stream

    def __iter__(self) -> Iterator[SensorFrame]:
        """逐行读取文本流并解析为 SensorFrame。

        Yields:
            SensorFrame: 从 JSON 行解析得到的传感器帧
        """
        for line in self.stream:
            line = line.strip()
            if not line:
                continue
            yield SensorFrame.from_dict(json.loads(line))


class SerialSensorReader:
    """从真实串口读取 ESP32-S3 实时输出的传感器数据。

    依赖 PySerial 库，适用于龙芯边缘端连接 ESP32-S3 硬件时的数据采集。
    使用阻塞式读取，超时由 timeout 参数控制。

    属性:
        serial: PySerial 串口对象
    """

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0) -> None:
        """初始化串口传感器读取器。

        参数:
            port: 串口设备路径，如 Linux 下为 "/dev/ttyUSB0"，Windows 下为 "COM3"
            baudrate: 串口波特率，默认 115200（与 ESP32-S3 固件配置一致）
            timeout: 读取超时时间（秒），默认 1.0 秒
        """
        import serial  # type: ignore

        self.serial = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)

    def __iter__(self) -> Iterator[SensorFrame]:
        """持续从串口读取数据流并解析为 SensorFrame。

        每次读取一行（以换行符分隔），尝试以 UTF-8 解码并解析为 JSON。
        读取失败或解码异常的行会被跳过，保证数据流不中断。

        Yields:
            SensorFrame: 从串口 JSON Lines 解析得到的传感器帧
        """
        while True:
            raw = self.serial.readline().decode("utf-8", errors="ignore").strip()
            if not raw:
                continue
            yield SensorFrame.from_dict(json.loads(raw))


def imu_features(frame: SensorFrame) -> dict[str, float | list[float]]:
    """从 IMU 原始数据中提取规则引擎和前端展示需要的特征。

    将 IMU 的原始姿态角（roll/pitch/yaw）、加速度和角速度
    整理为统一的特征字典，供规则引擎的 _anomalies 方法使用。

    参数:
        frame: 传感器数据帧，包含 IMU 采样数据
    返回:
        特征字典，包含 roll、pitch、yaw、acc、gyro 等字段
    """
    return {
        "roll": frame.imu.roll,
        "pitch": frame.imu.pitch,
        "yaw": frame.imu.yaw,
        "acc": frame.imu.acc,
        "gyro": frame.imu.gyro,
    }


def emg_features(frame: SensorFrame) -> dict[str, float | list[float]]:
    """计算 sEMG 肌电特征，包括均方根均值、最大值和峰值。

    经过滑动窗口 RMS 处理的肌电信号可以平滑地反映肌肉激活强度。
    此函数提供多种聚合特征，用于判断肌肉负荷是否过高。

    参数:
        frame: 传感器数据帧，包含肌电采样数据
    返回:
        特征字典，包含：
        - channels: 各通道原始值
        - rms: 各通道 RMS 值
        - rms_mean: 所有通道 RMS 的平均值
        - rms_max: 所有通道 RMS 的最大值
        - peak: 所有通道原始值的最大值
    """
    channels = frame.emg.channels
    rms_values = frame.emg.rms or channels
    return {
        "channels": channels,
        "rms": rms_values,
        "rms_mean": sum(rms_values) / len(rms_values) if rms_values else 0.0,
        "rms_max": max(rms_values) if rms_values else 0.0,
        "peak": max(channels) if channels else 0.0,
    }