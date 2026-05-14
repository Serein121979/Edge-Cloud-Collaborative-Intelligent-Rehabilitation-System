"""
test_models.py —— 共享数据协议单元测试。

测试 RehabFrame 和 SensorFrame 的序列化/反序列化、
字段类型一致性以及非法输入校验。
"""

import unittest

from shared.rehab_protocol import PoseFrame, RehabFrame, SensorFrame


class ModelTests(unittest.TestCase):
    """共享数据协议测试，确保边缘端和云端理解同一种 JSON。"""

    def test_sensor_frame_round_trip(self):
        """ESP32 传感器帧解析后再导出，数值类型应统一为 float。"""
        payload = {
            "timestamp_ms": 1,
            "device": "esp32_s3",
            "imu": {"roll": 1, "pitch": 2, "yaw": 3, "acc": [0, 0, 9.8], "gyro": [1, 2, 3]},
            "emg": {"channels": [100], "rms": [90]},
        }
        frame = SensorFrame.from_dict(payload)
        self.assertEqual(frame.to_dict()["imu"]["acc"], [0.0, 0.0, 9.8])
        self.assertEqual(frame.to_dict()["emg"]["rms"], [90.0])

    def test_rehab_frame_rejects_invalid_state(self):
        """云端收到非法状态时应拒绝，避免前端出现未知状态。"""
        payload = {
            "session_id": "s",
            "timestamp_ms": 1,
            "pose": {"shoulder_angle": 10, "elbow_angle": 180, "forearm_angle": 0, "landmarks_2d": []},
            "imu_features": {},
            "emg_features": {},
            "state": "bad",
            "score": 0,
            "anomalies": [],
        }
        with self.assertRaises(ValueError):
            RehabFrame.from_dict(payload)

    def test_pose_frame_round_trip_includes_trunk_angle(self):
        """摄像头姿态帧应保留 θ3 躯干侧倾角，并兼容缺省值。"""
        pose = PoseFrame.from_dict({"shoulder_angle": 90, "elbow_angle": 170, "trunk_angle": 12})
        self.assertEqual(pose.to_dict()["trunk_angle"], 12.0)
        self.assertEqual(PoseFrame.from_dict({}).trunk_angle, 0.0)


if __name__ == "__main__":
    # 允许直接 python tests/test_models.py 运行。
    unittest.main()
