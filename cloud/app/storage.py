from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from shared.rehab_protocol import VALID_STATES, RehabFrame, now_ms


class SessionStore:
    """极简会话存储：内存中快速访问，同时落盘 JSONL 方便复盘。"""

    def __init__(self, root: str | Path = "data/sessions") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.sessions: dict[str, dict[str, Any]] = {}
        self.frames: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def create_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        """创建或覆盖一个训练会话。"""
        session_id = str(payload["session_id"])
        session = {
            "session_id": session_id,
            "participant": payload.get("participant", "demo"),
            "scenario": payload.get("scenario", "upper_limb"),
            "created_at_ms": payload.get("created_at_ms", now_ms()),
        }
        self.sessions[session_id] = session
        return session

    def add_frame(self, frame: RehabFrame) -> dict[str, Any]:
        """保存一帧训练数据，并追加写入对应 session 的 JSONL 文件。"""
        payload = frame.to_dict()
        if frame.session_id not in self.sessions:
            self.create_session({"session_id": frame.session_id})
        self.frames[frame.session_id].append(payload)
        with self._jsonl_path(frame.session_id).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return payload

    def summary(self, session_id: str) -> dict[str, Any]:
        """计算医生端需要的训练摘要。"""
        frames = self.frames.get(session_id)
        if frames is None:
            frames = self._load_frames(session_id)
            self.frames[session_id] = frames

        state_counts = {state: 0 for state in VALID_STATES}
        anomalies: dict[str, int] = defaultdict(int)
        scores: list[float] = []
        max_reps = 0
        for frame in frames:
            # 统计每类动作状态的出现次数，用来判断训练过程是否完整。
            state_counts[str(frame.get("state", "idle"))] += 1
            scores.append(float(frame.get("score", 0.0)))
            for anomaly in frame.get("anomalies", []):
                anomalies[str(anomaly)] += 1
            max_reps = max(max_reps, int(frame.get("imu_features", {}).get("repetitions", 0)))

        return {
            "session_id": session_id,
            "frame_count": len(frames),
            "duration_s": self._duration_s(frames),
            "state_counts": state_counts,
            "anomalies": dict(anomalies),
            "average_score": round(sum(scores) / len(scores), 2) if scores else 0.0,
            "repetitions": max_reps,
            "latest": frames[-1] if frames else None,
        }

    def latest_frames(self, session_id: str, limit: int = 120) -> list[dict[str, Any]]:
        """返回最近若干帧，给前端画实时曲线使用。"""
        return self.frames.get(session_id, [])[-limit:]

    def _jsonl_path(self, session_id: str) -> Path:
        """根据 session_id 找到落盘文件路径。"""
        return self.root / f"{session_id}.jsonl"

    def _load_frames(self, session_id: str) -> list[dict[str, Any]]:
        """服务重启后，从 JSONL 文件恢复历史帧。"""
        path = self._jsonl_path(session_id)
        if not path.exists():
            return []
        frames: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    frames.append(json.loads(line))
        return frames

    @staticmethod
    def _duration_s(frames: list[dict[str, Any]]) -> float:
        """根据第一帧和最后一帧时间戳估算训练时长。"""
        if len(frames) < 2:
            return 0.0
        start = int(frames[0].get("timestamp_ms", 0))
        end = int(frames[-1].get("timestamp_ms", start))
        return round(max(0, end - start) / 1000.0, 2)
