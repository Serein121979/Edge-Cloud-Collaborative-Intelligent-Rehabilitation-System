import unittest

from shared.rehab_protocol import EmgSample, ImuSample, SensorFrame, VALID_STATES

try:
    from fastapi.testclient import TestClient

    from edge.rehab_edge.fusion import RehabFusionPipeline
    from edge.run_controller_node import ControllerState, create_controller_app, fuse_latest_pose
except ModuleNotFoundError as exc:  # pragma: no cover - depends on local env install state
    raise unittest.SkipTest(f"controller HTTP tests require FastAPI: {exc}") from exc


class ControllerNodeTests(unittest.TestCase):
    def test_post_pose_saves_latest_pose(self):
        state = ControllerState()
        client = TestClient(create_controller_app(state))

        response = client.post(
            "/api/pose",
            json={
                "shoulder_angle": 90,
                "elbow_angle": 170,
                "forearm_angle": 80,
                "trunk_angle": 3,
                "landmarks_2d": [],
            },
        )

        self.assertEqual(response.status_code, 200)
        pose, has_pose, updated_at_ms = state.latest_pose_or_default()
        self.assertTrue(has_pose)
        self.assertGreater(updated_at_ms, 0)
        self.assertEqual(pose.shoulder_angle, 90.0)
        self.assertEqual(pose.elbow_angle, 170.0)

    def test_controller_fuses_latest_pose_with_sensor_frame(self):
        state = ControllerState()
        client = TestClient(create_controller_app(state))
        client.post(
            "/api/pose",
            json={
                "shoulder_angle": 88,
                "elbow_angle": 172,
                "forearm_angle": 84,
                "trunk_angle": 2,
                "landmarks_2d": [],
            },
        )
        sensor = SensorFrame(
            timestamp_ms=1000,
            imu=ImuSample(roll=0, pitch=0, yaw=0, acc=[0, 0, 9.8], gyro=[0, 0, 0]),
            emg=EmgSample(channels=[120], rms=[120]),
        )

        rehab, has_pose = fuse_latest_pose(state, RehabFusionPipeline("test_session"), sensor)

        self.assertTrue(has_pose)
        self.assertIn(rehab.state, VALID_STATES)
        self.assertEqual(rehab.pose.shoulder_angle, 88.0)
        self.assertIn("rms_mean", rehab.emg_features)


if __name__ == "__main__":
    unittest.main()
