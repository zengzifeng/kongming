from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from ..utils.errors import IntegrationError


# 10 个监控项（顺序无关，用于默认全量请求）。
MONITOR_METRICS = [
    "token_node_count",
    "token_cluster_tpm",
    "token_node_avg_tpm",
    "token_gpu_node_count",
    "kingress_model_tpm",
    "kingress_thirdparty_ratio",
    "kingress_ksyun_ratio",
    "kingress_avg_input_token",
    "kingress_avg_output_token",
    "kingress_cache_hit_rate",
]

# token 侧（自建产能，全局，与客户无关）
TOKEN_METRICS = {
    "token_node_count", "token_cluster_tpm", "token_node_avg_tpm", "token_gpu_node_count",
}
# kingress 侧（售卖，按 ai_consumer 过滤）
KINGRESS_METRICS = {
    "kingress_model_tpm", "kingress_thirdparty_ratio", "kingress_ksyun_ratio",
    "kingress_avg_input_token", "kingress_avg_output_token", "kingress_cache_hit_rate",
}


@dataclass
class SeriesPoint:
    time: str
    value: float | int | None


@dataclass
class ParsedSeries:
    labels: dict
    points: list[SeriesPoint] = field(default_factory=list)

    def latest(self) -> float | int | None:
        for p in reversed(self.points):
            if p.value is not None:
                return p.value
        return None

    def avg(self) -> float:
        vals = [p.value for p in self.points if p.value is not None]
        return sum(vals) / len(vals) if vals else 0.0


@dataclass
class ParsedMonitor:
    start_time: str | None
    end_time: str | None
    # metric name -> list[ParsedSeries]（series 为 null 时是空列表）
    metrics: dict[str, list[ParsedSeries]] = field(default_factory=dict)

    def series_of(self, metric: str) -> list[ParsedSeries]:
        return self.metrics.get(metric, [])


def parse_envelope(envelope: dict) -> ParsedMonitor:
    """把接口信封（code/message/data.metrics[]）解析为结构化对象。

    容错：series 可能为 null（该维度无数据），values 可能为 null；均归一为空列表。
    """
    if not isinstance(envelope, dict):
        raise IntegrationError("监控接口返回非对象", code="INTEGRATION_FAILED")
    if envelope.get("code") not in (0, None):
        raise IntegrationError(
            f"监控接口错误: code={envelope.get('code')} msg={envelope.get('message')}",
            code="INTEGRATION_FAILED",
        )
    data = envelope.get("data") or {}
    parsed = ParsedMonitor(start_time=data.get("start_time"), end_time=data.get("end_time"))
    for m in data.get("metrics", []) or []:
        name = m.get("name")
        if not name:
            continue
        series_list: list[ParsedSeries] = []
        for s in (m.get("series") or []):
            points = [
                SeriesPoint(time=v.get("time"), value=v.get("value"))
                for v in (s.get("values") or [])
            ]
            series_list.append(ParsedSeries(labels=s.get("labels") or {}, points=points))
        parsed.metrics[name] = series_list
    return parsed


class ResourceMonitorClient:
    """资源模型监控数据接口 client。

    - http 模式：GET 真实 url，metrics 以重复参数名传递。
    - mock 模式：返回内置的合成信封（token 全局 + kingress 按 consumer）。
    """

    def __init__(self, mode: str = "mock", base_url: str = "", timeout: int = 30):
        self.mode = mode
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def fetch(self, metrics: list[str] | None = None, model: str | None = None,
              ai_consumer: str | None = None, start_time: str | None = None,
              end_time: str | None = None) -> dict:
        if self.mode == "mock":
            return _mock_envelope(metrics=metrics, ai_consumer=ai_consumer,
                                  start_time=start_time, end_time=end_time)
        if not self.base_url:
            raise IntegrationError("监控接口 base_url 未配置", code="INTEGRATION_FAILED")

        params: list[tuple[str, str]] = []
        for mt in (metrics or []):
            params.append(("metrics", mt))
        if model:
            params.append(("model", model))
        if ai_consumer:
            params.append(("ai_consumer", ai_consumer))
        if start_time:
            params.append(("start_time", start_time))
        if end_time:
            params.append(("end_time", end_time))
        url = self.base_url
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            raise IntegrationError(f"监控接口请求失败: {exc}", code="INTEGRATION_FAILED")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise IntegrationError(f"监控接口返回非 JSON: {exc}", code="INTEGRATION_FAILED")


def _mock_envelope(metrics: list[str] | None, ai_consumer: str | None,
                   start_time: str | None, end_time: str | None) -> dict:
    """合成一个信封：token 侧给全局产能；kingress 侧仅当带 ai_consumer 时给量，
    否则（全局）也给量。用于本地/测试，形状与真实接口一致（含 series 可空）。"""
    want = set(metrics) if metrics else set(MONITOR_METRICS)
    times = ["2026-01-01 00:00:00", "2026-01-01 00:01:00"]

    def series(labels: dict, vals: list) -> dict:
        return {"labels": labels, "values": [
            {"time": t, "value": v} for t, v in zip(times, vals)]}

    catalog = {
        "token_node_count": [series({"inference_model": "DeepSeek-V3.2"}, [9, 9]),
                             series({"inference_model": "GLM-5.2"}, [6, 6])],
        "token_cluster_tpm": [series({"inference_model": "DeepSeek-V3.2"}, [1305, 1464]),
                             series({"inference_model": "GLM-5.2"}, [800, 820])],
        "token_node_avg_tpm": [series({"inference_model": "DeepSeek-V3.2"}, [145, 163]),
                              series({"inference_model": "GLM-5.2"}, [133, 136])],
        "token_gpu_node_count": [series({"label_accelerator": "nvidia-nvidia-h200"}, [25, 25]),
                                series({"label_accelerator": "huawei-Ascend910"}, [4, 4])],
    }
    # kingress 侧：mock 一律给量（真实里无量时接口回 series:null，由解析层容错）。
    kingress = {
        "kingress_model_tpm": [series({"ai_model": "deepseek-v3.2"}, [16329121, 15655659])],
        "kingress_thirdparty_ratio": [series({"ai_model": "deepseek-v3.2"}, [24.94, 26.09])],
        "kingress_ksyun_ratio": [series({"ai_model": "deepseek-v3.2"}, [75.06, 73.92])],
        "kingress_avg_input_token": [series({"ai_model": "deepseek-v3.2"}, [5204, 5059])],
        "kingress_avg_output_token": [series({"ai_model": "deepseek-v3.2"}, [576.1, 517.7])],
        "kingress_cache_hit_rate": [series({"ai_model": "deepseek-v3.2"}, [38.49, 35.49])],
    }
    catalog.update(kingress)

    out_metrics = []
    for name in MONITOR_METRICS:
        if name not in want:
            continue
        out_metrics.append({"name": name, "label": name, "series": catalog.get(name, [])})
    return {
        "code": 0,
        "message": "success",
        "data": {
            "start_time": start_time or times[0],
            "end_time": end_time or times[-1],
            "metrics": out_metrics,
        },
    }
