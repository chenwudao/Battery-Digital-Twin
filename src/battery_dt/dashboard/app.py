"""Streamlit dashboard for the battery digital twin.

Start from the project root:

    .venv/bin/streamlit run src/battery_dt/dashboard/app.py
"""

from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from battery_dt.common.config import load_system, topic
from battery_dt.common.timeutil import iso_utc
from battery_dt.storage.db import Database

try:
    import paho.mqtt.client as mqtt
except Exception as exc:  # pragma: no cover - shown in the UI
    mqtt = None
    MQTT_IMPORT_ERROR = exc
else:
    MQTT_IMPORT_ERROR = None


SETTINGS = load_system()
ASSET_ID = SETTINGS["asset_id"]
DB = Database(SETTINGS["storage"]["db_path"])
DB.init()
REFRESH_MS = int(SETTINGS["dashboard"]["refresh_ms"])
STALE_AFTER_S = float(SETTINGS["dashboard"]["stale_after_s"])
OFFLINE_AFTER_S = float(SETTINGS["dashboard"]["offline_after_s"])


class DashboardMQTT:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.latest: dict[str, dict[str, Any]] = {}
        self.connected = False
        self.last_message_wall = 0.0
        self.error: str | None = None
        self.messages = 0
        self.client: mqtt.Client | None = None

    def start(self) -> None:
        if mqtt is None:
            self.error = f"paho-mqtt import failed: {MQTT_IMPORT_ERROR}"
            return
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"dashboard-{uuid.uuid4().hex[:8]}",
            clean_session=True,
            protocol=mqtt.MQTTv311,
        )
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.reconnect_delay_set(1, 10)
        client.connect_async(
            SETTINGS["mqtt"]["host"],
            int(SETTINGS["mqtt"]["port"]),
            keepalive=int(SETTINGS["mqtt"]["keepalive_s"]),
        )
        client.loop_start()
        self.client = client

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code != 0:
            self.error = f"MQTT connection refused: {reason_code}"
            return
        with self.lock:
            self.connected = True
            self.error = None
        base = SETTINGS["mqtt"]["base_topic"].rstrip("/")
        for name in (
            "telemetry",
            "twin_state",
            "twin_alarm",
            "status",
            "meta",
            "whatif_response",
        ):
            client.subscribe(topic(SETTINGS, name), qos=1)
        client.subscribe(f"{base}/whatif/response", qos=1)

    def _on_disconnect(self, *_args) -> None:
        with self.lock:
            self.connected = False

    def _on_message(self, _client, _userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            return
        base = SETTINGS["mqtt"]["base_topic"].rstrip("/")
        suffix = msg.topic.replace(base + "/", "", 1)
        key = {
            "telemetry": "telemetry",
            "twin/state": "twin_state",
            "twin/alarm": "alarm",
            "status": "status",
            "meta": "meta",
            "whatif/response": "whatif_response",
        }.get(suffix, suffix)
        with self.lock:
            self.latest[key] = payload
            self.messages += 1
            self.last_message_wall = time.time()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "latest": dict(self.latest),
                "connected": self.connected,
                "last_message_wall": self.last_message_wall,
                "messages": self.messages,
                "error": self.error,
            }

    def publish(self, topic_name: str, payload: dict[str, Any]) -> bool:
        if self.client is None or not self.connected:
            return False
        result = self.client.publish(
            topic(SETTINGS, topic_name), json.dumps(payload), qos=1
        )
        return result.rc == 0


@st.cache_resource
def mqtt_resource() -> DashboardMQTT:
    resource = DashboardMQTT()
    resource.start()
    return resource


def age_text(seconds: float) -> str:
    if seconds < 1:
        return "<1 s"
    if seconds < 90:
        return f"{seconds:.0f} s"
    return f"{seconds/60:.1f} min"


def status_banner(snapshot: dict[str, Any], twin_state: dict[str, Any] | None) -> None:
    now = time.time()
    last = snapshot.get("last_message_wall") or 0.0
    age = now - last if last else 1e9
    status_payload = snapshot["latest"].get("status", {})
    status = status_payload.get("status")
    if not snapshot["connected"]:
        st.error("MQTT 未连接：请先启动 broker 与相关服务。")
    elif age > OFFLINE_AFTER_S:
        st.error(
            f"数据已过期：最近一条消息 {age_text(age)} 前。"
            "模拟器可能已停止；LWT 为 offline。"
        )
    elif age > STALE_AFTER_S:
        st.warning(f"数据延迟：最近消息 {age_text(age)} 前。")
    elif status == "offline":
        st.warning(
            f"资产状态 offline（{status_payload.get('reason', 'unknown')}），"
            "但 twin 仍在输出。"
        )
    else:
        st.success(f"在线 · 数据新鲜度 {age_text(age)} · 已接收 {snapshot['messages']} 条消息")


def figure_voltage(twin: pd.DataFrame, measured: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if not measured.empty:
        fig.add_trace(
            go.Scatter(
                x=measured["ts_source"],
                y=measured["value"],
                name="实测端电压",
                mode="lines",
                line={"color": "#64748b", "width": 1.4},
            )
        )
    if not twin.empty:
        fig.add_trace(
            go.Scatter(
                x=twin["ts_source"],
                y=twin["v_pred_V"],
                name="twin 预测电压",
                mode="lines",
                line={"color": "#0ea5e9", "width": 2},
            )
        )
    fig.update_layout(
        height=330,
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        legend={"orientation": "h", "y": 1.08},
        yaxis_title="V",
        xaxis_title=None,
    )
    return fig


def figure_temperature(twin: pd.DataFrame, measured: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if not measured.empty:
        fig.add_trace(
            go.Scatter(
                x=measured["ts_source"],
                y=measured["value"],
                name="实测表面温度",
                mode="lines",
                line={"color": "#f59e0b", "width": 1.5},
            )
        )
    if not twin.empty:
        fig.add_trace(
            go.Scatter(
                x=twin["ts_source"],
                y=twin["t_core_C"],
                name="twin 估计核心温度",
                mode="lines",
                line={"color": "#dc2626", "width": 2},
            )
        )
    fig.update_layout(
        height=300,
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        legend={"orientation": "h", "y": 1.08},
        yaxis_title="°C",
    )
    return fig


def figure_soc(twin: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if not twin.empty:
        fig.add_trace(
            go.Scatter(
                x=twin["ts_source"],
                y=twin["soc"] * 100.0,
                name="SoC",
                mode="lines",
                line={"color": "#16a34a", "width": 2},
            )
        )
    fig.update_layout(
        height=260,
        margin={"l": 10, "r": 10, "t": 20, "b": 10},
        yaxis_title="%",
        yaxis_range=[0, 100],
    )
    return fig


def figure_diagnostics(twin: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if twin.empty:
        return fig
    fig.add_trace(
        go.Scatter(
            x=twin["ts_source"],
            y=twin["v_residual_mV"],
            name="电压残差 mV",
            line={"color": "#7c3aed"},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=twin["ts_source"],
            y=twin["t_residual_C"],
            name="温度残差 °C",
            yaxis="y2",
            line={"color": "#ea580c"},
        )
    )
    fig.update_layout(
        height=330,
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        yaxis={"title": "mV"},
        yaxis2={"title": "°C", "overlaying": "y", "side": "right"},
        legend={"orientation": "h", "y": 1.08},
    )
    return fig


def show_alarm_cards(alarms: pd.DataFrame) -> None:
    if alarms.empty:
        st.info("当前没有活动告警。残差与阈值监测仍在运行。")
        return
    for _, alarm in alarms.iterrows():
        severity = str(alarm.get("severity") or "warning")
        title = f"{alarm.get('code')} · {alarm.get('ts_source')}"
        evidence_text = ""
        raw_evidence = alarm.get("evidence_json")
        if raw_evidence:
            try:
                evidence = json.loads(raw_evidence)
            except Exception:
                evidence = {}
            parts = []
            if "peak_thermal_C" in evidence:
                parts.append(f"峰值热残差 {float(evidence['peak_thermal_C']):+.1f} °C")
            if "r0_ratio" in evidence:
                parts.append(f"R0 比率 {float(evidence['r0_ratio']):.2f}")
            if "peak_soc_consistency" in evidence:
                parts.append(f"SoC 一致性 {float(evidence['peak_soc_consistency'])*100:+.1f}%")
            if "cusum_thermal" in evidence:
                parts.append(f"热 CUSUM {float(evidence['cusum_thermal']):.1f}")
            if parts:
                evidence_text = "\n\n**证据：** " + " · ".join(parts)
        text = (
            f"**原因：** {alarm.get('reason')}\n\n"
            f"**建议：** {alarm.get('recommendation')}"
            f"{evidence_text}"
        )
        if severity == "critical":
            st.error(f"### {title}\n{text}")
        else:
            st.warning(f"### {title}\n{text}")


def show_whatif(client: DashboardMQTT, snapshot: dict[str, Any]) -> None:
    st.subheader("如果接下来这样开，会发生什么？")
    st.caption(
        "孪生从当前 SoC、内阻和温度状态向前仿真；结果通过 MQTT "
        "`whatif/request` / `whatif/response` 返回。"
    )
    with st.form("whatif_form"):
        col1, col2, col3 = st.columns(3)
        current = col1.number_input("目标电流 (A)", min_value=0.0, max_value=40.0, value=20.0, step=1.0)
        duration_min = col2.number_input("持续时间 (min)", min_value=1.0, max_value=240.0, value=30.0, step=5.0)
        ambient = col3.number_input("环境温度 (°C)", min_value=-10.0, max_value=50.0, value=35.0, step=1.0)
        submitted = st.form_submit_button("运行场景评估", type="primary")
    if submitted:
        request_id = uuid.uuid4().hex
        payload = {
            "request_id": request_id,
            "current_A": float(current),
            "duration_s": float(duration_min * 60.0),
            "ambient_C": float(ambient),
        }
        if client.publish("whatif_request", payload):
            st.session_state["pending_whatif"] = {"request_id": request_id, "sent": time.time()}
            st.session_state["whatif_response"] = None
            st.info("请求已发送，等待孪生回复……")
        else:
            st.error("MQTT 未连接，无法发送 what-if 请求。")

    response = snapshot["latest"].get("whatif_response")
    pending = st.session_state.get("pending_whatif")
    if response and pending and response.get("request_id") == pending["request_id"]:
        if response.get("error"):
            st.error(response["error"])
            return
        prediction = response.get("prediction", {})
        recommended = response.get("recommended_current_A")
        st.markdown(f"### {response.get('message', '')}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("预计可达截止电压", _duration_text(prediction.get("time_to_cutoff_s")))
        c2.metric("预计到温度上限", _duration_text(prediction.get("time_to_temp_s")))
        c3.metric("场景峰值温度", f"{prediction.get('peak_temp_C', 0):.1f} °C")
        c4.metric("建议电流上限", "—" if recommended is None else f"{recommended:.0f} A")
        st.caption(
            f"输入 {response['request']['current_A']:.0f} A / "
            f"{response['request']['duration_s']/60:.0f} min / "
            f"环境 {response['request']['ambient_C']:.0f} °C；"
            f"末态 SoC 估计 {prediction.get('soc_end', 0)*100:.1f}%。"
        )
        with st.expander("查看 60 秒粒度的预测轨迹"):
            traj = pd.DataFrame(prediction.get("trajectory", []))
            if not traj.empty:
                st.dataframe(traj, width="stretch", hide_index=True)
    elif pending:
        st.info("等待孪生响应（自动刷新中）……")


def _duration_text(seconds: Any) -> str:
    if seconds is None:
        return "不会触发"
    return f"{float(seconds)/60:.0f} min"


def show_data_management(twin: pd.DataFrame) -> None:
    st.subheader("数据层：原始消息与清洗后的窄表")
    try:
        counts = DB.counts()
    except Exception as exc:
        st.error(f"无法读取数据库：{exc}")
        return
    cols = st.columns(6)
    labels = {
        "raw_messages": "raw messages",
        "measurements": "measurements",
        "twin_outputs": "twin outputs",
        "alarms": "alarms",
        "data_gaps": "seq gaps",
        "commands": "commands",
    }
    for col, key in zip(cols, labels):
        col.metric(labels[key], f"{counts.get(key, 0):,}")

    st.markdown(
        "**查询示例**：窄表 `measurements(asset_id, variable, value, unit, ts_source, "
        "ts_ingest, seq, quality)`，原始 JSON 保留在 `raw_messages`。"
    )
    variable = st.selectbox(
        "选择变量",
        ["voltage_V", "current_A", "surface_temp_C", "ambient_temp_C"],
        index=0,
    )
    series = DB.get_series(variable, ASSET_ID, limit=3000)
    if series.empty:
        st.info("暂无数据。")
        return
    st.caption(
        f"最近 {len(series)} 个点；时间列是设备采集时间，`ts_ingest` 是入库墙钟时间。"
    )
    st.dataframe(
        series.tail(20).sort_values("ts_source", ascending=False),
        width="stretch",
        hide_index=True,
    )
    st.download_button(
        "导出 CSV",
        data=series.to_csv(index=False).encode("utf-8"),
        file_name=f"{ASSET_ID}_{variable}.csv",
        mime="text/csv",
    )
    st.code(
        "SELECT variable, value, unit, ts_source, quality\n"
        "FROM measurements\n"
        "WHERE asset_id = 'pack01' AND variable = 'voltage_V'\n"
        "ORDER BY ts_source DESC LIMIT 100;",
        language="sql",
    )
    if not twin.empty:
        st.caption(f"twin 表中最近一条输出时间：{twin['ts_source'].iloc[-1]}")


def main() -> None:
    st.set_page_config(
        page_title="48V 电池组数字孪生",
        layout="wide",
    )
    st_autorefresh(interval=REFRESH_MS, key="twin_dashboard_refresh")
    client = mqtt_resource()
    snapshot = client.snapshot()
    latest_state = snapshot["latest"].get("twin_state")
    if latest_state is None:
        try:
            row = DB.latest_twin(ASSET_ID)
            latest_state = json.loads(row["raw_json"]) if row and row.get("raw_json") else None
        except Exception:
            latest_state = None

    st.title("48 V / 13S 电池组数字孪生")
    st.caption(
        "Plant: 2RC ECM + two-node thermal model + aging drift  |  Twin: "
        "1RC ECM + EKF + RLS + single thermal node. Truth is never published."
    )
    status_banner(snapshot, latest_state)
    if snapshot.get("error"):
        st.caption(f"MQTT: {snapshot['error']}")

    if latest_state is None:
        st.info(
            "等待第一条 twin/state。确认顺序：broker → ingestor → twin → simulator。"
        )
        return

    twin = pd.DataFrame()
    try:
        history_limit = max(600, int(SETTINGS["dashboard"]["history_minutes"] * 60))
        twin = DB.get_twin_history(ASSET_ID, limit=history_limit)
        voltage_series = DB.get_series("voltage_V", ASSET_ID, limit=history_limit)
        temp_series = DB.get_series("surface_temp_C", ASSET_ID, limit=history_limit)
    except Exception:
        st.exception("数据库查询失败")
        voltage_series = pd.DataFrame()
        temp_series = pd.DataFrame()

    active = latest_state.get("active_alarms", [])
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("SoC", f"{latest_state.get('soc_pct', 0):.1f}%", help="EKF 融合电压后的估计")
    m2.metric("SoH (R0)", f"{latest_state.get('soh_pct', 0):.1f}%", help="R0_nominal / R0_est")
    m3.metric("核心温度", f"{latest_state.get('t_core_C', 0):.1f} °C", help="单节点热模型估计")
    remaining = latest_state.get("remaining_min")
    m4.metric(
        "剩余续航",
        "—" if remaining is None else f"{remaining:.0f} min",
        help=f"按近 10 分钟平均电流 {latest_state.get('forecast_current_A', 0):.1f} A 外推",
    )
    m5.metric(
        "活动告警",
        f"{len(active)}",
        delta=", ".join(active) if active else "正常",
        delta_color="inverse" if active else "normal",
    )

    tab_monitor, tab_anomaly, tab_whatif, tab_data = st.tabs(
        ["监控", "异常与解释", "What-if 决策", "数据管理"]
    )

    with tab_monitor:
        c1, c2 = st.columns([1.65, 1])
        with c1:
            st.plotly_chart(figure_voltage(twin, voltage_series), width="stretch", key="monitor_voltage")
        with c2:
            st.plotly_chart(figure_soc(twin), width="stretch", key="monitor_soc")
        c3, c4 = st.columns(2)
        with c3:
            st.plotly_chart(figure_temperature(twin, temp_series), width="stretch", key="monitor_temperature")
        with c4:
            st.plotly_chart(figure_diagnostics(twin), width="stretch", key="monitor_diagnostics")
        st.caption(
            "实测用灰色/橙色，孪生预测用蓝色/红色。模拟时间可加速，"
            "数据新鲜度按 MQTT 到达的墙钟时间计算。"
        )

    with tab_anomaly:
        try:
            alarms = DB.get_active_alarms(ASSET_ID)
        except Exception:
            alarms = pd.DataFrame()
        show_alarm_cards(alarms)
        st.subheader("证据：EKF pre-fit 残差")
        if not twin.empty:
            diag = twin.tail(1200)
            fig = figure_diagnostics(diag)
            st.plotly_chart(fig, width="stretch", key="anomaly_diagnostics")
            recent = diag.tail(1).iloc[0]
            st.caption(
                f"最新电压残差 {recent.get('v_residual_mV', 0):.1f} mV，"
                f"温度残差 {recent.get('t_residual_C', 0):.2f} °C，"
                f"R0 比率 {recent.get('r0_ratio', 0):.2f}。"
                "阈值只在正常运行数据上标定。"
            )
        else:
            st.info("尚无 twin 历史。")

    with tab_whatif:
        show_whatif(client, snapshot)

    with tab_data:
        show_data_management(twin)

    with st.sidebar:
        st.header("操作台")
        st.caption(f"asset: `{ASSET_ID}`")
        st.subheader("改变负载")
        load_current = st.slider("恒流负载 (A)", 0.0, 35.0, 12.0, 1.0)
        load_minutes = st.number_input("持续 (min)", 1.0, 120.0, 10.0, 1.0)
        if st.button("应用负载", width="stretch"):
            ok = client.publish(
                "cmd_load",
                {
                    "current_A": load_current,
                    "duration_s": load_minutes * 60.0,
                },
            )
            (st.success if ok else st.error)("负载命令已发送" if ok else "MQTT 未连接")
        if st.button("清除负载覆盖", width="stretch"):
            client.publish("cmd_load", {"action": "clear"})

        st.divider()
        st.subheader("故障注入")
        st.caption("热故障演示建议先把负载设为 15–20 A，使温升更明显。")
        if st.button("R0 +50%（连接/老化）", width="stretch"):
            ok = client.publish(
                "cmd_fault", {"kind": "r0_increase", "magnitude": 0.5}
            )
            (st.success if ok else st.error)("R0 故障已注入" if ok else "MQTT 未连接")
        st.caption("R0 的快速分类需要电流有变化；恒流覆盖下可能先报为电压异常。")
        if st.button("冷却失效（hA → 5%）", width="stretch"):
            client.publish(
                "cmd_fault", {"kind": "cooling_failure", "magnitude": 0.95}
            )
            st.warning("已注入。建议同时施加 15–20 A 负载。")
        if st.button("电压传感器 +0.5 V", width="stretch"):
            client.publish(
                "cmd_fault",
                {"kind": "voltage_sensor_drift", "magnitude": 0.5},
            )
            st.warning("已注入电压偏置。")
        if st.button("清除故障", width="stretch"):
            client.publish("cmd_fault", {"kind": "clear"})

        st.divider()
        st.subheader("现场检查")
        st.markdown(
            "- `mosquitto_sub -v -t 'dt/#'` 看原始消息\n"
            "- 杀掉 simulator 进程可演示 LWT offline\n"
            "- 数据新鲜度 > 8 s 会变黄，> 15 s 变红\n"
            "- 模拟器结束后 twin 仍在，历史表可查"
        )
        st.caption(f"刷新：{REFRESH_MS} ms · 当前时刻 {iso_utc()}")


if __name__ == "__main__":
    main()
