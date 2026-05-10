from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shared.rehab_protocol import PoseFrame


@dataclass(slots=True)
class RehabRuleConfig:
    """规则引擎的阈值配置，可根据患者情况和实测数据调参。

    这些阈值定义了肩肘康复训练动作"正确"与"异常"的边界：
    - idle_angle: 判定为静止状态的最大肩关节角度
    - target_angle: 训练目标角度（用于评分参考）
    - hold_angle: 达到保持阶段所需的最小肩关节角度
    - complete_angle: 判定一次动作完成的最大肩关节角度
    - min_elbow_angle: 肘关节伸直的最小要求角度
    - max_roll_abs: 躯干横滚角最大允许绝对值（躯干代偿阈值）
    - max_pitch_abs: 躯干俯仰角最大允许绝对值（躯干代偿阈值）
    - high_emg_rms: 肌电 RMS 高阈值（肌肉过负荷阈值）
    - hold_frames_required: 达到保持角度后需要持续的帧数（防抖动）
    """

    idle_angle: float = 25.0          # 静止角度阈值（°），低于此值视为自然下垂
    target_angle: float = 90.0        # 训练目标角度（°），用于评分
    hold_angle: float = 80.0          # 保持角度阈值（°），高于此值开始计时保持
    complete_angle: float = 35.0      # 完成角度阈值（°），低于此值且曾到过保持区视为完成
    min_elbow_angle: float = 135.0    # 最小肘关节角度（°），肘关节伸直下限
    max_roll_abs: float = 35.0       # 最大允许躯干横滚角度绝对值（°），超过视为代偿
    max_pitch_abs: float = 45.0      # 最大允许躯干俯仰角度绝对值（°），超过视为代偿
    high_emg_rms: float = 900.0      # 肌电 RMS 高阈值（ADC 值），超过视为肌肉过负荷
    hold_frames_required: int = 8    # 保持阶段所需最少连续帧数


@dataclass(slots=True)
class RehabDecision:
    """规则引擎一次评估的输出结果，包含状态、评分和异常信息。

    属性:
        state: 当前动作阶段（idle/raising/holding/lowering/completed/incorrect/anomaly）
        score: 动作质量评分（0~100 分）
        anomalies: 检测到的异常列表，如 ["elbow_not_extended"]
        repetitions: 累计完成的训练次数
    """

    state: str                     # 动作阶段状态
    score: float                   # 当前评分
    anomalies: list[str]           # 检测到的异常列表
    repetitions: int               # 累计完成次数


class RehabStateMachine:
    """上肢肩肘康复训练的状态机，负责将连续的角度变化和传感器数据
    转换为离散的动作阶段状态。

    状态转换流程：
    idle → raising → holding → lowering → completed → idle
              ↓                     ↓
          incorrect              anomaly

    核心逻辑：
    1. 通过肩关节角度判断动作阶段（抬臂/保持/放下/静止）
    2. 通过 IMU 姿态角检测躯干代偿
    3. 通过 sEMG RMS 检测肌肉过负荷
    4. 通过肘关节角度检测肘部未伸直
    5. 综合以上信息给出动作质量评分

    属性:
        config: 规则引擎配置（阈值等）
        previous_angle: 上一帧的肩关节角度，用于计算角度变化趋势
        has_reached_target: 是否已达到目标保持区
        hold_frames: 在保持区连续停留的帧数计数
        repetitions: 累计完成的训练次数
    """

    def __init__(self, config: RehabRuleConfig | None = None) -> None:
        """初始化状态机。

        参数:
            config: 规则引擎配置，为 None 时使用 RehabRuleConfig 的默认值
        """
        self.config = config or RehabRuleConfig()
        self.previous_angle: float | None = None      # 上一帧肩关节角度
        self.has_reached_target = False               # 是否已到达目标保持区
        self.hold_frames = 0                          # 保持区连续帧计数
        self.repetitions = 0                          # 累计完成次数

    def evaluate(
        self,
        pose: PoseFrame,
        imu_features: dict[str, Any] | None = None,
        emg_features: dict[str, Any] | None = None,
    ) -> RehabDecision:
        """综合姿态、IMU、肌电多模态特征，输出当前动作状态、评分和异常。

        评估流程：
        1. 检测各类异常（弯肘、躯干代偿、肌肉过负荷）
        2. 如果存在严重异常，直接返回 anomaly 或 incorrect 状态
        3. 否则通过肩关节角度变化判断 motion state
        4. 计算动作质量评分

        参数:
            pose: 摄像头姿态识别结果（肩肘角度）
            imu_features: IMU 特征字典（roll/pitch/yaw/acc/gyro）
            emg_features: 肌电特征字典（rms_mean/rms_max/peak 等）
        返回:
            RehabDecision 实例，包含状态、评分、异常列表和完成次数
        """
        imu_features = imu_features or {}
        emg_features = emg_features or {}
        anomalies = self._anomalies(pose, imu_features, emg_features)

        # 严重异常直接覆盖状态
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
        """根据肩关节角度变化判断当前动作阶段。

        状态逻辑：
        - 角度 > hold_angle（80°）→ 进入保持区，连续 hold_frames_required 帧后变为 holding
        - 曾到过保持区且角度回落到 complete_angle（35°）以下 → 计为一次 completed
        - 角度 < idle_angle（25°）且未到过保持区 → idle
        - 角度上升趋势（delta ≥ 1°）→ raising
        - 角度下降趋势（delta ≤ -1°）→ lowering
        - 其他情况保持当前状态

        参数:
            shoulder_angle: 当前帧的肩关节抬举角度
        返回:
            动作阶段状态字符串
        """
        config = self.config
        previous = self.previous_angle if self.previous_angle is not None else shoulder_angle
        delta = shoulder_angle - previous

        # 到达目标角附近后，需要保持足够帧数，避免抖动导致误判为 holding
        if shoulder_angle >= config.hold_angle:
            self.has_reached_target = True
            self.hold_frames += 1
            if self.hold_frames >= config.hold_frames_required:
                return "holding"
            return "raising"

        # 曾经达到目标并回落到完成阈值以下，计为完成一次完整动作
        if self.has_reached_target and shoulder_angle <= config.complete_angle:
            self.repetitions += 1
            self.has_reached_target = False
            self.hold_frames = 0
            return "completed"

        # 角度低于静止阈值且未到过目标区，视为静止状态
        if shoulder_angle <= config.idle_angle and not self.has_reached_target:
            self.hold_frames = 0
            return "idle"

        # 根据角度变化趋势判断抬臂或放臂
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
        """检测训练过程中可能出现的异常情况。

        目前支持三类异常检测：
        1. 肘关节未伸直（elbow_not_extended）：抬臂时肘关节弯曲超过阈值
        2. 躯干代偿（trunk_compensation）：身体过度倾斜来辅助抬手
        3. 肌肉过负荷（excessive_muscle_activation）：肌电值过高

        参数:
            pose: 当前姿态帧（肩肘角度）
            imu_features: IMU 特征（用于检测躯干姿态异常）
            emg_features: 肌电特征（用于检测肌肉负荷异常）
        返回:
            异常名称列表，无异常时为空列表
        """
        config = self.config
        anomalies: list[str] = []

        # 1. 检测肘关节未伸直：在抬臂动作中肘关节角度小于阈值
        if pose.shoulder_angle > config.idle_angle and pose.elbow_angle < config.min_elbow_angle:
            anomalies.append("elbow_not_extended")

        # 2. 检测躯干代偿：躯干横滚角或俯仰角超过允许范围
        roll = abs(float(imu_features.get("roll", 0.0)))
        pitch = abs(float(imu_features.get("pitch", 0.0)))
        if roll > config.max_roll_abs or pitch > config.max_pitch_abs:
            anomalies.append("trunk_compensation")

        # 3. 检测肌肉过负荷：任意通道肌电 RMS 最大值超过阈值
        emg_rms_max = float(emg_features.get("rms_max", 0.0))
        if emg_rms_max > config.high_emg_rms:
            anomalies.append("excessive_muscle_activation")

        return anomalies

    def _score(self, pose: PoseFrame, state: str, anomalies: list[str]) -> float:
        """计算当前动作的质量评分。

        评分策略：
        1. 基础分 = 100 - |目标角度 - 当前肩关节角度|，越接近目标分越高
        2. 肘关节奖励分：肘关节伸直程度越好额外加分越多（最多 10 分）
        3. 异常惩罚：每检测到一个异常扣 20 分
        4. completed 状态保底 90 分

        参数:
            pose: 当前姿态帧
            state: 当前动作阶段
            anomalies: 检测到的异常列表
        返回:
            综合评分（0~100 分，保留两位小数）
        """
        target = self.config.target_angle
        # 基础角度评分：越接近目标角度分越高
        angle_score = max(0.0, min(100.0, 100.0 - abs(target - pose.shoulder_angle)))
        # 肘关节伸直奖励：超出最低要求的部分每 4° 加 1 分，上限 10 分
        elbow_bonus = max(0.0, min(10.0, (pose.elbow_angle - self.config.min_elbow_angle) / 4))
        # 异常惩罚：每个异常扣 20 分
        penalty = 20.0 * len(anomalies)
        # 完成动作保底 90 分
        if state == "completed":
            angle_score = max(angle_score, 90.0)
        return round(max(0.0, min(100.0, angle_score + elbow_bonus - penalty)), 2)