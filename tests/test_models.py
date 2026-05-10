import unittest

from shared.rehab_protocol import RehabFrame, SensorFrame


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
            "pose": {"shoulder_angle": 10, "elbow_angle": 180, "landmarks_2d": []},
            "imu_features": {},
            "emg_features": {},
            "state": "bad",
            "score": 0,
            "anomalies": [],
        }
        with self.assertRaises(ValueError):
            RehabFrame.from_dict(payload)


if __name__ == "__main__":
    # 允许直接 python tests/test_models.py 运行。
    unittest.main()
