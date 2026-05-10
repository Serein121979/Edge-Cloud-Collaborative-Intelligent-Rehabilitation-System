from __future__ import annotations

import json
from urllib.error import URLError
from urllib.request import Request, urlopen

from shared.rehab_protocol import RehabFrame


class CloudUploader:
    """边缘端数据上传客户端，仅依赖 Python 标准库，无需额外安装依赖。

    这种设计的目的是降低在龙芯处理器上的部署复杂度：
    - 只使用 urllib，不需要安装 requests 等第三方库（龙芯的 PyPI 镜像可能不全）
    - 上传失败时返回 False 而非抛异常，由边缘端保留本地记录兜底
    - 可配置超时时间，避免网络问题阻塞主循环

    属性:
        base_url: 云端 API 的基础 URL（如 "http://localhost:8000"）
        timeout_s: HTTP 请求超时时间（秒）
    """

    def __init__(self, base_url: str, timeout_s: float = 2.0) -> None:
        """初始化云端上传客户端。

        参数:
            base_url: 云端 API 的基础地址，如 "http://localhost:8000"
            timeout_s: HTTP 请求超时秒数，默认 2 秒，避免网络延迟过大时阻塞主循环
        """
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def create_session(self, session_id: str, participant: str = "demo") -> bool:
        """在云端创建一个新的训练会话记录。

        在训练开始前调用此方法通知云端开始记录，云端会创建对应的
        训练会话条目并分配存储空间。

        参数:
            session_id: 训练会话的全局唯一标识（如 UUID 字符串）
            participant: 参与者标识，默认 "demo"，正式使用时应传入患者 ID
        返回:
            创建成功返回 True，网络失败返回 False
        """
        payload = {"session_id": session_id, "participant": participant, "scenario": "upper_limb"}
        return self._post("/api/sessions", payload)

    def upload_frame(self, frame: RehabFrame) -> bool:
        """将一帧融合后的标准康复数据上传到云端。

        每帧数据包含姿态角度、IMU 特征、肌电特征、动作状态和评分等信息，
        上传到云端后可以实时展示给医生或康复师。

        参数:
            frame: 融合后的标准康复帧（RehabFrame 实例）
        返回:
            上传成功返回 True，网络失败返回 False
        """
        return self._post("/api/frames", frame.to_dict())

    def _post(self, path: str, payload: dict) -> bool:
        """发送 HTTP POST 请求的内部工具方法。

        将 payload 字典序列化为 JSON，以 UTF-8 编码发送 HTTP POST 请求，
        设置正确的 Content-Type 头。网络异常时不抛异常，返回 False 让
        上层逻辑决定如何处理（通常保留本地记录待补传）。

        参数:
            path: API 路径（将拼接到 base_url 后面，如 "/api/frames"）
            payload: 要发送的数据字典
        返回:
            HTTP 状态码为 2xx 时返回 True，网络错误或非 2xx 返回 False
        """
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                return 200 <= response.status < 300
        except URLError:
            return False