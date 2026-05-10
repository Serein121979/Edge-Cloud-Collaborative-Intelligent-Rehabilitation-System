from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shared.rehab_protocol import PoseFrame


@dataclass(slots=True)
class RehabRuleConfig:
    """规则引擎阈值配置，后期可根据实测数据调参。"""

    idle_angle: float = 25.0
    target_angle: float = 90.0
    hold_angle: float = 80.0
    complete_angle: float = 35.0
    min_elbow_angle: float = 135.0
    max_roll_abs: float = 35.0
    max_pitch_abs: float = 45.0
    high_emg_rms: float = 900.0
    hold_frames_required: int = 8


@dataclass(slots=True)
class RehabDecision:
    """规则引擎一次判断的输出结果。"""

    state: str
    score: float
    anomalies: list[str]
    repetitions: int


class RehabStateMachine:
    """上肢肩肘训练状态机，负责把连续角度变化转成动作状态。"""

    def __init__(self, config: RehabRuleConfig | None = None) -> None:
        self.config = config or RehabRuleConfig()
        self.previous_angle: float | None = None
        self.has_reached_target = False
        self.hold_frames = 0
        self.repetitions = 0

    def evaluate(
        self,
        pose: PoseFrame,
        imu_features: dict[str, Any] | None = None,
        emg_features: dict[str, Any] | None = None,
    ) -> RehabDecision:
        """综合姿态、IMU、肌电特征，输出动作状态、评分和异常。"""
        imu_features = imu_features or {}
        emg_features = emg_features or {}
        anomalies = self._anomalies(pose, imu_features, emg_features)
        if "trunk_compensation" in anomalies or "excessive_muscle_activation" in anomalies:
            state = "anomaly"
        elif "elbow_not_extended" in anomalies:
            state = "incorrect"
        else:
            state = self._motion_state(pose.shoulder_angle)

        score = self._score(pose, state, anomalies)
        self.previous_angle = pose.shoulder_angle
        return RehabDecision(
            state=state,
            score=score,
            anomalies=anomalies,
            repetitions=self.repetitions,
        )

    def _motion_state(self, shoulder_angle: float) -> str:
        """根据肩关节角度变化判断 idle/raising/holding/lowering/completed。"""
        config = self.config
        previous = self.previous_angle if self.previous_angle is not None else shoulder_angle
        delta = shoulder_angle - previous

        # 到达目标角附近后，需要保持若干帧，避免抖动导致误判。
        if shoulder_angle >= config.hold_angle:
            self.has_reached_target = True
            self.hold_frames += 1
            if self.hold_frames >= config.hold_frames_required:
                return "holding"
            return "raising"

        # 曾经达到目标并回落到完成阈值以下，计为完成一次。
        if self.has_reached_target and shoulder_angle <= config.complete_angle:
            self.repetitions += 1
            self.has_reached_target = False
            self.hold_frames = 0
            return "completed"

        if shoulder_angle <= config.idle_angle and not self.has_reached_target:
            self.hold_frames = 0
            return "idle"

        if delta >= 1.0:
            return "raising"
        if delta <= -1.0:
            return "lowering"
        return "holding" if self.has_reached_target else "idle"

    def _anomalies(
        self,
        pose: PoseFrame,
        imu_features: dict[str, Any],
        emg_features: dict[str, Any],
    ) -> list[str]:
        """检测常见错误：弯肘、躯干代偿、肌肉负荷过高。"""
        config = self.config
        anomalies: list[str] = []
        if pose.shoulder_angle > config.idle_angle and pose.elbow_angle < config.min_elbow_angle:
            anomalies.append("elbow_not_extended")

        roll = abs(float(imu_features.get("roll", 0.0)))
        pitch = abs(float(imu_features.get("pitch", 0.0)))
        if roll > config.max_roll_abs or pitch > config.max_pitch_abs:
            anomalies.append("trunk_compensation")

        emg_rms_max = float(emg_features.get("rms_max", 0.0))
        if emg_rms_max > config.high_emg_rms:
            anomalies.append("excessive_muscle_activation")
        return anomalies

    def _score(self, pose: PoseFrame, state: str, anomalies: list[str]) -> float:
        """给当前动作打分：越接近目标角度越高，异常会扣分。"""
        target = self.config.target_angle
        angle_score = max(0.0, min(100.0, 100.0 - abs(target - pose.shoulder_angle)))
        elbow_bonus = max(0.0, min(10.0, (pose.elbow_angle - self.config.min_elbow_angle) / 4))
        penalty = 20.0 * len(anomalies)
        if state == "completed":
            angle_score = max(angle_score, 90.0)
        return round(max(0.0, min(100.0, angle_score + elbow_bonus - penalty)), 2)
