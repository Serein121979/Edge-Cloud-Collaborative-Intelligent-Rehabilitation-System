from __future__ import annotations

from shared.rehab_protocol import PoseFrame, RehabFrame, SensorFrame

from .rules import RehabStateMachine
from .sensors import emg_features, imu_features


class RehabFusionPipeline:
    """边缘端融合流水线：把摄像头姿态和 ESP32 传感器数据合成 RehabFrame。"""

    def __init__(self, session_id: str, rules: RehabStateMachine | None = None) -> None:
        self.session_id = session_id
        self.rules = rules or RehabStateMachine()

    def fuse(self, pose: PoseFrame, sensor: SensorFrame) -> RehabFrame:
        """融合一帧姿态和一帧传感器数据，并执行规则判断。"""
        imu = imu_features(sensor)
        emg = emg_features(sensor)
        decision = self.rules.evaluate(pose=pose, imu_features=imu, emg_features=emg)
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
        # 完成次数暂存在 imu_features 中，前端可以直接展示；后期可拆成独立字段。
        frame.imu_features["repetitions"] = decision.repetitions
        return frame


def pose_timestamp(fallback_ms: int) -> int:
    """当前 PoseFrame 没有独立时间戳，先使用传感器时间作为融合时间。"""
    return fallback_ms
