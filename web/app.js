/**
 * app.js —— 患者端和医生端共用前端脚本。
 *
 * 通过 WebSocket 连接云端 FastAPI 服务，接收实时康复训练帧数据，
 * 同时更新患者端（状态、提示、评分、指标、角度曲线）和
 * 医生端（摘要统计、事件日志、角度曲线）。
 *
 * 使用原生 JavaScript + Canvas，不依赖第三方框架。
 */

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

/**
 * 简化 document.getElementById 的快捷函数。
 * @param {string} id - 元素 ID
 * @returns {HTMLElement|null}
 */
function $(id) {
  // 简短封装，减少重复的 document.getElementById。
  return document.getElementById(id);
}

/**
 * 连接指定 session 的 WebSocket；医生端和患者端可以连同一个 session。
 * 页面加载后自动连接默认 session ("edge_demo")。
 */
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

/**
 * 新帧进入统一入口，同时刷新患者端、医生端和曲线。
 * @param {Object} frame - 从边缘端上传并经过云端广播的康复帧数据
 */
function ingestFrame(frame) {
  // 新帧进入统一入口，同时刷新患者端、医生端和曲线。
  frames.push(frame);
  if (frames.length > historyLimit) frames.shift();
  renderPatient(frame);
  renderDoctor(frame);
  drawChart();
}

/**
 * 更新患者端页面：状态标签、引导提示、动作评分、关节角度、完成次数、肌电 RMS。
 * @param {Object} frame - 当前帧数据
 */
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

/**
 * 更新医生端页面：帧数、平均评分、异常次数、事件日志。
 * 只记录"completed"（完成一次动作）和包含异常的事件，避免日志刷屏。
 * @param {Object} frame - 当前帧数据
 */
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

/**
 * 处理页面刚连接时云端推送的会话摘要，恢复已有统计数据显示。
 * @param {Object} summary - 会话摘要数据（frame_count, average_score, duration_s, anomalies, latest）
 */
function renderSummary(summary) {
  // 页面刚连接时显示当前会话已有统计，适合服务重启后恢复演示。
  if (!summary) return;
  setText("frameCount", summary.frame_count || 0);
  setText("averageScore", summary.average_score || 0);
  setText("durationValue", summary.duration_s || 0);
  setText("anomalyCount", Object.values(summary.anomalies || {}).reduce((a, b) => a + b, 0));
  if (summary.latest) ingestFrame(summary.latest);
}

/**
 * 使用原生 Canvas 绘制肩关节和肘关节角度变化趋势曲线。
 * 使用固定坐标（Canvas 尺寸 900x260/300），CSS 拉伸适配面板大小。
 */
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

/**
 * 绘制背景参考网格和角度标签（四条水平线代表 45° 间隔）。
 * @param {CanvasRenderingContext2D} ctx - Canvas 2D 上下文
 * @param {number} width - Canvas 宽度
 * @param {number} height - Canvas 高度
 */
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

/**
 * 绘制单条角度变化曲线（肩关节或肘关节）。
 * 将 0-180° 角度值映射到 Canvas 垂直坐标。
 * @param {CanvasRenderingContext2D} ctx - Canvas 2D 上下文
 * @param {number} width - Canvas 宽度
 * @param {number} height - Canvas 高度
 * @param {Function} getter - 从帧数据中提取角度值的函数
 * @param {string} color - 曲线颜色
 */
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

/**
 * 安全设置元素文本内容，节点不存在时静默跳过。
 * 让同一份 JS 可同时服务患者端和医生端（某些元素只在其中一个页面存在）。
 * @param {string} id - 元素 ID
 * @param {string|number} value - 要设置的文本内容
 */
function setText(id, value) {
  // 节点不存在时静默跳过，让同一份 JS 可同时服务患者端和医生端。
  const node = $(id);
  if (node) node.textContent = value;
}

// 页面加载完成后自动连接，便于比赛现场快速打开页面。
document.addEventListener("DOMContentLoaded", () => {
  // 默认连接 edge_demo，便于比赛现场快速打开页面。
  const input = $("sessionId");
  if (input) input.value = sessionId || "edge_demo";
  $("connectBtn")?.addEventListener("click", connect);
  connect();
});