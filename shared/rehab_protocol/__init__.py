"""共享协议包入口：把边缘端和云端都会用到的数据结构统一导出。

这样各模块可以从 shared.rehab_protocol 直接导入，不需要关心内部文件名。
这种设计降低了模块间的耦合，也方便后续扩展新的数据结构。
"""
from .models import (
    VALID_STATES,       # 合法的动作状态列表
    EmgSample,          # 肌电采样数据
    ImuSample,          # IMU 传感器采样数据
    PoseFrame,          # 摄像头姿态识别结果
    RehabFrame,         # 融合后的标准康复训练帧
    SensorFrame,        # ESP32 传感器原始数据帧
    make_session_id,    # 生成训练会话 ID
    now_ms,             # 获取当前时间戳（毫秒）
)

__all__ = [
    "VALID_STATES",
    "EmgSample",
    "ImuSample",
    "PoseFrame",
    "RehabFrame",
    "SensorFrame",
    "make_session_id",
    "now_ms",
]