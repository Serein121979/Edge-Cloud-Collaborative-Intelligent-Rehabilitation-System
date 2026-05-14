"""
test_rules.py —— 规则状态机单元测试。

测试正常动作周期（抬起→保持→放下→完成）以及异常动作检测
（弯肘、躯干代偿），确保规则引擎输出正确状态和异常标记。
"""

import unittest

from edge.rehab_edge.rules import RehabRuleConfig, RehabStateMachine
from shared.rehab_protocol import PoseFrame


def make_landmarks(
    right_shoulder: tuple[float, float],
    left_shoulder: tuple[float, float] = (0.40, 0.40),
    right_hip: tuple[float, float] = (0.50, 0.70),
    left_hip: tuple[float, float] = (0.40, 0.70),
) -> list[dict[str, float]]:
    landmarks = [{"x": 0.0, "y": 0.0} for _ in range(33)]
    landmarks[11] = {"x": left_shoulder[0], "y": left_shoulder[1]}
    landmarks[12] = {"x": right_shoulder[0], "y": right_shoulder[1]}
    landmarks[23] = {"x": left_hip[0], "y": left_hip[1]}
    landmarks[24] = {"x": right_hip[0], "y": right_hip[1]}
    return landmarks


class RuleTests(unittest.TestCase):
    """规则状态机测试，覆盖正常动作和典型错误动作。"""

    def test_normal_repetition_completes(self):
        """抬起、保持、放下后应计为完成一次。"""
        rules = RehabStateMachine(RehabRuleConfig(hold_frames_required=2))
        states = []
        for angle in [10, 35, 65, 92, 95, 70, 40, 20]:
            decision = rules.evaluate(PoseFrame(shoulder_angle=angle, elbow_angle=165))
            states.append(decision.state)
        self.assertIn("completed", states)
        self.assertEqual(rules.repetitions, 1)

    def test_bent_elbow_is_incorrect(self):
        """抬手时弯肘应判定为 incorrect。"""
        rules = RehabStateMachine()
        decision = rules.evaluate(PoseFrame(shoulder_angle=55, elbow_angle=155))
        self.assertEqual(decision.state, "incorrect")
        self.assertIn("elbow_not_extended", decision.anomalies)

    def test_elbow_at_straight_threshold_is_not_incorrect(self):
        """肘角达到 160° 时，应视为满足伸直要求。"""
        rules = RehabStateMachine()
        decision = rules.evaluate(PoseFrame(shoulder_angle=55, elbow_angle=160))
        self.assertNotIn("elbow_not_extended", decision.anomalies)

    def test_safety_stop_has_highest_priority(self):
        """肩角超过 150° 时，应触发安全停止异常。"""
        rules = RehabStateMachine()
        decision = rules.evaluate(PoseFrame(shoulder_angle=151, elbow_angle=165))
        self.assertEqual(decision.state, "anomaly")
        self.assertIn("safety_stop", decision.anomalies)

    def test_target_tolerance_allows_95_degrees_hold(self):
        """目标容差内的 95° 不应被判为过顶代偿。"""
        rules = RehabStateMachine(RehabRuleConfig(hold_frames_required=1))
        decision = rules.evaluate(PoseFrame(shoulder_angle=95, elbow_angle=165))
        self.assertEqual(decision.state, "holding")
        self.assertNotIn("shoulder_over_target_compensation", decision.anomalies)

    def test_shoulder_over_target_is_anomaly(self):
        """明显超过水平目标后，应判定为肩部过顶代偿。"""
        rules = RehabStateMachine()
        decision = rules.evaluate(PoseFrame(shoulder_angle=105, elbow_angle=165))
        self.assertEqual(decision.state, "anomaly")
        self.assertIn("shoulder_over_target_compensation", decision.anomalies)

    def test_pose_trunk_angle_is_anomaly(self):
        """PoseFrame 中的 θ3 超过 15° 时，应判为躯干代偿。"""
        rules = RehabStateMachine()
        decision = rules.evaluate(PoseFrame(shoulder_angle=55, elbow_angle=165, trunk_angle=16))
        self.assertEqual(decision.state, "anomaly")
        self.assertIn("trunk_compensation", decision.anomalies)

    def test_forearm_only_lift_is_incorrect(self):
        """上臂未充分抬起但小臂抬很高时，应判定为前臂代偿。"""
        rules = RehabStateMachine()
        decision = rules.evaluate(PoseFrame(shoulder_angle=25, elbow_angle=105, forearm_angle=85))
        self.assertEqual(decision.state, "incorrect")
        self.assertIn("forearm_lift_compensation", decision.anomalies)

    def test_forearm_too_high_when_upper_arm_is_level_is_incorrect(self):
        """上臂已接近水平但小臂额外上翘过多时，应判定为前臂代偿。"""
        rules = RehabStateMachine()
        decision = rules.evaluate(PoseFrame(shoulder_angle=85, elbow_angle=125, forearm_angle=130))
        self.assertEqual(decision.state, "incorrect")
        self.assertIn("forearm_lift_compensation", decision.anomalies)

    def test_trunk_compensation_is_anomaly(self):
        """IMU roll 过大代表躯干代偿，应判定为 anomaly。"""
        rules = RehabStateMachine()
        decision = rules.evaluate(
            PoseFrame(shoulder_angle=55, elbow_angle=165),
            imu_features={"roll": 42},
        )
        self.assertEqual(decision.state, "anomaly")
        self.assertIn("trunk_compensation", decision.anomalies)

    def test_landmark_trunk_compensation_is_anomaly(self):
        """没有 IMU 时，摄像头关键点的肩-髋侧倾也应能判出躯干代偿。"""
        rules = RehabStateMachine()
        pose = PoseFrame(
            shoulder_angle=60,
            elbow_angle=165,
            landmarks_2d=make_landmarks(right_shoulder=(0.68, 0.44), right_hip=(0.50, 0.70)),
        )
        decision = rules.evaluate(pose)
        self.assertEqual(decision.state, "anomaly")
        self.assertIn("trunk_compensation", decision.anomalies)

    def test_shoulder_hike_is_anomaly(self):
        """活动侧肩峰明显抬高时，应判为耸肩代偿。"""
        rules = RehabStateMachine(RehabRuleConfig(arm_side="right"))
        pose = PoseFrame(
            shoulder_angle=70,
            elbow_angle=165,
            landmarks_2d=make_landmarks(
                right_shoulder=(0.52, 0.28),
                left_shoulder=(0.40, 0.40),
                right_hip=(0.52, 0.72),
            ),
        )
        decision = rules.evaluate(pose)
        self.assertEqual(decision.state, "anomaly")
        self.assertIn("shoulder_hike_compensation", decision.anomalies)

    def test_left_side_shoulder_hike_is_anomaly(self):
        """左侧训练时，也应按左肩/左髋判定耸肩代偿。"""
        rules = RehabStateMachine(RehabRuleConfig(arm_side="left"))
        pose = PoseFrame(
            shoulder_angle=70,
            elbow_angle=165,
            landmarks_2d=make_landmarks(
                right_shoulder=(0.60, 0.40),
                left_shoulder=(0.40, 0.26),
                left_hip=(0.40, 0.72),
            ),
        )
        decision = rules.evaluate(pose)
        self.assertEqual(decision.state, "anomaly")
        self.assertIn("shoulder_hike_compensation", decision.anomalies)

    def test_switching_arm_side_resets_short_term_motion_state(self):
        """自动切换左右侧时，应清空短时动作阶段缓存，避免看起来像延迟。"""
        rules = RehabStateMachine(RehabRuleConfig(arm_side="right"))
        rules.previous_angle = 70.0
        rules.has_reached_target = True
        rules.hold_frames = 4
        rules.set_arm_side("left")
        self.assertIsNone(rules.previous_angle)
        self.assertFalse(rules.has_reached_target)
        self.assertEqual(rules.hold_frames, 0)


if __name__ == "__main__":
    # 允许直接 python tests/test_rules.py 运行。
    unittest.main()
