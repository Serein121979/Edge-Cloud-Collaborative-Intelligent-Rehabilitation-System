"""
test_pose.py —— 姿态角度计算单元测试。

测试 angle_between_points 和 shoulder_raise_angle 的角度计算逻辑，
确保标准几何姿势（共线、水平）返回预期的角度值。
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from edge.rehab_edge.pose import (
    angle_between_points,
    forearm_raise_angle,
    infer_active_side,
    pose_from_landmarks,
    resolve_pose_model_path,
    shoulder_abduction_angle,
    shoulder_raise_angle,
    trunk_lean_angle,
)


class PoseTests(unittest.TestCase):
    """姿态角度计算测试。"""

    def test_elbow_angle_straight(self):
        """三点共线时，肘关节角应接近 180 度。"""
        angle = angle_between_points((0, 0), (1, 0), (2, 0))
        self.assertAlmostEqual(angle, 180.0)

    def test_shoulder_angle_horizontal(self):
        """手臂水平抬起时，肩关节抬举角应接近 90 度。"""
        angle = shoulder_raise_angle((0, 0), (1, 0))
        self.assertAlmostEqual(angle, 90.0)

    def test_forearm_angle_horizontal(self):
        """前臂水平抬起时，前臂抬举角应接近 90 度。"""
        angle = forearm_raise_angle((0, 0), (1, 0))
        self.assertAlmostEqual(angle, 90.0)

    def test_shoulder_abduction_uses_trunk_axis(self):
        """肩外展角应按肩-髋躯干轴计算，水平外展接近 90 度。"""
        angle = shoulder_abduction_angle((0.5, 0.4), (0.8, 0.4), trunk_reference=(0.5, 0.8))
        self.assertAlmostEqual(angle, 90.0)

    def test_trunk_lean_angle_from_midpoints(self):
        """肩髋中线偏离竖直方向时，应得到躯干侧倾角。"""
        angle = trunk_lean_angle((0.6, 0.4), (0.5, 0.8))
        self.assertAlmostEqual(angle, 14.036, places=3)

    def test_elbow_angle_straight_in_3d(self):
        """3D 共线时，肘关节角应接近 180 度。"""
        angle = angle_between_points((0, 0, -1), (0, 0, 0), (0, 0, 1))
        self.assertAlmostEqual(angle, 180.0)

    def test_pose_from_landmarks_supports_left_side(self):
        """左侧训练时，应从左肩-左肘-左腕读取角度。"""
        landmarks = [{"x": 0.0, "y": 0.0} for _ in range(33)]
        landmarks[11] = {"x": 0.5, "y": 0.5}
        landmarks[13] = {"x": 0.3, "y": 0.5}
        landmarks[15] = {"x": 0.1, "y": 0.5}
        pose = pose_from_landmarks(landmarks, side="left")
        self.assertAlmostEqual(pose.shoulder_angle, 90.0)
        self.assertAlmostEqual(pose.elbow_angle, 180.0)
        self.assertAlmostEqual(pose.forearm_angle, 90.0)

    def test_pose_from_landmarks_outputs_trunk_angle(self):
        """完整关键点输入时，应输出 θ3 躯干侧倾角。"""
        landmarks = [{"x": 0.0, "y": 0.0} for _ in range(33)]
        landmarks[11] = {"x": 0.4, "y": 0.4}
        landmarks[12] = {"x": 0.6, "y": 0.4}
        landmarks[13] = {"x": 0.2, "y": 0.4}
        landmarks[15] = {"x": 0.0, "y": 0.4}
        landmarks[23] = {"x": 0.3, "y": 0.8}
        landmarks[24] = {"x": 0.5, "y": 0.8}
        pose = pose_from_landmarks(landmarks, side="left")
        self.assertGreater(pose.trunk_angle, 0.0)
        self.assertAlmostEqual(pose.shoulder_angle, 90.0)

    def test_infer_active_side_prefers_left_when_left_arm_is_raised(self):
        """自动侧别应优先选择抬得更高的一侧。"""
        landmarks = [{"x": 0.0, "y": 0.0} for _ in range(33)]
        landmarks[11] = {"x": 0.5, "y": 0.5}
        landmarks[13] = {"x": 0.3, "y": 0.5}
        landmarks[12] = {"x": 0.5, "y": 0.5}
        landmarks[14] = {"x": 0.5, "y": 0.8}
        self.assertEqual(infer_active_side(landmarks, previous_side="right"), "left")

    def test_resolve_pose_model_path_with_explicit_existing_file(self):
        """显式传入存在的 .task 文件路径时，应返回该文件。"""
        with TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "pose_landmarker_full.task"
            model_path.write_bytes(b"test")
            self.assertEqual(resolve_pose_model_path(str(model_path)), model_path.resolve())

    def test_resolve_pose_model_path_missing_file_falls_back_to_default_model(self):
        """显式路径不存在时，应继续回退查找项目默认模型路径。"""
        resolved = resolve_pose_model_path("/tmp/definitely_missing_pose_landmarker.task")
        if resolved is not None:
            self.assertTrue(resolved.name.startswith("pose_landmarker"))


if __name__ == "__main__":
    # 允许直接 python tests/test_pose.py 运行。
    unittest.main()
