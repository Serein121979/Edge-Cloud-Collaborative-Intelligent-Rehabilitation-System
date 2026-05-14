"""Run the x86 vision node.

This process owns the camera and MediaPipe. It sends PoseFrame JSON to the
Loongson controller, where serial sensor fusion and rule judgement happen.
"""

from __future__ import annotations

import argparse
import json
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from edge.rehab_edge.pose import MediaPipePoseEstimator
from edge.run_camera_demo import draw_pose_overlay, inference_frame, open_camera
from shared.rehab_protocol import PoseFrame


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run x86 MediaPipe vision node.")
    parser.add_argument("--camera-index", type=int, default=0, help="OpenCV camera index, usually 0 or 1.")
    parser.add_argument("--side", choices=("auto", "left", "right"), default="auto", help="Arm side to analyze.")
    parser.add_argument("--controller-url", default="http://127.0.0.1:9001", help="Loongson controller base URL.")
    parser.add_argument("--fps", type=float, default=10.0, help="Target pose POST rate.")
    parser.add_argument("--frames", type=int, default=0, help="Stop after N pose frames. 0 means run until q/Ctrl+C.")
    parser.add_argument("--width", type=int, default=1280, help="Requested camera width.")
    parser.add_argument("--height", type=int, default=720, help="Requested camera height.")
    parser.add_argument("--infer-width", type=int, default=640, help="Resize width for pose inference. 0 keeps original.")
    parser.add_argument("--model-path", default=None, help="Path to pose_landmarker.task for MediaPipe Tasks.")
    parser.add_argument("--post-timeout", type=float, default=0.2, help="HTTP POST timeout in seconds.")
    parser.add_argument("--report-interval", type=float, default=0.5, help="Console report interval in seconds.")
    parser.add_argument("--no-preview", action="store_true", help="Disable OpenCV preview window.")
    return parser.parse_args()


def post_pose(controller_url: str, pose: PoseFrame, timeout_s: float = 0.2) -> bool:
    url = controller_url.rstrip("/") + "/api/pose"
    body = json.dumps(pose.to_dict()).encode("utf-8")
    request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=timeout_s) as response:
            return 200 <= response.status < 300
    except (OSError, URLError, TimeoutError):
        return False


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

    capture = open_camera(cv2, args.camera_index, args.width, args.height)
    frame_count = 0
    last_report = time.time()
    report_interval = max(0.05, args.report_interval)
    frame_interval = 0.0 if args.fps <= 0 else 1.0 / args.fps
    next_tick = time.perf_counter()
    last_pose = PoseFrame()
    last_side = "right" if args.side == "auto" else args.side
    last_post_ok = False

    print(f"[vision] controller: {args.controller_url.rstrip('/')}/api/pose")
    print("[vision] camera node started; press q in preview or Ctrl+C to stop")

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                print("[vision] failed to read camera frame")
                time.sleep(0.1)
                continue

            now = time.perf_counter()
            should_process = frame_count == 0 or frame_interval == 0.0 or now >= next_tick
            if should_process:
                pose = estimator.estimate(inference_frame(cv2, frame, args.infer_width))
                last_post_ok = post_pose(args.controller_url, pose, timeout_s=args.post_timeout)
                last_pose = pose
                last_side = estimator.current_side
                frame_count += 1
                if frame_interval > 0.0:
                    next_tick = now + frame_interval

            if not args.no_preview:
                draw_pose_overlay(cv2, frame, last_pose, last_side)
                status_text = (
                    f"vision {frame_count}  "
                    f"post {'ok' if last_post_ok else 'fail'}  "
                    f"shoulder {last_pose.shoulder_angle:.0f}  "
                    f"elbow {last_pose.elbow_angle:.0f}"
                )
                cv2.putText(frame, status_text, (24, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (40, 220, 80), 2, cv2.LINE_AA)
                cv2.imshow("Rehab Vision Node - press q to quit", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            if time.time() - last_report >= report_interval:
                print(
                    f"[vision] 第{frame_count:>4}帧 | "
                    f"POST {'成功' if last_post_ok else '失败'} | "
                    f"侧别 {last_side:<5} | "
                    f"肩角 {last_pose.shoulder_angle:5.1f}° | "
                    f"肘角 {last_pose.elbow_angle:5.1f}° | "
                    f"前臂 {last_pose.forearm_angle:5.1f}° | "
                    f"躯干 {last_pose.trunk_angle:5.1f}°"
                )
                last_report = time.time()

            if args.frames and frame_count >= args.frames:
                break
    except KeyboardInterrupt:
        print("\n[vision] stopped by user")
    finally:
        capture.release()
        if not args.no_preview:
            cv2.destroyAllWindows()

    print(f"[vision] done, sent {frame_count} pose frames")


if __name__ == "__main__":
    main()
