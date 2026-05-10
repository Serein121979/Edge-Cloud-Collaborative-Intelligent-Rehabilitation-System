from __future__ import annotations

from shared.rehab_protocol import PoseFrame, RehabFrame, SensorFrame

from .rules import RehabStateMachine
from .sensors import emg_features, imu_features


class RehabFusionPipeline:
    """边缘端融合流水线：将摄像头姿态识别结果和 ESP32 传感器数据
    合成为标准的 RehabFrame，并执行规则引擎进行动作评估。

    这是边缘端的核心处理模块，负责：
    1. 从传感器帧提取 IMU 特征和肌电特征
    2. 将姿态数据和传感器特征一起送入规则引擎
    3. 生成包含状态、评分和异常的完整康复帧

    属性:
        session_id: 当前训练会话 ID
        rules: 规则引擎状态机实例
    """

    def __init__(self, session_id: str, rules: RehabStateMachine | None = None) -> None:
        """初始化融合流水线。

        参数:
            session_id: 训练会话 ID，用于标识一组连续的训练数据
            rules: 规则引擎状态机，为 None 时使用默认配置创建新实例
        """
        self.session_id = session_id
        self.rules = rules or RehabStateMachine()

    def fuse(self, pose: PoseFrame, sensor: SensorFrame) -> RehabFrame:
        """融合一帧摄像头姿态数据和一帧传感器数据，执行规则判断并生成标准康复帧。

        融合流程：
        1. 从传感器帧中提取 IMU 特征（躯干姿态角等）
        2. 从传感器帧中提取肌电特征（RMS 均值、最大值等）
        3. 将姿态数据和特征送入规则引擎进行评估
        4. 根据评估结果构建完整的 RehabFrame

        参数:
            pose: 摄像头姿态识别结果（肩肘角度）
            sensor: ESP32 传感器数据帧（IMU + sEMG）
        返回:
            RehabFrame 实例，包含融合后的所有数据和规则引擎判断结果
        """
        # 提取多模态特征
        imu = imu_features(sensor)
        emg = emg_features(sensor)

        # 规则引擎评估
        decision = self.rules.evaluate(pose=pose, imu_features=imu, emg_features=emg)

        # 构建标准康复帧
        frame = RehabFrame(
            session_id=self.session_id,
            timestamp_ms=max(pose_timestamp(sensor.timestamp_ms), sensor.timestamp_ms),
            pose=pose,
            imu_features=imu,
            emg_features=emg,
            state=decision.state,
            score=decision.score,
            anomalies=decision.anomalies,
        )
        # 将训练完成次数暂存在 imu_features 字段中，方便前端直接展示。
        # 后续版本可拆分为独立字段以支持更丰富的统计需求。
        frame.imu_features["repetitions"] = decision.repetitions
        return frame


def pose_timestamp(fallback_ms: int) -> int:
    """获取姿态帧的时间戳。

    当前版本中 PoseFrame 尚未包含独立的时间戳字段，
    因此暂时使用传感器帧的时间戳作为融合时间。
    后续版本将在 PoseFrame 中增加时间戳字段以实现精确时间对齐。

    参数:
        fallback_ms: 备选时间戳（传感器帧的时间戳，毫秒）
    返回:
        姿态帧的时间戳（当前直接返回备选时间戳）
    """
    return fallback_ms