from __future__ import annotations

import math
from typing import Any

from shared.rehab_protocol import PoseFrame


# MediaPipe Pose 的人体关键点编号。第一版默认分析右臂，也保留左臂切换能力。
RIGHT_SHOULDER = 12
RIGHT_ELBOW = 14
RIGHT_WRIST = 16
LEFT_SHOULDER = 11
LEFT_ELBOW = 13
LEFT_WRIST = 15


def angle_between_points(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> float:
    """计算三点 A-B-C 在 B 点形成的夹角，单位为度。"""
    ab = (a[0] - b[0], a[1] - b[1])
    cb = (c[0] - b[0], c[1] - b[1])
    ab_len = math.hypot(*ab)
    cb_len = math.hypot(*cb)
    if ab_len == 0 or cb_len == 0:
        return 0.0
    cosine = (ab[0] * cb[0] + ab[1] * cb[1]) / (ab_len * cb_len)
    cosine = max(-1.0, min(1.0, cosine))
    return math.degrees(math.acos(cosine))


def shoulder_raise_angle(
    shoulder: tuple[float, float],
    elbow: tuple[float, float],
) -> float:
    """计算上臂相对“自然下垂方向”的抬举角。

    图像坐标里 y 轴向下，所以手臂自然下垂接近 0 度，水平抬起接近 90 度。
    """
    dx = elbow[0] - shoulder[0]
    dy = elbow[1] - shoulder[1]
    if dx == 0 and dy == 0:
        return 0.0
    return math.degrees(math.atan2(abs(dx), dy)) % 360


def _xy(landmark: dict[str, Any]) -> tuple[float, float]:
    """从 MediaPipe 关键点字典中取出二维坐标。"""
    return float(landmark["x"]), float(landmark["y"])


def pose_from_landmarks(landmarks: list[dict[str, Any]], side: str = "right") -> PoseFrame:
    """把 MediaPipe 的 33 个关键点转换成系统内部的 PoseFrame。"""
    if side == "left":
        shoulder_index, elbow_index, wrist_index = LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST
    else:
        shoulder_index, elbow_index, wrist_index = RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST

    if len(landmarks) <= max(shoulder_index, elbow_index, wrist_index):
        return PoseFrame(landmarks_2d=landmarks)

    shoulder = _xy(landmarks[shoulder_index])
    elbow = _xy(landmarks[elbow_index])
    wrist = _xy(landmarks[wrist_index])
    return PoseFrame(
        shoulder_angle=shoulder_raise_angle(shoulder, elbow),
        elbow_angle=angle_between_points(shoulder, elbow, wrist),
        landmarks_2d=[
            {"x": float(item.get("x", 0.0)), "y": float(item.get("y", 0.0))}
            for item in landmarks
        ],
    )


def synthetic_pose(step: int, period: int = 120) -> PoseFrame:
    """生成模拟上肢训练动作，用于没有摄像头时打通软件闭环。"""
    # 一个周期分为抬手、保持、放下、休息四段，便于网页看到完整状态切换。
    phase = (step % period) / period
    if phase < 0.35:
        shoulder = 15 + 105 * (phase / 0.35)
    elif phase < 0.55:
        shoulder = 120
    elif phase < 0.9:
        shoulder = 120 - 105 * ((phase - 0.55) / 0.35)
    else:
        shoulder = 15

    # 大部分时间肘关节接近伸直，周期末尾故意制造弯肘错误样例。
    elbow = 165.0
    if step % (period * 3) > period * 2.2:
        elbow = 118.0

    return PoseFrame(shoulder_angle=shoulder, elbow_angle=elbow, landmarks_2d=[])


class MediaPipePoseEstimator:
    """真实摄像头姿态估计器；导入时才加载 OpenCV/MediaPipe，降低测试依赖。"""

    def __init__(self, side: str = "right") -> None:
        import cv2  # type: ignore
        import mediapipe as mp  # type: ignore

        self.cv2 = cv2
        self.mp_pose = mp.solutions.pose
        self.side = side
        self.pose = self.mp_pose.Pose(
            static_image_mode=False,
            model_complexity=1,
            enable_segmentation=False,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    def estimate(self, frame: Any) -> PoseFrame:
        """输入 OpenCV BGR 图像帧，输出肩肘角和关键点。"""
        rgb = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB)
        result = self.pose.process(rgb)
        if not result.pose_landmarks:
            return PoseFrame()
        landmarks = [
            {"x": lm.x, "y": lm.y, "visibility": lm.visibility}
            for lm in result.pose_landmarks.landmark
        ]
        return pose_from_landmarks(landmarks, side=self.side)
