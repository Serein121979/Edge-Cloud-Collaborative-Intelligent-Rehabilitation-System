from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonlRecorder:
    """本地训练数据记录器，将康复帧逐行追加写入 JSON Lines 文件。

    使用 JSONL 格式的优势：
    - 每行一个独立的 JSON 对象，不需要整体解析即可追加写入
    - 支持流式写入，适合长时间训练记录
    - 可以离线回放数据，用于调试和模型训练

    属性:
        path: 输出文件的路径
    """

    def __init__(self, path: str | Path) -> None:
        """初始化记录器，自动创建父目录。

        参数:
            path: 输出 JSONL 文件的路径，如果父目录不存在会自动创建
        """
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, payload: dict[str, Any]) -> None:
        """将一帧数据以 JSON 行的形式追加写入文件。

        使用 ensure_ascii=False 允许中文字符直接以 Unicode 形式写入，
        避免将所有非 ASCII 字符转义为 \\uXXXX，便于直接阅读。

        参数:
            payload: 要写入的数据字典（如 RehabFrame 的 to_dict() 结果）
        """
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")