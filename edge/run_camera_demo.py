"""Run the single-machine camera demo with MediaPipe Pose.

This entry point keeps the existing edge pipeline intact:
camera frame -> MediaPipe Pose -> RehabFusionPipeline -> JSONL + cloud upload.
IMU/sEMG values are simulated by default, but a real ESP32 serial stream can be
attached with --serial-port.
"""

from __future__ import annotations

import argparse
import os
import threading
import time

from edge.rehab_edge.fusion import RehabFusionPipeline
from edge.rehab_edge.pose import (
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
    MediaPipePoseEstimator,
)
from edge.rehab_edge.recorder import JsonlRecorder
from edge.rehab_edge.rules import RehabRuleConfig, RehabStateMachine
from edge.rehab_edge.sensors import SerialSensorReader, SimulatedSensorReader
from edge.rehab_edge.uploader import CloudUploader
from shared.rehab_protocol import PoseFrame, SensorFrame, make_session_id, now_ms


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run rehabilitation demo with a real USB camera.")
    parser.add_argument("--camera-index", type=int, default=0, help="OpenCV camera index, usually 0 or 1.")
    parser.add_argument("--side", choices=("auto", "left", "right"), default="auto", help="Arm side to analyze.")
    parser.add_argument("--cloud-url", default="http://127.0.0.1:8000", help="Local cloud API base URL.")
    parser.add_argument("--participant", default="camera_demo", help="Participant ID stored in the session.")
    parser.add_argument("--frames", type=int, default=0, help="Stop after N fused frames. 0 means run until q/Ctrl+C.")
    parser.add_argument("--fps", type=float, default=10.0, help="Target fusion/upload rate.")
    parser.add_argument(
        "--report-interval",
        type=float,
        default=0.5,
        help="Console report interval in seconds. Lower values feel more realtime.",
    )
    parser.add_argument("--width", type=int, default=1280, help="Requested camera width.")
    parser.add_argument("--height", type=int, default=720, help="Requested camera height.")
    parser.add_argument(
        "--infer-width",
        type=int,
        default=640,
        help="Resize width for pose inference. 0 keeps the original camera frame size.",
    )
    parser.add_argument(
        "--model-path",
        default=None,
        help="Path to pose_landmarker.task when using the newer MediaPipe Tasks package.",
    )
    parser.add_argument("--disable-upload", action="store_true", help="Keep JSONL locally without HTTP upload.")
    parser.add_argument("--no-preview", action="store_true", help="Disable OpenCV preview window.")
    parser.add_argument(
        "--serial-port",
        default=None,
        help="ESP32-S3 serial port. If omitted, simulated IMU/sEMG data is used.",
    )
    parser.add_argument("--serial-baud", type=int, default=115200, help="ESP32-S3 serial baud rate.")
    parser.add_argument("--serial-timeout", type=float, default=1.0, help="Serial read timeout in seconds.")
    parser.add_argument(
        "--vision-only-rules",
        action="store_true",
        help="Read real sensors for logging, but ignore IMU/sEMG in rule judgement.",
    )
    return parser.parse_args()


def sensor_reader_from_args(args: argparse.Namespace):
    """Build the sensor reader for the single-machine demo."""
    if args.serial_port:
        reader = SerialSensorReader(
            port=args.serial_port,
            baudrate=args.serial_baud,
            timeout=args.serial_timeout,
        )
        return reader, f"serial {args.serial_port} @ {args.serial_baud}"
    return SimulatedSensorReader(interval_s=0.0), "simulated IMU/sEMG"


class LatestSensorBuffer:
    """后台持续读取串口传感器，前台总是拿最新一帧，避免阻塞摄像头主循环。"""

    def __init__(self, reader) -> None:
        self.reader = reader
        self._lock = threading.Lock()
        self._latest = SensorFrame(timestamp_ms=now_ms())
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return

        def run() -> None:
            while True:
                frame = self.reader.read()
                with self._lock:
                    self._latest = frame

        self._thread = threading.Thread(target=run, name="camera-demo-sensor", daemon=True)
        self._thread.start()

    def latest(self) -> SensorFrame:
        with self._lock:
            return self._latest


def open_camera(cv2, camera_index: int, width: int, height: int):
    backend = cv2.CAP_DSHOW if os.name == "nt" else 0
    capture = cv2.VideoCapture(camera_index, backend)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"Cannot open camera index {camera_index}. Try --camera-index 1 or 2.")
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    # Keep the capture queue as short as possible so preview follows the user
    # instead of showing older buffered frames.
    if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def inference_frame(cv2, frame, infer_width: int):
    if infer_width <= 0 or frame.shape[1] <= infer_width:
        return frame
    scale = infer_width / frame.shape[1]
    infer_height = max(1, int(frame.shape[0] * scale))
    return cv2.resize(frame, (infer_width, infer_height))


def arm_indices(side: str) -> tuple[int, int, int]:
    if side == "left":
        return LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST
    return RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST


def draw_pose_overlay(cv2, frame, pose, side: str) -> None:
    shoulder_index, elbow_index, wrist_index = arm_indices(side)
    landmarks = pose.landmarks_2d
    if len(landmarks) <= wrist_index:
        return

    points = []
    for index in (shoulder_index, elbow_index, wrist_index):
        item = landmarks[index]
        x = int(item["x"] * frame.shape[1])
        y = int(item["y"] * frame.shape[0])
        points.append((x, y))

    shoulder, elbow, wrist = points
    line_color = (80, 220, 80)
    joint_color = (40, 170, 255)
    cv2.line(frame, shoulder, elbow, line_color, 3, cv2.LINE_AA)
    cv2.line(frame, elbow, wrist, line_color, 3, cv2.LINE_AA)
    cv2.circle(frame, shoulder, 6, joint_color, -1, cv2.LINE_AA)
    cv2.circle(frame, elbow, 6, joint_color, -1, cv2.LINE_AA)
    cv2.circle(frame, wrist, 6, joint_color, -1, cv2.LINE_AA)

    if len(landmarks) > RIGHT_HIP:
        left_shoulder = landmarks[LEFT_SHOULDER]
        right_shoulder = landmarks[RIGHT_SHOULDER]
        left_hip = landmarks[LEFT_HIP]
        right_hip = landmarks[RIGHT_HIP]
        shoulder_mid = (
            int((left_shoulder["x"] + right_shoulder["x"]) * 0.5 * frame.shape[1]),
            int((left_shoulder["y"] + right_shoulder["y"]) * 0.5 * frame.shape[0]),
        )
        hip_mid = (
            int((left_hip["x"] + right_hip["x"]) * 0.5 * frame.shape[1]),
            int((left_hip["y"] + right_hip["y"]) * 0.5 * frame.shape[0]),
        )
        cv2.line(frame, shoulder_mid, hip_mid, (255, 190, 80), 2, cv2.LINE_AA)


def state_label(state: str) -> str:
    return {
        "idle": "静止",
        "raising": "抬手中",
        "holding": "保持中",
        "lowering": "放下中",
        "completed": "完成一次",
        "incorrect": "动作不标准",
        "anomaly": "检测到异常",
    }.get(state, state)


def anomaly_label(anomaly: str) -> str:
    return {
        "elbow_not_extended": "肘部没有伸直",
        "elbow_hyperextension": "肘部过伸",
        "forearm_lift_compensation": "前臂代偿",
        "safety_stop": "安全停止",
        "trunk_compensation": "躯干代偿",
        "shoulder_over_target_compensation": "肩部过顶代偿",
        "shoulder_hike_compensation": "耸肩代偿",
        "excessive_muscle_activation": "肌电负荷过高(当前为模拟信号)",
    }.get(anomaly, anomaly)


def coaching_hint(rehab, pose) -> str:
    target_angle = 90.0
    idle_angle = 25.0
    hold_angle = 85.0
    shoulder_gap = target_angle - pose.shoulder_angle
    shoulder_gap_text = f"距离目标还差 {max(0, int(round(shoulder_gap)))}°"

    if "safety_stop" in rehab.anomalies:
        return "角度过大，立即停止，慢慢回到安全位置"
    if "trunk_compensation" in rehab.anomalies:
        return "躯干侧倾过大，收紧腰腹，保持身体直立"
    if "shoulder_over_target_compensation" in rehab.anomalies:
        return "肩已超过水平目标，请放低到肩平附近"
    if "shoulder_hike_compensation" in rehab.anomalies:
        return "注意不要耸肩，放松斜方肌，肩胛骨下沉"
    if "forearm_lift_compensation" in rehab.anomalies:
        if pose.shoulder_angle < 45:
            return "小臂抬得很高，但上臂没有充分抬起"
        return "小臂上翘过多，尽量让上臂带动整条手臂"
    if "elbow_not_extended" in rehab.anomalies:
        return f"肘关节角度 {pose.elbow_angle:.0f}°，请伸直手肘到 160° 以上"
    if "elbow_hyperextension" in rehab.anomalies:
        return "肘关节疑似过伸，保持伸直但不要反折"
    if "excessive_muscle_activation" in rehab.anomalies:
        return "当前显示的是模拟肌电异常，可先忽略"

    if rehab.state == "idle":
        return f"继续抬高，{shoulder_gap_text}"

    if rehab.state == "raising":
        if shoulder_gap > 20:
            return f"继续抬高，距离目标大约还差 {int(round(shoulder_gap))}°"
        if shoulder_gap > 5:
            return "已经接近目标，再抬高一点"
        if pose.shoulder_angle > target_angle + 15:
            return "抬得偏高了，可以略微放低一点"
        return "接近目标，准备保持"

    if rehab.state == "holding":
        if pose.shoulder_angle < hold_angle:
            return "高度还不够，继续抬到肩平附近"
        if pose.shoulder_angle > target_angle + 20:
            return "抬得偏高了，保持时可略微放低一些"
        if rehab.score >= 85:
            return "位置较好，保持住"
        return "位置基本到位，再稳定一点"

    if rehab.state == "lowering":
        if rehab.score < 60:
            return "正在放下，注意控制速度和轨迹"
        return "慢慢放下，保持肘部伸直"
    if rehab.state == "completed":
        return "这次动作完成了"
    if pose.shoulder_angle <= idle_angle:
        return f"继续抬高，{shoulder_gap_text}"
    if rehab.score >= 85:
        return "动作质量较好，继续保持"
    if pose.shoulder_angle < target_angle - 15:
        return "动作幅度还不够，需要继续抬高"
    if pose.shoulder_angle > target_angle + 20:
        return "动作幅度偏大，可略微放低一些"
    return "动作基本到位，再稳一点"


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
        estimator = MediaPipePoseEstimator(side=args.side, model_path=args.model_path)
    except ImportError as exc:
        raise SystemExit(
            "MediaPipe is not installed. Use Python 3.10/3.11 and run: "
            "pip install -r requirements-vision.txt"
        ) from exc
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    session_id = make_session_id("camera")
    initial_side = "right" if args.side == "auto" else args.side
    rules = RehabStateMachine(RehabRuleConfig(arm_side=initial_side))
    fusion = RehabFusionPipeline(
        session_id=session_id,
        rules=rules,
        use_imu_rules=not args.vision_only_rules,
        use_emg_rules=not args.vision_only_rules,
    )
    recorder = JsonlRecorder(f"data/{session_id}.jsonl")
    uploader = CloudUploader(base_url=args.cloud_url, timeout_s=0.2)
    sensor_reader, sensor_source = sensor_reader_from_args(args)
    sensor_buffer = None
    if args.serial_port:
        sensor_buffer = LatestSensorBuffer(sensor_reader)
        sensor_buffer.start()
    upload_enabled = not args.disable_upload

    print(f"[camera] session_id: {session_id}")
    print(f"[camera] sensor source: {sensor_source}")
    if args.vision_only_rules:
        print("[camera] rules mode: vision-only (real sensors are logged but not used for judgement)")
    if args.disable_upload:
        print("[camera] upload disabled; keeping local JSONL only")
        upload_enabled = False
    elif uploader.create_session(session_id, participant=args.participant):
        print("[camera] cloud session created")
    else:
        upload_enabled = False
        print("[camera] cloud is not reachable; keeping local JSONL only")

    capture = open_camera(cv2, args.camera_index, args.width, args.height)
    frame_count = 0
    last_report = time.time()
    report_interval = max(0.05, args.report_interval)
    frame_interval = 0.0 if args.fps <= 0 else 1.0 / args.fps
    next_tick = time.perf_counter()
    last_pose = PoseFrame()
    last_rehab = None
    last_side = initial_side

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                print("[camera] failed to read camera frame")
                time.sleep(0.1)
                continue

            now = time.perf_counter()
            should_process = last_rehab is None or frame_interval == 0.0 or now >= next_tick
            if should_process:
                infer_frame = inference_frame(cv2, frame, args.infer_width)
                pose = estimator.estimate(infer_frame)
                analysis_side = estimator.current_side
                rules.set_arm_side(analysis_side)
                sensor_frame = sensor_buffer.latest() if sensor_buffer is not None else sensor_reader.read()
                rehab = fusion.fuse(pose, sensor_frame)
                recorder.append(rehab.to_dict())
                if upload_enabled:
                    uploader.upload_frame(rehab)

                last_pose = pose
                last_rehab = rehab
                last_side = analysis_side
                frame_count += 1
                if frame_interval > 0.0:
                    next_tick = now + frame_interval

            if not args.no_preview:
                draw_pose_overlay(cv2, frame, last_pose, last_side)
                status_text = (
                    f"shoulder {last_pose.shoulder_angle:.0f}  "
                    f"elbow {last_pose.elbow_angle:.0f}  "
                    f"forearm {last_pose.forearm_angle:.0f}  "
                    f"trunk {last_pose.trunk_angle:.0f}  "
                    f"{last_rehab.state if last_rehab else 'idle'}"
                )
                cv2.putText(frame, status_text, (24, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (40, 220, 80), 2, cv2.LINE_AA)
                cv2.imshow("Rehab Camera Demo - press q to quit", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            if last_rehab is not None and time.time() - last_report >= report_interval:
                anomaly_text = "、".join(anomaly_label(item) for item in last_rehab.anomalies) if last_rehab.anomalies else "无"
                imu_roll = float(last_rehab.imu_features.get("roll", 0.0))
                imu_pitch = float(last_rehab.imu_features.get("pitch", 0.0))
                imu_yaw = float(last_rehab.imu_features.get("yaw", 0.0))
                emg_rms = float(last_rehab.emg_features.get("rms_mean", 0.0))
                print(
                    f"[camera] 第{frame_count:>4}帧 | "
                    f"侧别 {last_side:<5} | "
                    f"肩角 {last_pose.shoulder_angle:5.1f}° | "
                    f"肘角 {last_pose.elbow_angle:5.1f}° | "
                    f"前臂 {last_pose.forearm_angle:5.1f}° | "
                    f"躯干 {last_pose.trunk_angle:5.1f}° | "
                    f"IMU R/P/Y {imu_roll:6.1f}/{imu_pitch:6.1f}/{imu_yaw:6.1f} | "
                    f"EMG_RMS {emg_rms:6.1f} | "
                    f"状态 {state_label(last_rehab.state):<6} | "
                    f"评分 {last_rehab.score:5.1f} | "
                    f"异常 {anomaly_text} | "
                    f"提示 {coaching_hint(last_rehab, last_pose)}"
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
