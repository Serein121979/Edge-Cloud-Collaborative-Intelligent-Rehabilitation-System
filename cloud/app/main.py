from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from shared.rehab_protocol import RehabFrame, make_session_id

from .storage import SessionStore


ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "web"

# FastAPI 同时提供 API、静态网页和 WebSocket 实时推送。
app = FastAPI(title="Rehabilitation Local Cloud", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 第一版使用进程内存 + JSONL 文件，部署简单，后期可替换成 SQLite。
store = SessionStore(ROOT / "data" / "sessions")
subscribers: dict[str, set[WebSocket]] = {}


@app.get("/")
def root() -> RedirectResponse:
    """访问根路径时默认跳转患者端，患者端入场即用，无需导航。"""
    return RedirectResponse(url="/patient")


@app.get("/patient")
def patient_page() -> FileResponse:
    """患者实时反馈页面：显示当前动作、评分和引导提示。"""
    return FileResponse(WEB_ROOT / "patient.html")


@app.get("/doctor")
def doctor_page() -> FileResponse:
    """医生端训练仪表盘页面：显示多会话概览、实时曲线和异常统计。"""
    return FileResponse(WEB_ROOT / "doctor.html")


app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")


@app.post("/api/sessions")
async def create_session(payload: dict[str, Any]) -> dict[str, Any]:
    """创建训练会话；如果前端没传 session_id，则云端自动生成。

    边缘端在开始训练前调用此接口通知云端，
    云端会创建一个会话记录并分配存储空间用于保存后续帧数据。

    参数:
        payload: 请求体，包含 session_id（可选）、participant（可选）
    返回:
        包含 ok 状态和创建的会话信息的字典
    """
    if "session_id" not in payload or not payload["session_id"]:
        payload["session_id"] = make_session_id("cloud")
    session = store.create_session(payload)
    return {"ok": True, "session": session}


@app.post("/api/frames")
async def receive_frame(payload: dict[str, Any]) -> dict[str, Any]:
    """接收龙芯边缘端上传的一帧 RehabFrame。

    每帧数据包含姿态角度、IMU 特征、肌电特征和动作状态等信息，
    云端将其保存并广播给所有订阅该会话的 WebSocket 客户端
    （患者端和医生端）。

    参数:
        payload: 边缘端上传的帧数据字典
    返回:
        包含 ok 状态和当前会话累计帧数的字典
    异常:
        400: 帧数据格式不正确，无法解析为 RehabFrame
    """
    try:
        frame = RehabFrame.from_dict(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    saved = store.add_frame(frame)
    await broadcast(frame.session_id, saved)
    return {"ok": True, "frame_count": store.summary(frame.session_id)["frame_count"]}


@app.get("/api/sessions/{session_id}/summary")
async def get_summary(session_id: str) -> dict[str, Any]:
    """返回指定会话的统计摘要。

    摘要包含总帧数、训练时长、动作状态分布、异常统计、
    平均评分和最新帧数据，供医生端仪表盘使用。

    参数:
        session_id: 训练会话 ID
    返回:
        统计摘要字典
    """
    return store.summary(session_id)


@app.get("/api/sessions/{session_id}/frames")
async def get_frames(session_id: str, limit: int = 120) -> dict[str, Any]:
    """返回最近若干帧，便于前端刷新或离线查看。

    默认返回最近 120 帧（约 12 秒，按 10Hz 采样率计算），
    前端用这些数据绘制实时趋势曲线。

    参数:
        session_id: 训练会话 ID
        limit: 返回的最大帧数，默认 120
    返回:
        包含 session_id 和帧列表的字典
    """
    return {"session_id": session_id, "frames": store.latest_frames(session_id, limit=limit)}


@app.websocket("/ws/realtime/{session_id}")
async def realtime(websocket: WebSocket, session_id: str) -> None:
    """WebSocket 实时通道：新帧到达后推送给患者端和医生端。

    客户端连接后立即收到当前会话摘要，之后每来一帧就推送一次。
    关闭连接时自动清理，不抛异常。

    参数:
        websocket: WebSocket 连接实例
        session_id: 要订阅的会话 ID
    """
    await websocket.accept()
    subscribers.setdefault(session_id, set()).add(websocket)
    try:
        await websocket.send_json({"type": "summary", "payload": store.summary(session_id)})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        subscribers.get(session_id, set()).discard(websocket)


async def broadcast(session_id: str, payload: dict[str, Any]) -> None:
    """把某个 session 的新帧广播给所有订阅页面。

    使用 asyncio.gather 并发推送新帧数据，单个连接发送失败
    不会影响其他连接（通过 _safe_send 保护）。

    参数:
        session_id: 目标会话 ID
        payload: 要广播的帧数据字典
    """
    sockets = list(subscribers.get(session_id, set()))
    if not sockets:
        return
    message = {"type": "frame", "payload": payload}
    await asyncio.gather(*[_safe_send(socket, message) for socket in sockets])


async def _safe_send(socket: WebSocket, message: dict[str, Any]) -> None:
    """单个连接发送失败时不影响其他连接。

    参数:
        socket: WebSocket 连接实例
        message: 要发送的消息字典
    """
    try:
        await socket.send_json(message)
    except RuntimeError:
        pass