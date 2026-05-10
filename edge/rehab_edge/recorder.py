from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonlRecorder:
    """把训练帧追加写入 JSONL 文件，方便离线回放和后续训练模型。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, payload: dict[str, Any]) -> None:
        """追加一行 JSON，ensure_ascii=False 方便中文异常名或备注直接阅读。"""
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
