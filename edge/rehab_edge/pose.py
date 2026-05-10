from __future__ import annotations
import math
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


def angle_between_points(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> float:
    """计算三点 A-B-C 在 B 点形成的夹角，单位为度。

    使用向量点积公式计算夹角：
    cos(θ) = (AB·CB) / (|AB| * |CB|)

    参数:
        a: 点 A 的 (x, y) 坐标（如图像中手腕）
        b: 点 B 的 (x, y) 坐标（如图像中肘关节）
        c: 点 C 的 (x, y) 坐标（如图像中肩关节）
    返回:
        A-B-C 三点在 B 点形成的夹角，范围 [0°, 180°]
    """
    # 计算向量 AB 和 CB
    ab = (a[0] - b[0], a[1] - b[1])
    cb = (c[0] - b[0], c[1] - b[1])
    # 计算向量模长
    ab_len = math.hypot(*ab)
    cb_len = math.hypot(*cb)
    # 避免除零：当任一向量长度为 0 时返回 0°
    if ab_len == 0 or cb_len == 0:
        return 0.0
    # 余弦值（钳制到合法范围防止浮点误差）
    cosine = (ab[0] * cb[0] + ab[1] * cb[1]) / (ab_len * cb_len)
    cosine = max(-1.0, min(1.0, cosine))
    return math.degrees(math.acos(cosine))


def shoulder_raise_angle(
    shoulder: tuple[float, float],
    elbow: tuple[float, float],
) -> float:
    """计算上臂相对"自然下垂方向"的抬举角。

    在图像坐标系中，y 轴指向下方，因此"自然下垂"即从肩关节到肘关节的
    向量方向接近垂直向下。此函数计算该向量与垂直方向的夹角，用于估计
    肩关节的抬举角度。

    参数:
        shoulder: 肩关节的 (x, y) 坐标
        elbow: 肘关节的 (x, y) 坐标
    返回:
        抬举角度，0°=手臂自然下垂，90°=手臂水平抬起
    """
    dx = elbow[0] - shoulder[0]
    dy = elbow[1] - shoulder[1]
    # 当肩肘坐标重合时返回 0°
    if dx == 0 and dy == 0:
        return 0.0
    # 使用 atan2 计算水平偏移与垂直偏移的比值，再取绝对值得到抬举角
    return math.degrees(math.atan2(abs(dx), dy)) % 360


def _xy(landmark: dict[str, Any]) -> tuple[float, float]:
    """从 MediaPipe 关键点字典中提取二维坐标 (x, y)。

    参数:
        landmark: MediaPipe 关键点字典，包含 "x"、"y" 等字段
    返回:
        (x, y) 坐标元组
    """
    return float(landmark["x"]), float(landmark["y"])


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
        return PoseFrame(landmarks_2d=landmarks)

    # 提取肩、肘、腕三个关键点的坐标
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
    """生成模拟上肢训练动作的 PoseFrame，用于没有摄像头时打通软件闭环。

    模拟一个完整的训练周期，包含四个阶段：
    1. 抬臂阶段（0-35%）：肩角从 15° 缓慢抬升至 120°
    2. 保持阶段（35-55%）：维持 120° 高位保持
    3. 放下阶段（55-90%）：从 120° 缓慢回落到 15°
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
        # 抬臂阶段：从 15° 线性上升到 120°
        shoulder = 15 + 105 * (phase / 0.35)
    elif phase < 0.55:
        # 保持阶段：维持在 120°
        shoulder = 120
    elif phase < 0.9:
        # 放下阶段：从 120° 线性下降到 15°
        shoulder = 120 - 105 * ((phase - 0.55) / 0.35)
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

    def __init__(self, side: str = "right") -> None:
        """初始化姿态估计器，加载 OpenCV 和 MediaPipe 库。

        参数:
            side: 分析的偏侧，"right" 分析右臂，"left" 分析左臂
        """
        import cv2  # type: ignore
        import mediapipe as mp  # type: ignore

        self.cv2 = cv2
        self.mp_pose = mp.solutions.pose
        self.side = side
        # 创建 MediaPipe Pose 实例，配置为视频流模式
        self.pose = self.mp_pose.Pose(
            static_image_mode=False,      # 视频流模式（非静态图片）
            model_complexity=1,           # 模型复杂度：0=精简版，1=完整版，2=超大全量版
            enable_segmentation=False,    # 不启用人物分割（节省算力）
            min_detection_confidence=0.5,  # 最小检测置信度阈值
            min_tracking_confidence=0.5,   # 最小跟踪置信度阈值
        )

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
        # BGR 转 RGB（MediaPipe 要求）
        rgb = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB)
        result = self.pose.process(rgb)
        # 未检测到关键点时返回空 PoseFrame
        if not result.pose_landmarks:
            return PoseFrame()
        # 提取所有关键点的坐标和可见度信息
        landmarks = [
            {"x": lm.x, "y": lm.y, "visibility": lm.visibility}
            for lm in result.pose_landmarks.landmark
        ]
        return pose_from_landmarks(landmarks, side=self.side)