from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import time
from typing import Any
from uuid import uuid4


# 系统第一版固定使用这些动作状态，云端会拒绝不在列表里的状态。
VALID_STATES = (
    "idle",
    "raising",
    "holding",
    "lowering",
    "completed",
    "incorrect",
    "anomaly",
)


def now_ms() -> int:
    """返回当前 Unix 时间戳，单位毫秒，方便边缘端和云端统一对齐。"""
    return int(time.time() * 1000)


def make_session_id(prefix: str = "session") -> str:
    """生成训练会话 ID，包含 UTC 时间和短随机串，便于日志检索。"""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{stamp}_{uuid4().hex[:8]}"


def _float_list(value: Any, length: int | None = None) -> list[float]:
    """把输入数组统一转成 float 列表，并可选检查长度。"""
    if value is None:
        values: list[float] = []
    else:
        values = [float(item) for item in value]
    if length is not None and len(values) != length:
        raise ValueError(f"expected {length} values, got {len(values)}")
    return values


@dataclass(slots=True)
class ImuSample:
    """ESP32 发来的 IMU 原始姿态和惯性数据。"""

    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    acc: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    gyro: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ImuSample":
        """从 JSON 字典构造 IMU 数据，缺字段时给出安全默认值。"""
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
    """sEMG 肌电采样数据，channels 是原始值，rms 是窗口均方根特征。"""

    channels: list[float] = field(default_factory=list)
    rms: list[float] = field(default_factory=list)

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
    """ESP32 到龙芯边缘端的一帧传感器数据。"""

    timestamp_ms: int
    device: str = "esp32_s3"
    imu: ImuSample = field(default_factory=ImuSample)
    emg: EmgSample = field(default_factory=EmgSample)

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
    """摄像头姿态识别结果，目前只保留肩肘角和 2D 关键点。"""

    shoulder_angle: float = 0.0
    elbow_angle: float = 180.0
    landmarks_2d: list[dict[str, float]] = field(default_factory=list)

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
    """龙芯边缘端融合后的标准康复训练帧。"""

    session_id: str
    timestamp_ms: int
    pose: PoseFrame
    imu_features: dict[str, Any]
    emg_features: dict[str, Any]
    state: str = "idle"
    score: float = 0.0
    anomalies: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RehabFrame":
        """从云端 API 收到的 JSON 中恢复康复帧，并校验状态合法性。"""
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
        """转换为 API 和 WebSocket 都能直接使用的字典。"""
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
