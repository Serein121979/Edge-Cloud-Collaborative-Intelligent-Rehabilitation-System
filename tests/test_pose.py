"""
test_pose.py —— 姿态角度计算单元测试。

测试 angle_between_points 和 shoulder_raise_angle 的角度计算逻辑，
确保标准几何姿势（共线、水平）返回预期的角度值。
"""

import unittest

from edge.rehab_edge.pose import angle_between_points, shoulder_raise_angle


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


if __name__ == "__main__":
    # 允许直接 python tests/test_pose.py 运行。
    unittest.main()