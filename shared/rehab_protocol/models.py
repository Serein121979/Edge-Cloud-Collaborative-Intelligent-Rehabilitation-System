from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import time
from typing import Any
from uuid import uuid4


# 系统第一版固定使用这些动作状态，云端会拒绝不在列表里的状态。
# 这些状态对应肩肘训练的标准动作阶段：静止→抬起→保持→放下→完成，
# 以及两种错误状态（不正确姿势、异常代偿）。
VALID_STATES = (
    "idle",       # 静止/初始状态，手臂自然下垂
    "raising",    # 抬臂阶段，肩关节角度正在增大
    "holding",    # 保持阶段，手臂已达到目标角度并稳定保持
    "lowering",   # 放下阶段，肩关节角度正在减小
    "completed",  # 完成一次完整的训练动作
    "incorrect",  # 姿势不正确（如肘关节未伸直）
    "anomaly",    # 异常状态（如躯干代偿、肌电过高等）
)


def now_ms() -> int:
    """返回当前 Unix 时间戳，单位毫秒，方便边缘端和云端统一对齐。"""
    return int(time.time() * 1000)


def make_session_id(prefix: str = "session") -> str:
    """生成训练会话 ID，包含 UTC 时间和短随机串，便于日志检索。

    参数:
        prefix: 会话 ID 前缀，用于区分来源（如 "edge"、"cloud"）
    返回:
        格式为 "{prefix}_{UTC时间}_{8位随机hex}" 的字符串
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{stamp}_{uuid4().hex[:8]}"


def _float_list(value: Any, length: int | None = None) -> list[float]:
    """把输入数组统一转成 float 列表，并可选检查长度。

    这是模型层常用的类型转换辅助函数，确保 JSON 中的数字统一为 float，
    避免 Python 的 int/float 类型混用问题。

    参数:
        value: 输入值，可以是列表、None 或其他可迭代对象
        length: 期望的长度，不为 None 时会校验
    返回:
        由 float 组成的列表
    抛出:
        ValueError: 如果指定了 length 但实际长度不匹配
    """
    if value is None:
        values: list[float] = []
    else:
        values = [float(item) for item in value]
    if length is not None and len(values) != length:
        raise ValueError(f"expected {length} values, got {len(values)}")
    return values


@dataclass(slots=True)
class ImuSample:
    """ESP32 发来的 IMU 原始姿态和惯性数据。

    JY61P6 六轴 IMU 传感器输出的数据，包含：
    - 姿态角（roll/pitch/yaw）：描述传感器在三维空间中的朝向
    - 加速度（acc）：三轴加速度值，单位 m/s²
    - 角速度（gyro）：三轴角速度值，单位 rad/s

    这些数据用于检测躯干姿态是否稳定，以及是否存在代偿动作。
    """

    roll: float = 0.0      # 横滚角，绕 X 轴旋转，正值表示向右倾斜
    pitch: float = 0.0     # 俯仰角，绕 Y 轴旋转，正值表示向前俯
    yaw: float = 0.0       # 偏航角，绕 Z 轴旋转，正值表示向右转
    acc: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])   # 三轴加速度 [ax, ay, az]
    gyro: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])  # 三轴角速度 [gx, gy, gz]

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ImuSample":
        """从 JSON 字典构造 IMU 数据，缺字段时给出安全默认值。

        参数:
            payload: 包含 IMU 数据的字典，可以只包含部分字段
        返回:
            ImuSample 实例，缺失的字段使用默认值
        """
        payload = payload or {}
        return cls(
            roll=float(payload.get("roll", 0.0)),
            pitch=float(payload.get("pitch", 0.0)),
            yaw=float(payload.get("yaw", 0.0)),
            acc=_float_list(payload.get("acc", [0.0, 0.0, 0.0]), 3),
            gyro=_float_list(payload.get("gyro", [0.0, 0.0, 0.0]), 3),
        )

    def to_dict(self) -> dict[str, Any]:
        """转成可 JSON 序列化的字典，供上传或写日志使用。"""
        return {
            "roll": self.roll,
            "pitch": self.pitch,
            "yaw": self.yaw,
            "acc": self.acc,
            "gyro": self.gyro,
        }


@dataclass(slots=True)
class EmgSample:
    """sEMG 肌电采样数据，channels 是原始值，rms 是窗口均方根特征。

    表面肌电信号（Surface Electromyography）用于监测肌肉激活程度。
    原始 ADC 值经过滑动窗口计算 RMS（均方根）后，可以反映肌肉发力强度。
    在康复训练中，肌电值过高可能表示肌肉代偿或异常发力。
    """

    channels: list[float] = field(default_factory=list)  # 各通道的原始 ADC 采样值
    rms: list[float] = field(default_factory=list)        # 各通道的滑动窗口均方根值

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "EmgSample":
        """从 JSON 字典构造肌电数据。"""
        payload = payload or {}
        return cls(
            channels=_float_list(payload.get("channels", [])),
            rms=_float_list(payload.get("rms", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        """转成可 JSON 序列化的字典。"""
        return {"channels": self.channels, "rms": self.rms}


@dataclass(slots=True)
class SensorFrame:
    """ESP32 到龙芯边缘端的一帧传感器数据。

    这是边缘端接收到的原始数据帧，由 ESP32-S3 通过串口输出 JSON Lines 格式。
    每帧包含：
    - timestamp_ms：采样时间戳
    - device：设备标识
    - imu：六轴 IMU 数据（姿态角 + 加速度 + 角速度）
    - emg：肌电数据（原始值 + RMS）
    """

    timestamp_ms: int                    # 采样时间戳，Unix 毫秒
    device: str = "esp32_s3"            # 设备来源标识
    imu: ImuSample = field(default_factory=ImuSample)     # IMU 传感器数据
    emg: EmgSample = field(default_factory=EmgSample)     # 肌电传感器数据

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SensorFrame":
        """解析 ESP32 输出的一行 JSON。"""
        return cls(
            timestamp_ms=int(payload.get("timestamp_ms", now_ms())),
            device=str(payload.get("device", "esp32_s3")),
            imu=ImuSample.from_dict(payload.get("imu")),
            emg=EmgSample.from_dict(payload.get("emg")),
        )

    def to_dict(self) -> dict[str, Any]:
        """输出为比赛方案中约定的 JSON Lines 格式。"""
        return {
            "timestamp_ms": self.timestamp_ms,
            "device": self.device,
            "imu": self.imu.to_dict(),
            "emg": self.emg.to_dict(),
        }


@dataclass(slots=True)
class PoseFrame:
    """摄像头姿态识别结果，目前只保留肩肘角和 2D 关键点。

    由 MediaPipe Pose 模型从 RGB 摄像头帧中提取的人体姿态数据。
    第一版重点关注：
    - shoulder_angle：肩关节抬举角（手臂与躯干夹角）
    - elbow_angle：肘关节屈伸角（上臂与前臂夹角）
    - landmarks_2d：完整 33 个关键点坐标（预留扩展用）
    """

    shoulder_angle: float = 0.0         # 肩关节抬举角度，0°=自然下垂，90°=水平抬起
    elbow_angle: float = 180.0          # 肘关节屈伸角度，180°=完全伸直，越小代表弯曲越多
    landmarks_2d: list[dict[str, float]] = field(default_factory=list)  # MediaPipe 33 个关键点坐标

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "PoseFrame":
        """从云端或测试数据字典恢复姿态帧。"""
        payload = payload or {}
        return cls(
            shoulder_angle=float(payload.get("shoulder_angle", 0.0)),
            elbow_angle=float(payload.get("elbow_angle", 180.0)),
            landmarks_2d=list(payload.get("landmarks_2d", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        """转成可上传、可记录的 JSON 字典。"""
        return {
            "shoulder_angle": self.shoulder_angle,
            "elbow_angle": self.elbow_angle,
            "landmarks_2d": self.landmarks_2d,
        }


@dataclass(slots=True)
class RehabFrame:
    """龙芯边缘端融合后的标准康复训练帧。

    这是系统中最核心的数据结构，由 RehabFusionPipeline 融合摄像头姿态和
    传感器数据后生成，包含了完整的训练状态信息：
    - pose：来自摄像头的肩肘角度
    - imu_features：从 IMU 提取的躯干姿态特征
    - emg_features：从 sEMG 提取的肌肉激活特征
    - state：规则引擎输出的动作阶段
    - score：动作质量评分（0-100）
    - anomalies：检测到的异常列表
    """

    session_id: str                     # 所属训练会话 ID
    timestamp_ms: int                    # 融合帧的时间戳
    pose: PoseFrame                                      # 姿态识别结果
    imu_features: dict[str, Any]                         # IMU 特征数据
    emg_features: dict[str, Any]                         # 肌电特征数据
    state: str = "idle"                 # 训练动作阶段状态
    score: float = 0.0                  # 动作质量评分（0-100 分）
    anomalies: list[str] = field(default_factory=list)    # 检测到的异常列表

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RehabFrame":
        """从云端 API 收到的 JSON 中恢复康复帧，并校验状态合法性。

        参数:
            payload: 包含康复帧数据的字典
        返回:
            RehabFrame 实例
        抛出:
            ValueError: 如果状态值不在 VALID_STATES 中
        """
        state = str(payload.get("state", "idle"))
        if state not in VALID_STATES:
            raise ValueError(f"invalid rehab state: {state}")
        return cls(
            session_id=str(payload["session_id"]),
            timestamp_ms=int(payload.get("timestamp_ms", now_ms())),
            pose=PoseFrame.from_dict(payload.get("pose")),
            imu_features=dict(payload.get("imu_features", {})),
            emg_features=dict(payload.get("emg_features", {})),
            state=state,
            score=float(payload.get("score", 0.0)),
            anomalies=list(payload.get("anomalies", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为 API 和 WebSocket 都能直接使用的字典。

        这是边缘端上传和云端转发的标准格式，前端直接解析此字典进行展示。
        """
        return {
            "session_id": self.session_id,
            "timestamp_ms": self.timestamp_ms,
            "pose": self.pose.to_dict(),
            "imu_features": self.imu_features,
            "emg_features": self.emg_features,
            "state": self.state,
            "score": self.score,
            "anomalies": self.anomalies,
        }