from __future__ import annotations

import argparse
import itertools
from pathlib import Path

from shared.rehab_protocol import make_session_id

from .rehab_edge.fusion import RehabFusionPipeline
from .rehab_edge.pose import synthetic_pose
from .rehab_edge.recorder import JsonlRecorder
from .rehab_edge.sensors import SimulatedSensorReader
from .rehab_edge.uploader import CloudUploader


def parse_args() -> argparse.Namespace:
    """解析命令行参数，支持只本地记录或同时上传云端。"""
    parser = argparse.ArgumentParser(description="Run the Week 1 simulated edge loop.")
    parser.add_argument("--cloud-url", default="", help="Local cloud URL, for example http://127.0.0.1:8000")
    parser.add_argument("--session-id", default="", help="Use a fixed session id.")
    parser.add_argument("--frames", type=int, default=240, help="Number of fused frames to emit.")
    parser.add_argument("--interval", type=float, default=0.05, help="Simulated sensor interval in seconds.")
    parser.add_argument(
        "--record",
        default="data/sessions/edge_demo.jsonl",
        help="JSONL path for fused frames.",
    )
    return parser.parse_args()


def main() -> None:
    """运行 Week 1 模拟边缘端闭环。"""
    args = parse_args()
    session_id = args.session_id or make_session_id("edge")
    pipeline = RehabFusionPipeline(session_id=session_id)
    recorder = JsonlRecorder(Path(args.record))
    uploader = CloudUploader(args.cloud_url) if args.cloud_url else None
    if uploader:
        uploader.create_session(session_id)

    print(f"session_id={session_id}")
    # 这里先使用模拟传感器；接入硬件后可替换为 SerialSensorReader。
    sensor_reader = SimulatedSensorReader(interval_s=args.interval)
    for step, sensor_frame in enumerate(itertools.islice(sensor_reader, args.frames)):
        # synthetic_pose 代替摄像头姿态，保证没有硬件也能验证云端和网页。
        pose = synthetic_pose(step)
        rehab_frame = pipeline.fuse(pose, sensor_frame)
        payload = rehab_frame.to_dict()
        recorder.append(payload)
        if uploader:
            uploader.upload_frame(rehab_frame)
        if step % 10 == 0:
            reps = payload["imu_features"].get("repetitions", 0)
            print(
                f"{step:04d} state={rehab_frame.state:<10} "
                f"shoulder={pose.shoulder_angle:6.1f} elbow={pose.elbow_angle:6.1f} "
                f"score={rehab_frame.score:5.1f} reps={reps}"
            )


if __name__ == "__main__":
    main()
