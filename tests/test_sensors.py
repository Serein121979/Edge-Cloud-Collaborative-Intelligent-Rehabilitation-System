import unittest

from edge.rehab_edge.sensors import SerialSensorReader


class FakeSerial:
    def __init__(self, lines):
        self._lines = list(lines)

    def readline(self):
        if self._lines:
            return self._lines.pop(0)
        return b'{"timestamp_ms":4,"device":"esp32_s3","imu":{},"emg":{"channels":[9],"rms":[9]}}\n'


class SerialSensorReaderTests(unittest.TestCase):
    def test_read_skips_empty_bad_and_partial_lines(self):
        reader = SerialSensorReader(
            port="unused",
            serial_obj=FakeSerial(
                [
                    b"\n",
                    b"\x00\x00",
                    b'{"timestamp_ms":1',
                    b'{"timestamp_ms":2,"device":"esp32_s3","imu":{"roll":1},"emg":{"channels":[7],"rms":[8]}}\n',
                ]
            ),
        )

        frame = reader.read()

        self.assertEqual(frame.timestamp_ms, 2)
        self.assertEqual(frame.device, "esp32_s3")
        self.assertEqual(frame.imu.roll, 1.0)
        self.assertEqual(frame.emg.channels, [7.0])


if __name__ == "__main__":
    unittest.main()
