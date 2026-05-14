"""边缘端代码包：负责视觉节点、龙芯 controller、融合、规则识别和上传。

龙芯 controller 是康复系统的核心处理节点；x86 PC 可作为视觉服务节点。
主要职责：
1. x86 视觉节点通过 RGB 摄像头和 MediaPipe 生成 PoseFrame
2. 龙芯 controller 接收 PoseFrame，并读取 ESP32-S3 的 IMU/sEMG 串口数据
3. 龙芯 controller 融合多模态数据生成标准康复帧
4. 运行规则引擎判断动作阶段和检测异常
5. 本地记录训练数据并上传到云端
"""
