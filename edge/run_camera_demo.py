"""Run the edge demo with a real USB camera and MediaPipe Pose.

This entry point keeps the existing edge pipeline intact:
camera frame -> MediaPipe Pose -> RehabFusionPipeline -> JSONL + cloud upload.
IMU/sEMG values are simulated by default, so the Logitech camera can be tested
before the ESP32 sensor bridge is connected.
"""

from __future__ import annotations

import argparse
import os
import time
from collections.abc import Iterator

from edge.rehab_edge.fusion import RehabFusionPipeline
from edge.rehab_edge.pose import MediaPipePoseEstimator
from edge.rehab_edge.recorder import JsonlRecorder
from edge.rehab_edge.sensors import SimulatedSensorReader
from edge.rehab_edge.uploader import CloudUploader
from shared.rehab_protocol import SensorFrame, make_session_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run rehabilitation demo with a real USB camera.")
    parser.add_argument("--camera-index", type=int, default=0, help="OpenCV camera index, usually 0 or 1.")
    parser.add_argument("--side", choices=("left", "right"), default="right", help="Arm side to analyze.")
    parser.add_argument("--cloud-url", default="http://127.0.0.1:8000", help="Local cloud API base URL.")
    parser.add_argument("--participant", default="camera_demo", help="Participant ID stored in the session.")
    parser.add_argument("--frames", type=int, default=0, help="Stop after N fused frames. 0 means run until q/Ctrl+C.")
    parser.add_argument("--fps", type=float, default=10.0, help="Target fusion/upload rate.")
    parser.add_argument("--width", type=int, default=1280, help="Requested camera width.")
    parser.add_argument("--height", type=int, default=720, help="Requested camera height.")
    parser.add_argument("--no-preview", action="store_true", help="Disable OpenCV preview window.")
    return parser.parse_args()


def open_camera(cv2, camera_index: int, width: int, height: int):
    backend = cv2.CAP_DSHOW if os.name == "nt" else 0
    capture = cv2.VideoCapture(camera_index, backend)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"Cannot open camera index {camera_index}. Try --camera-index 1 or 2.")
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    return capture


def next_sensor_frame(sensor_iter: Iterator[SensorFrame]) -> SensorFrame:
    return next(sensor_iter)


def main() -> None:
    args = parse_args()

    try:
        import cv2  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "OpenCV is not installed. Use Python 3.10/3.11 and run: "
            "pip install -r requirements-vision.txt"
        ) from exc

    try:
        estimator = MediaPipePoseEstimator(side=args.side)
    except ImportError as exc:
        raise SystemExit(
            "MediaPipe is not installed. Use Python 3.10/3.11 and run: "
            "pip install -r requirements-vision.txt"
        ) from exc

    session_id = make_session_id("camera")
    fusion = RehabFusionPipeline(session_id=session_id)
    recorder = JsonlRecorder(f"data/{session_id}.jsonl")
    uploader = CloudUploader(base_url=args.cloud_url)
    sensor_iter = iter(SimulatedSensorReader(interval_s=max(0.001, 1.0 / args.fps)))

    print(f"[camera] session_id: {session_id}")
    if uploader.create_session(session_id, participant=args.participant):
        print("[camera] cloud session created")
    else:
        print("[camera] cloud is not reachable; keeping local JSONL only")

    capture = open_camera(cv2, args.camera_index, args.width, args.height)
    frame_count = 0
    last_report = time.time()

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                print("[camera] failed to read camera frame")
                time.sleep(0.1)
                continue

            pose = estimator.estimate(frame)
            sensor_frame = next_sensor_frame(sensor_iter)
            rehab = fusion.fuse(pose, sensor_frame)
            recorder.append(rehab.to_dict())
            uploader.upload_frame(rehab)

            if not args.no_preview:
                cv2.putText(
                    frame,
                    f"shoulder {pose.shoulder_angle:.0f}  elbow {pose.elbow_angle:.0f}  {rehab.state}",
                    (24, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.0,
                    (40, 220, 80),
                    2,
                    cv2.LINE_AA,
                )
                cv2.imshow("Rehab Camera Demo - press q to quit", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            frame_count += 1
            if time.time() - last_report >= 1.0:
                print(
                    f"[camera] frame {frame_count:>4} | "
                    f"shoulder {pose.shoulder_angle:5.1f} | "
                    f"elbow {pose.elbow_angle:5.1f} | "
                    f"state {rehab.state:>9} | "
                    f"score {rehab.score:5.1f} | "
                    f"anomalies {rehab.anomalies}"
                )
                last_report = time.time()

            if args.frames and frame_count >= args.frames:
                break
    except KeyboardInterrupt:
        print("\n[camera] stopped by user")
    finally:
        capture.release()
        if not args.no_preview:
            cv2.destroyAllWindows()

    print(f"[camera] done, processed {frame_count} frames")
    print(f"[camera] log saved to data/{session_id}.jsonl")


if __name__ == "__main__":
    main()
