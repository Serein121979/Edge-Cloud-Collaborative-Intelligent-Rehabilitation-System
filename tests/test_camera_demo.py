from types import SimpleNamespace
import unittest

from edge.run_camera_demo import coaching_hint
from shared.rehab_protocol import PoseFrame


class CameraDemoHintTests(unittest.TestCase):
    def test_idle_hint_mentions_gap_to_target(self):
        rehab = SimpleNamespace(anomalies=[], state="idle", score=22.0)
        hint = coaching_hint(rehab, PoseFrame(shoulder_angle=10.0, elbow_angle=170.0))
        self.assertIn("还差", hint)
        self.assertIn("80", hint)

    def test_holding_too_high_hint_mentions_over_target(self):
        rehab = SimpleNamespace(anomalies=[], state="holding", score=35.0)
        hint = coaching_hint(rehab, PoseFrame(shoulder_angle=150.0, elbow_angle=170.0))
        self.assertIn("抬得偏高", hint)

    def test_raising_low_angle_hint_mentions_gap_to_target(self):
        rehab = SimpleNamespace(anomalies=[], state="raising", score=55.0)
        hint = coaching_hint(rehab, PoseFrame(shoulder_angle=50.0, elbow_angle=170.0))
        self.assertIn("还差", hint)

    def test_forearm_compensation_hint_mentions_forearm(self):
        rehab = SimpleNamespace(anomalies=["forearm_lift_compensation"], state="incorrect", score=35.0)
        hint = coaching_hint(rehab, PoseFrame(shoulder_angle=25.0, elbow_angle=105.0, forearm_angle=85.0))
        self.assertIn("小臂", hint)

    def test_safety_stop_hint_mentions_stop(self):
        rehab = SimpleNamespace(anomalies=["safety_stop"], state="anomaly", score=0.0)
        hint = coaching_hint(rehab, PoseFrame(shoulder_angle=155.0, elbow_angle=170.0))
        self.assertIn("立即停止", hint)

    def test_low_angle_fallback_does_not_mention_natural_rest(self):
        rehab = SimpleNamespace(anomalies=[], state="unknown", score=50.0)
        hint = coaching_hint(rehab, PoseFrame(shoulder_angle=20.0, elbow_angle=170.0))
        self.assertIn("还差", hint)
        self.assertNotIn("自然下垂", hint)


if __name__ == "__main__":
    unittest.main()
