const historyLimit = 120;
// 前端只保留最近 120 帧，避免长时间演示导致浏览器越来越慢。
const frames = [];
let sessionId = new URLSearchParams(window.location.search).get("session") || "";
let socket = null;

// 状态到中文提示语的映射，患者端直接展示。
const stateCue = {
  idle: "站稳，手臂自然下垂",
  raising: "缓慢抬高手臂",
  holding: "保持目标角度",
  lowering: "控制速度放下",
  completed: "完成一次，准备下一次",
  incorrect: "注意伸直肘关节",
  anomaly: "出现代偿或肌肉负荷异常",
};

function $(id) {
  // 简短封装，减少重复的 document.getElementById。
  return document.getElementById(id);
}

function connect() {
  // 连接指定 session 的 WebSocket；医生端和患者端可以连同一个 session。
  const input = $("sessionId");
  sessionId = input?.value || sessionId || "edge_demo";
  if (input) input.value = sessionId;
  if (socket) socket.close();

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${window.location.host}/ws/realtime/${sessionId}`);
  socket.onmessage = (event) => {
    // 后端会先发 summary，之后每收到边缘端上传的新帧就推送 frame。
    const message = JSON.parse(event.data);
    if (message.type === "frame") {
      ingestFrame(message.payload);
    }
    if (message.type === "summary") {
      renderSummary(message.payload);
    }
  };
}

function ingestFrame(frame) {
  // 新帧进入统一入口，同时刷新患者端、医生端和曲线。
  frames.push(frame);
  if (frames.length > historyLimit) frames.shift();
  renderPatient(frame);
  renderDoctor(frame);
  drawChart();
}

function renderPatient(frame) {
  // 患者端只显示训练时最需要看的实时反馈。
  setText("shoulderValue", frame.pose.shoulder_angle.toFixed(0));
  setText("elbowValue", frame.pose.elbow_angle.toFixed(0));
  setText("scoreValue", frame.score.toFixed(0));
  setText("repValue", frame.imu_features.repetitions || 0);
  setText("emgValue", Math.round(frame.emg_features.rms_max || 0));
  setText("cueText", stateCue[frame.state] || frame.state);

  const stateLabel = $("stateLabel");
  if (stateLabel) {
    stateLabel.textContent = frame.state;
    stateLabel.className = `state-label state-${frame.state}`;
  }
}

function renderDoctor(frame) {
  // 医生端关注统计信息和异常事件。
  const anomalyCount = frames.reduce((sum, item) => sum + (item.anomalies || []).length, 0);
  const average =
    frames.reduce((sum, item) => sum + Number(item.score || 0), 0) / Math.max(1, frames.length);
  setText("frameCount", frames.length);
  setText("averageScore", average.toFixed(1));
  setText("anomalyCount", anomalyCount);

  const log = $("eventLog");
  if (log && (frame.state === "completed" || frame.anomalies.length > 0)) {
    // 只记录完成和异常，避免日志被普通帧刷屏。
    const item = document.createElement("li");
    const anomalies = frame.anomalies.length ? ` · ${frame.anomalies.join(", ")}` : "";
    item.textContent = `${new Date(frame.timestamp_ms).toLocaleTimeString()} ${frame.state}${anomalies}`;
    log.prepend(item);
    while (log.children.length > 20) log.removeChild(log.lastChild);
  }
}

function renderSummary(summary) {
  // 页面刚连接时显示当前会话已有统计，适合服务重启后恢复演示。
  if (!summary) return;
  setText("frameCount", summary.frame_count || 0);
  setText("averageScore", summary.average_score || 0);
  setText("durationValue", summary.duration_s || 0);
  setText("anomalyCount", Object.values(summary.anomalies || {}).reduce((a, b) => a + b, 0));
  if (summary.latest) ingestFrame(summary.latest);
}

function drawChart() {
  // 使用原生 Canvas 绘图，避免引入额外前端构建工具。
  const canvas = $("angleChart");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);
  drawGrid(ctx, width, height);
  drawSeries(ctx, width, height, (frame) => frame.pose.shoulder_angle, "#2f6fd6");
  drawSeries(ctx, width, height, (frame) => frame.pose.elbow_angle, "#147d7e");
}

function drawGrid(ctx, width, height) {
  // 背景网格帮助观察角度趋势，不承担精确医学读数。
  ctx.strokeStyle = "#d9e0e7";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = 20 + (i * (height - 40)) / 4;
    ctx.beginPath();
    ctx.moveTo(36, y);
    ctx.lineTo(width - 16, y);
    ctx.stroke();
  }
  ctx.fillStyle = "#687382";
  ctx.font = "14px system-ui";
  ctx.fillText("shoulder", width - 170, 28);
  ctx.fillStyle = "#147d7e";
  ctx.fillText("elbow", width - 90, 28);
}

function drawSeries(ctx, width, height, getter, color) {
  // 把 0-180 度角度映射到 Canvas 高度。
  if (frames.length < 2) return;
  const left = 36;
  const right = width - 16;
  const top = 20;
  const bottom = height - 20;
  ctx.strokeStyle = color;
  ctx.lineWidth = 3;
  ctx.beginPath();
  frames.forEach((frame, index) => {
    const x = left + (index * (right - left)) / Math.max(1, historyLimit - 1);
    const value = Math.max(0, Math.min(180, getter(frame)));
    const y = bottom - (value / 180) * (bottom - top);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function setText(id, value) {
  // 节点不存在时静默跳过，让同一份 JS 可同时服务患者端和医生端。
  const node = $(id);
  if (node) node.textContent = value;
}

document.addEventListener("DOMContentLoaded", () => {
  // 默认连接 edge_demo，便于比赛现场快速打开页面。
  const input = $("sessionId");
  if (input) input.value = sessionId || "edge_demo";
  $("connectBtn")?.addEventListener("click", connect);
  connect();
});
