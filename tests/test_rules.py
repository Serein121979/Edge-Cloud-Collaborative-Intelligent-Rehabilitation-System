import unittest

from edge.rehab_edge.rules import RehabRuleConfig, RehabStateMachine
from shared.rehab_protocol import PoseFrame


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
        decision = rules.evaluate(PoseFrame(shoulder_angle=55, elbow_angle=100))
        self.assertEqual(decision.state, "incorrect")
        self.assertIn("elbow_not_extended", decision.anomalies)

    def test_trunk_compensation_is_anomaly(self):
        """IMU roll 过大代表躯干代偿，应判定为 anomaly。"""
        rules = RehabStateMachine()
        decision = rules.evaluate(
            PoseFrame(shoulder_angle=55, elbow_angle=165),
            imu_features={"roll": 42},
        )
        self.assertEqual(decision.state, "anomaly")
        self.assertIn("trunk_compensation", decision.anomalies)


if __name__ == "__main__":
    # 允许直接 python tests/test_rules.py 运行。
    unittest.main()
