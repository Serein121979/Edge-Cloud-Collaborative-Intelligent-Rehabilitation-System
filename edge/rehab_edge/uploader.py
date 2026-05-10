from __future__ import annotations

import json
from urllib.error import URLError
from urllib.request import Request, urlopen

from shared.rehab_protocol import RehabFrame


class CloudUploader:
    """边缘端上传客户端，只依赖标准库，方便在龙芯板上快速运行。"""

    def __init__(self, base_url: str, timeout_s: float = 2.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def create_session(self, session_id: str, participant: str = "demo") -> bool:
        """通知本地云端创建训练会话。"""
        payload = {"session_id": session_id, "participant": participant, "scenario": "upper_limb"}
        return self._post("/api/sessions", payload)

    def upload_frame(self, frame: RehabFrame) -> bool:
        """上传一帧融合后的康复数据。"""
        return self._post("/api/frames", frame.to_dict())

    def _post(self, path: str, payload: dict) -> bool:
        """发送 HTTP POST；失败时返回 False，由边缘端保留本地记录兜底。"""
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
