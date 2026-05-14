"""边缘端本地演示脚本：在不依赖摄像头和串口硬件的情况下，
模拟训练全流程来验证系统功能。

运行方式：
    python edge/run_edge_demo.py

该脚本会执行以下步骤：
1. 使用模拟姿态数据源（synthetic_pose）替代摄像头
2. 使用模拟传感器数据源（SimulatedSensorReader）替代 ESP32 串口
3. 融合流水线将两者合成为康复帧
4. 本地记录到 JSONL 文件
5. 尝试上传到云端

整个过程持续最多 30 秒（约 300 帧，10Hz 采样率）。
"""

import time
import uuid
from datetime import datetime

from edge.rehab_edge.fusion import RehabFusionPipeline
from edge.rehab_edge.pose import synthetic_pose
from edge.rehab_edge.recorder import JsonlRecorder
from edge.rehab_edge.rules import RehabRuleConfig, RehabStateMachine
from edge.rehab_edge.sensors import SimulatedSensorReader
from edge.rehab_edge.uploader import CloudUploader


def main() -> None:
    """运行边缘端本地演示。

    在整个演示过程中，流水线会输出每帧的状态摘要，
    包括当前动作阶段、评分和异常信息。演示结束后会显示
    总处理帧数和日志文件路径。
    """
    # 生成唯一的会话 ID，格式：demo_20260101_093000_a1b2c3d4
    session_id = f"demo_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    print(f"[演示] 会话ID: {session_id}")

    # 初始化各模块
    fusion = RehabFusionPipeline(
        session_id=session_id,
        rules=RehabStateMachine(RehabRuleConfig(arm_side="right")),
    )
    recorder = JsonlRecorder(f"data/{session_id}.jsonl")
    uploader = CloudUploader(base_url="http://localhost:8000")

    # 在云端创建会话（如果不可达也没关系，本地演示可以跳过）
    if uploader.create_session(session_id, participant="demo"):
        print("[演示] 云端会话创建成功")
    else:
        print("[演示] 云端不可达，将仅保存本地记录")

    # 使用模拟数据源：合成姿态（10Hz）+ 模拟传感器（20Hz）
    # 传感器频率高，每 2 帧传感器取 1 帧与姿态融合
    sensor_source = SimulatedSensorReader(interval_s=0.05)

    frame_count = 0
    start_time = time.time()

    for step, sensor_frame in enumerate(sensor_source):
        # 每 2 帧融合一次（对应约 10Hz 融合频率）
        if step % 2 != 0:
            continue

        # 生成模拟姿态
        pose = synthetic_pose(step // 2, period=120)

        # 融合
        rehab = fusion.fuse(pose, sensor_frame)

        # 本地记录
        recorder.append(rehab.to_dict())

        # 上传（失败不影响主流程）
        uploader.upload_frame(rehab)

        # 控制台输出摘要
        print(
            f"帧 {frame_count:>4} | "
            f"角度 {pose.shoulder_angle:5.1f}° | "
            f"状态 {rehab.state:>9} | "
            f"评分 {rehab.score:5.1f} | "
            f"异常 {rehab.anomalies}"
        )

        frame_count += 1

        # 运行最多 30 秒
        if time.time() - start_time > 30:
            break

    print(f"\n[演示] 完成！共处理 {frame_count} 帧。")
    print(f"[演示] 日志已保存至: data/{session_id}.jsonl")


if __name__ == "__main__":
    main()
