from __future__ import annotations

import math
import os
import time
from pathlib import Path
from typing import Any

from shared.rehab_protocol import PoseFrame


# MediaPipe Pose 模型输出的人体关键点索引编号（共 33 个关键点）。
# 第一版默认分析右臂（右侧 shoulder / elbow / wrist），
# 同时保留左臂索引，方便后续扩展切换分析肢体。
RIGHT_SHOULDER = 12   # 右肩关键点索引
RIGHT_ELBOW = 14      # 右肘关键点索引
RIGHT_WRIST = 16      # 右手腕关键点索引
LEFT_SHOULDER = 11    # 左肩关键点索引（预留）
LEFT_ELBOW = 13       # 左肘关键点索引（预留）
LEFT_WRIST = 15       # 左手腕关键点索引（预留）
LEFT_HIP = 23
RIGHT_HIP = 24
AUTO_SWITCH_MARGIN_DEG = 12.0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_pose_model_path(model_path: str | None = None) -> Path | None:
    """解析新版 MediaPipe Tasks API 所需的 pose model 文件路径。"""
    candidates: list[Path] = []
    if model_path:
        candidates.append(Path(model_path).expanduser())

    env_value = os.environ.get("MEDIAPIPE_POSE_MODEL")
    model_from_env = Path(env_value).expanduser() if env_value else None
    if model_from_env is not None:
        candidates.append(model_from_env)

    root = _repo_root()
    candidates.extend(
        [
            root / "models" / "pose_landmarker_full.task",
            root / "models" / "pose_landmarker_lite.task",
            root / "models" / "pose_landmarker_heavy.task",
            root / "models" / "pose_landmarker.task",
            root / "pose_landmarker.task",
        ]
    )

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved
    return None


def angle_between_points(
    a: tuple[float, ...],
    b: tuple[float, ...],
    c: tuple[float, ...],
) -> float:
    """计算三点 A-B-C 在 B 点形成的夹角，单位为度。

    使用向量点积公式计算夹角：
    cos(θ) = (AB·CB) / (|AB| * |CB|)

    参数:
        a: 点 A 的坐标（支持 2D/3D，如图像中手腕）
        b: 点 B 的坐标（支持 2D/3D，如图像中肘关节）
        c: 点 C 的坐标（支持 2D/3D，如图像中肩关节）
    返回:
        A-B-C 三点在 B 点形成的夹角，范围 [0°, 180°]
    """
    a3 = (a[0], a[1], a[2] if len(a) > 2 else 0.0)
    b3 = (b[0], b[1], b[2] if len(b) > 2 else 0.0)
    c3 = (c[0], c[1], c[2] if len(c) > 2 else 0.0)
    # 计算向量 AB 和 CB
    ab = (a3[0] - b3[0], a3[1] - b3[1], a3[2] - b3[2])
    cb = (c3[0] - b3[0], c3[1] - b3[1], c3[2] - b3[2])
    # 计算向量模长
    ab_len = math.sqrt(sum(item * item for item in ab))
    cb_len = math.sqrt(sum(item * item for item in cb))
    # 避免除零：当任一向量长度为 0 时返回 0°
    if ab_len == 0 or cb_len == 0:
        return 0.0
    # 余弦值（钳制到合法范围防止浮点误差）
    cosine = sum(left * right for left, right in zip(ab, cb)) / (ab_len * cb_len)
    cosine = max(-1.0, min(1.0, cosine))
    return math.degrees(math.acos(cosine))


def shoulder_raise_angle(
    shoulder: tuple[float, ...],
    elbow: tuple[float, ...],
) -> float:
    """计算上臂相对"自然下垂方向"的抬举角。

    在图像坐标系中，y 轴指向下方，因此"自然下垂"即从肩关节到肘关节的
    向量方向接近垂直向下。此函数计算该向量与垂直方向的夹角，用于估计
    肩关节的抬举角度。

    参数:
        shoulder: 肩关节的坐标（当前按 2D 图像平面计算）
        elbow: 肘关节的坐标（当前按 2D 图像平面计算）
    返回:
        抬举角度，0°=手臂自然下垂，90°=手臂水平抬起
    """
    dx = elbow[0] - shoulder[0]
    dy = elbow[1] - shoulder[1]
    # 当肩肘坐标重合时返回 0°
    if dx == 0 and dy == 0:
        return 0.0
    # 当前使用普通 RGB 摄像头，仅按图像平面中的左右抬举来估计肩角。
    return math.degrees(math.atan2(abs(dx), dy)) % 360


def shoulder_abduction_angle(
    shoulder: tuple[float, ...],
    elbow: tuple[float, ...],
    trunk_reference: tuple[float, ...] | None = None,
) -> float:
    """计算肩外展角 θ1，0°=自然下垂，90°=水平，180°=过头方向。

    优先使用肩点到髋中点作为躯干纵轴；如果髋部关键点不可用，则退回到
    图像竖直轴，保持无下肢画面时仍能工作。
    """
    if trunk_reference is None:
        trunk_reference = (shoulder[0], shoulder[1] + 1.0)
    return angle_between_points(trunk_reference, shoulder, elbow)


def forearm_raise_angle(
    elbow: tuple[float, ...],
    wrist: tuple[float, ...],
) -> float:
    """计算前臂相对自然下垂方向的抬举角。"""
    return shoulder_raise_angle(elbow, wrist)


def trunk_lean_angle(
    shoulder_midpoint: tuple[float, ...],
    hip_midpoint: tuple[float, ...],
) -> float:
    """计算躯干中线相对竖直轴的侧倾角 θ3。"""
    dx = shoulder_midpoint[0] - hip_midpoint[0]
    dy = shoulder_midpoint[1] - hip_midpoint[1]
    if dx == 0 and dy == 0:
        return 0.0
    return math.degrees(math.atan2(abs(dx), abs(dy)))


def _xy(landmark: dict[str, Any]) -> tuple[float, float]:
    """从 MediaPipe 关键点字典中提取二维坐标 (x, y)。

    参数:
        landmark: MediaPipe 关键点字典，包含 "x"、"y" 等字段
    返回:
        (x, y) 坐标元组
    """
    return float(landmark["x"]), float(landmark["y"])


def _midpoint(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0


def _serializable_landmarks(landmarks: list[dict[str, Any]]) -> list[dict[str, float]]:
    return [
        {
            "x": float(item.get("x", 0.0)),
            "y": float(item.get("y", 0.0)),
            "z": float(item.get("z", 0.0)),
            "visibility": float(item.get("visibility", 0.0)),
        }
        for item in landmarks
    ]


def infer_active_side(
    landmarks: list[dict[str, Any]],
    previous_side: str = "right",
    switch_margin_deg: float = AUTO_SWITCH_MARGIN_DEG,
) -> str:
    """根据左右上肢抬举幅度估计当前活动侧。"""
    if len(landmarks) <= RIGHT_WRIST:
        return previous_side

    left_shoulder = _xy(landmarks[LEFT_SHOULDER])
    left_elbow = _xy(landmarks[LEFT_ELBOW])
    right_shoulder = _xy(landmarks[RIGHT_SHOULDER])
    right_elbow = _xy(landmarks[RIGHT_ELBOW])

    left_angle = shoulder_raise_angle(left_shoulder, left_elbow)
    right_angle = shoulder_raise_angle(right_shoulder, right_elbow)
    if abs(left_angle - right_angle) < switch_margin_deg:
        return previous_side
    return "left" if left_angle > right_angle else "right"


def pose_from_landmarks(landmarks: list[dict[str, Any]], side: str = "right") -> PoseFrame:
    """把 MediaPipe 模型输出的 33 个关键点列表转换成系统内部的 PoseFrame。

    此函数从完整的关键点列表中提取肩、肘、腕三个关键点的坐标，
    计算肩关节抬举角和肘关节屈伸角，并将所有关键点坐标保留在
    landmarks_2d 字段中以备后续扩展使用。

    参数:
        landmarks: MediaPipe 输出的 33 个关键点字典列表
        side: 分析偏侧，可选 "right"（右臂）或 "left"（左臂）
    返回:
        PoseFrame 实例，包含计算出的肩肘角度和关键点坐标
    """
    # 根据偏侧选择对应的关键点索引
    if side == "left":
        shoulder_index, elbow_index, wrist_index = LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST
    else:
        shoulder_index, elbow_index, wrist_index = RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST

    # 如果关键点数量不足，仅返回坐标，角度保持默认值 0
    if len(landmarks) <= max(shoulder_index, elbow_index, wrist_index):
        return PoseFrame(landmarks_2d=_serializable_landmarks(landmarks))

    # 提取肩、肘、腕三个关键点的坐标
    shoulder = _xy(landmarks[shoulder_index])
    elbow = _xy(landmarks[elbow_index])
    wrist = _xy(landmarks[wrist_index])
    trunk_reference = None
    trunk_angle = 0.0
    if len(landmarks) > RIGHT_HIP:
        left_shoulder = _xy(landmarks[LEFT_SHOULDER])
        right_shoulder = _xy(landmarks[RIGHT_SHOULDER])
        left_hip = _xy(landmarks[LEFT_HIP])
        right_hip = _xy(landmarks[RIGHT_HIP])
        shoulder_midpoint = _midpoint(left_shoulder, right_shoulder)
        hip_midpoint = _midpoint(left_hip, right_hip)
        if hip_midpoint[1] > shoulder_midpoint[1]:
            trunk_reference = hip_midpoint
            trunk_angle = trunk_lean_angle(shoulder_midpoint, hip_midpoint)

    return PoseFrame(
        shoulder_angle=shoulder_abduction_angle(shoulder, elbow, trunk_reference=trunk_reference),
        elbow_angle=angle_between_points(shoulder, elbow, wrist),
        forearm_angle=forearm_raise_angle(elbow, wrist),
        trunk_angle=trunk_angle,
        landmarks_2d=_serializable_landmarks(landmarks),
    )


def synthetic_pose(step: int, period: int = 120) -> PoseFrame:
    """生成模拟上肢训练动作的 PoseFrame，用于没有摄像头时打通软件闭环。

    模拟一个完整的训练周期，包含四个阶段：
    1. 抬臂阶段（0-35%）：肩角从 15° 缓慢抬升至 90°
    2. 保持阶段（35-55%）：维持 90° 水平位保持
    3. 放下阶段（55-90%）：从 90° 缓慢回落到 15°
    4. 休息阶段（90-100%）：在 15° 低位休息

    此外，每 3 个周期中会制造一次弯肘异常样例，用于测试规则引擎。

    参数:
        step: 当前步数，随时间递增
        period: 一个完整训练周期的帧数，默认 120 帧
    返回:
        PoseFrame 实例，包含模拟的肩肘角度
    """
    # 计算在周期内的相位位置（0.0 ~ 1.0）
    phase = (step % period) / period
    # 分段生成肩关节抬举角度
    if phase < 0.35:
        # 抬臂阶段：从 15° 线性上升到 90°
        shoulder = 15 + 75 * (phase / 0.35)
    elif phase < 0.55:
        # 保持阶段：维持在 90°
        shoulder = 90
    elif phase < 0.9:
        # 放下阶段：从 90° 线性下降到 15°
        shoulder = 90 - 75 * ((phase - 0.55) / 0.35)
    else:
        # 休息阶段：维持在 15°
        shoulder = 15

    # 大部分时间肘关节接近伸直（165°），周期末尾故意制造弯肘错误
    elbow = 165.0
    if step % (period * 3) > period * 2.2:
        elbow = 118.0

    return PoseFrame(shoulder_angle=shoulder, elbow_angle=elbow, landmarks_2d=[])


class MediaPipePoseEstimator:
    """基于 MediaPipe Pose 模型的实时摄像头姿态估计器。

    使用 MediaPipe 的 BlazePose 模型（运行在 CPU 上，适合边缘端部署），
    从 RGB 摄像头帧中实时检测人体 33 个关键点，然后计算肩肘角度。

    此类的 cv2 和 mediapipe 库在 __init__ 方法中延迟加载，以避免在
    单元测试环境中因缺少摄像头驱动而导入失败。

    属性:
        side: 分析的偏侧（"right" 或 "left"）
        pose: MediaPipe Pose 模型实例
    """

    def __init__(self, side: str = "right", model_path: str | None = None) -> None:
        """初始化姿态估计器，加载 OpenCV 和 MediaPipe 库。

        参数:
            side: 分析的偏侧，"right" 分析右臂，"left" 分析左臂
        """
        import cv2  # type: ignore
        import mediapipe as mp  # type: ignore

        self.cv2 = cv2
        self.mp = mp
        self.side = side
        self.current_side = "right" if side == "auto" else side
        self.uses_tasks_api = not hasattr(mp, "solutions")

        if not self.uses_tasks_api:
            self.mp_pose = mp.solutions.pose
            # 创建 MediaPipe Pose 实例，配置为视频流模式
            self.pose = self.mp_pose.Pose(
                static_image_mode=False,      # 视频流模式（非静态图片）
                model_complexity=1,           # 模型复杂度：0=精简版，1=完整版，2=超大全量版
                enable_segmentation=False,    # 不启用人物分割（节省算力）
                min_detection_confidence=0.5,  # 最小检测置信度阈值
                min_tracking_confidence=0.5,   # 最小跟踪置信度阈值
            )
            return

        resolved_model_path = resolve_pose_model_path(model_path)
        if resolved_model_path is None:
            raise RuntimeError(
                "This MediaPipe package exposes only the Tasks API. Download a pose landmarker "
                "model file such as pose_landmarker_full.task and pass --model-path /path/to/model.task "
                "or set MEDIAPIPE_POSE_MODEL."
            )

        self.model_path = resolved_model_path
        options = mp.tasks.vision.PoseLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(resolved_model_path)),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_poses=1,
        )
        self.pose = mp.tasks.vision.PoseLandmarker.create_from_options(options)

    def estimate(self, frame: Any) -> PoseFrame:
        """输入 OpenCV BGR 图像帧，输出肩肘角度和关键点坐标。

        处理流程：
        1. 将 BGR 帧转换为 RGB（MediaPipe 要求 RGB 输入）
        2. 使用 MediaPipe Pose 模型推理，检测人体关键点
        3. 如果检测到关键点，提取坐标并计算肩肘角度
        4. 返回包含角度和坐标的 PoseFrame

        参数:
            frame: OpenCV 读取的 BGR 图像帧（numpy 数组）
        返回:
            PoseFrame 实例；如果未检测到人体，返回含默认值的 PoseFrame
        """
        if self.uses_tasks_api:
            rgb = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB)
            image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
            result = self.pose.detect_for_video(image, time.monotonic_ns() // 1_000_000)
            if not result.pose_landmarks:
                return PoseFrame()

            landmarks = [
                {
                    "x": float(lm.x or 0.0),
                    "y": float(lm.y or 0.0),
                    "z": float(lm.z or 0.0),
                    "visibility": float(lm.visibility or 0.0),
                }
                for lm in result.pose_landmarks[0]
            ]
            side = self._resolve_side(landmarks)
            return pose_from_landmarks(landmarks, side=side)

        # BGR 转 RGB（MediaPipe 要求）
        rgb = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB)
        result = self.pose.process(rgb)
        # 未检测到关键点时返回空 PoseFrame
        if not result.pose_landmarks:
            return PoseFrame()
        # 提取所有关键点的坐标和可见度信息
        landmarks = [
            {"x": lm.x, "y": lm.y, "z": lm.z, "visibility": lm.visibility}
            for lm in result.pose_landmarks.landmark
        ]
        side = self._resolve_side(landmarks)
        return pose_from_landmarks(landmarks, side=side)

    def _resolve_side(self, landmarks: list[dict[str, Any]]) -> str:
        if self.side != "auto":
            self.current_side = self.side
            return self.side
        self.current_side = infer_active_side(landmarks, previous_side=self.current_side)
        return self.current_side
