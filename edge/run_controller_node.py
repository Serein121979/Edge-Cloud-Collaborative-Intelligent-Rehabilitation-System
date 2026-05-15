"""Run the Loongson controller node.

The controller receives PoseFrame objects from the x86 vision node, reads
ESP32-S3 JSON Lines from serial, fuses the newest pose with the current sensor
frame, records JSONL locally, and uploads RehabFrame objects to the cloud API.
"""

from __future__ import annotations

import argparse
import threading
import time
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException

from edge.rehab_edge.fusion import RehabFusionPipeline
from edge.rehab_edge.recorder import JsonlRecorder
from edge.rehab_edge.rules import RehabRuleConfig, RehabStateMachine
from edge.rehab_edge.sensors import SerialSensorReader, SimulatedSensorReader
from edge.rehab_edge.uploader import CloudUploader
from shared.rehab_protocol import PoseFrame, RehabFrame, SensorFrame, make_session_id


class ControllerState:
    """Thread-safe holder for the newest PoseFrame sent by the vision node."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest_pose: PoseFrame | None = None
        self._updated_at_ms = 0

    def set_pose(self, pose: PoseFrame) -> None:
        with self._lock:
            self._latest_pose = pose
            self._updated_at_ms = int(time.time() * 1000)

    def latest_pose_or_default(self) -> tuple[PoseFrame, bool, int]:
        with self._lock:
            if self._latest_pose is None:
                return PoseFrame(), False, 0
            return self._latest_pose, True, self._updated_at_ms


def create_controller_app(state: ControllerState) -> FastAPI:
    """Create the HTTP API used by the x86 vision node."""
    app = FastAPI(title="Loongson Rehab Controller")

    @app.post("/api/pose")
    async def receive_pose(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            pose = PoseFrame.from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"invalid PoseFrame: {exc}") from exc
        state.set_pose(pose)
        return {"ok": True}

    @app.get("/api/pose/latest")
    async def latest_pose() -> dict[str, Any]:
        pose, has_pose, updated_at_ms = state.latest_pose_or_default()
        return {"has_pose": has_pose, "updated_at_ms": updated_at_ms, "pose": pose.to_dict()}

    return app


def fuse_latest_pose(
    state: ControllerState,
    fusion: RehabFusionPipeline,
    sensor_frame: SensorFrame,
) -> tuple[RehabFrame, bool]:
    """Fuse the current sensor frame with the newest known pose."""
    pose, has_pose, _updated_at_ms = state.latest_pose_or_default()
    return fusion.fuse(pose, sensor_frame), has_pose


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Loongson controller for rehab fusion.")
    parser.add_argument("--serial-port", default=None, help="ESP32-S3 serial port, for example /dev/ttyUSB1.")
    parser.add_argument("--serial-baud", type=int, default=115200, help="ESP32-S3 serial baud rate.")
    parser.add_argument("--serial-timeout", type=float, default=1.0, help="Serial read timeout in seconds.")
    parser.add_argument("--simulate-sensors", action="store_true", help="Use simulated IMU/sEMG when ESP32 is absent.")
    parser.add_argument("--cloud-url", default="http://127.0.0.1:8000", help="Cloud API base URL.")
    parser.add_argument("--disable-upload", action="store_true", help="Keep JSONL locally without HTTP upload.")
    parser.add_argument("--listen-host", default="0.0.0.0", help="Controller HTTP host.")
    parser.add_argument("--listen-port", type=int, default=9001, help="Controller HTTP port.")
    parser.add_argument("--participant", default="loongson_controller", help="Participant ID stored in the session.")
    parser.add_argument("--side", choices=("left", "right"), default="right", help="Arm side used by controller rules.")
    parser.add_argument("--frames", type=int, default=0, help="Stop after N fused frames. 0 means run until Ctrl+C.")
    parser.add_argument("--report-interval", type=float, default=0.5, help="Console report interval in seconds.")
    parser.add_argument(
        "--vision-only-rules",
        action="store_true",
        help="Read real sensors for logging, but ignore IMU/sEMG in rule judgement.",
    )
    return parser.parse_args()


def start_pose_server(state: ControllerState, host: str, port: int) -> threading.Thread:
    app = create_controller_app(state)

    def run() -> None:
        uvicorn.run(app, host=host, port=port, log_level="warning")

    thread = threading.Thread(target=run, name="pose-api", daemon=True)
    thread.start()
    return thread


def build_sensor_reader(args: argparse.Namespace):
    if args.simulate_sensors:
        return SimulatedSensorReader(interval_s=0.02), "simulated IMU/sEMG"
    if not args.serial_port:
        raise SystemExit("Please pass --serial-port /dev/ttyUSBx, or use --simulate-sensors before hardware arrives.")
    reader = SerialSensorReader(port=args.serial_port, baudrate=args.serial_baud, timeout=args.serial_timeout)
    return reader, f"serial {args.serial_port} @ {args.serial_baud}"


def main() -> None:
    args = parse_args()
    state = ControllerState()
    start_pose_server(state, args.listen_host, args.listen_port)

    session_id = make_session_id("controller")
    rules = RehabStateMachine(RehabRuleConfig(arm_side=args.side))
    fusion = RehabFusionPipeline(
        session_id=session_id,
        rules=rules,
        use_imu_rules=not args.vision_only_rules,
        use_emg_rules=not args.vision_only_rules,
    )
    recorder = JsonlRecorder(f"data/{session_id}.jsonl")
    uploader = CloudUploader(base_url=args.cloud_url, timeout_s=0.2)
    sensor_reader, sensor_source = build_sensor_reader(args)
    upload_enabled = not args.disable_upload

    print(f"[controller] session_id: {session_id}")
    print(f"[controller] pose API: http://{args.listen_host}:{args.listen_port}/api/pose")
    print(f"[controller] sensor source: {sensor_source}")
    if args.vision_only_rules:
        print("[controller] rules mode: vision-only (real sensors are logged but not used for judgement)")
    if args.disable_upload:
        print("[controller] upload disabled; keeping local JSONL only")
    elif uploader.create_session(session_id, participant=args.participant):
        print("[controller] cloud session created")
    else:
        upload_enabled = False
        print("[controller] cloud is not reachable; keeping local JSONL only")

    frame_count = 0
    last_report = time.time()
    report_interval = max(0.05, args.report_interval)
    warned_no_pose = False

    try:
        for sensor_frame in sensor_reader:
            rehab, has_pose = fuse_latest_pose(state, fusion, sensor_frame)
            if not has_pose and not warned_no_pose:
                print("[controller] waiting for vision PoseFrame; using default empty pose for now")
                warned_no_pose = True

            recorder.append(rehab.to_dict())
            if upload_enabled:
                uploader.upload_frame(rehab)

            frame_count += 1
            if time.time() - last_report >= report_interval:
                emg_rms = rehab.emg_features.get("rms_mean", 0.0)
                print(
                    f"[controller] 第{frame_count:>4}帧 | "
                    f"pose {'ok' if has_pose else 'waiting'} | "
                    f"肩角 {rehab.pose.shoulder_angle:5.1f}° | "
                    f"肘角 {rehab.pose.elbow_angle:5.1f}° | "
                    f"状态 {rehab.state:<9} | "
                    f"评分 {rehab.score:5.1f} | "
                    f"EMG_RMS {float(emg_rms):7.1f} | "
                    f"异常 {rehab.anomalies}"
                )
                last_report = time.time()

            if args.frames and frame_count >= args.frames:
                break
    except KeyboardInterrupt:
        print("\n[controller] stopped by user")

    print(f"[controller] done, processed {frame_count} frames")
    print(f"[controller] log saved to data/{session_id}.jsonl")


if __name__ == "__main__":
    main()
