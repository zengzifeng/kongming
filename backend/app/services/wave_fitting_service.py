"""波形拟合服务：算法目录只读、客户关联配置增改查、跑拟合产出客户+集群波形、供求解消费。

时段边界（忙时小时集合）取自 config.WAVE_FIT_BUSY_HOURS，闲时为其 24 小时补集，全局统一。
"""
from __future__ import annotations

from collections import defaultdict

from flask import current_app

from ..algorithms.fitting import FittingInput, get_fitting_algorithm
from ..extensions import db
from ..models import (
    CustomerFittingConfig,
    CustomerUsageHourly,
    FitLevel,
    FittingResult,
    WavePeriod,
)
from ..repositories import (
    CustomerFittingConfigRepository,
    FittingAlgorithmRepository,
    FittingResultRepository,
)
from ..utils.errors import NotFound, ValidationFailed
from ..utils.time import utcnow


class WaveFittingService:
    def __init__(self):
        self.algo_repo = FittingAlgorithmRepository()
        self.config_repo = CustomerFittingConfigRepository()
        self.result_repo = FittingResultRepository()

    # ---------- 时段边界 ----------
    @staticmethod
    def busy_hours() -> frozenset[int]:
        hours = current_app.config.get("WAVE_FIT_BUSY_HOURS", tuple(range(9, 24)))
        return frozenset(int(h) for h in hours)

    @classmethod
    def period_hours(cls, period: str) -> frozenset[int]:
        busy = cls.busy_hours()
        if period == WavePeriod.BUSY:
            return busy
        return frozenset(h for h in range(24) if h not in busy)

    # ---------- 算法目录（只读）----------
    def list_algorithms(self) -> list:
        return self.algo_repo.list_all()

    # ---------- 客户关联配置（可查/可增/可改）----------
    def list_configs(self, ai_consumer=None, model_name=None, period=None) -> list:
        return self.config_repo.list(ai_consumer, model_name, period)

    def get_config(self, config_id: int) -> CustomerFittingConfig:
        cfg = self.config_repo.get(config_id)
        if not cfg:
            raise NotFound("拟合配置不存在", details={"id": config_id})
        return cfg

    def upsert_config(self, data: dict) -> CustomerFittingConfig:
        """按 (ai_consumer, model_name) 自然键 upsert：存在则更新，否则新建。"""
        self._validate_period(data["period"])
        self._validate_algo(data["algo_name"])
        existing = self.config_repo.get_natural(data["ai_consumer"], data["model_name"])
        if existing:
            for key in ("algo_name", "params_json", "enabled"):
                if key in data and data[key] is not None:
                    setattr(existing, key, data[key])
            db.session.commit()
            return existing
        cfg = CustomerFittingConfig(
            ai_consumer=data["ai_consumer"],
            model_name=data["model_name"],
            period=data["period"],
            algo_name=data["algo_name"],
            params_json=data.get("params_json") or {},
            enabled=data.get("enabled", True),
        )
        self.config_repo.add(cfg)
        db.session.commit()
        return cfg

    def update_config(self, config_id: int, patch: dict) -> CustomerFittingConfig:
        cfg = self.get_config(config_id)
        if patch.get("period") is not None:
            self._validate_period(patch["period"])
        if patch.get("algo_name") is not None:
            self._validate_algo(patch["algo_name"])
        for key in ("period", "algo_name", "params_json", "enabled"):
            if key in patch and patch[key] is not None:
                setattr(cfg, key, patch[key])
        db.session.commit()
        return cfg

    def _validate_period(self, period: str) -> None:
        if period not in WavePeriod.ALL:
            raise ValidationFailed(
                "未知时段", details={"allowed": sorted(WavePeriod.ALL)})

    def _validate_algo(self, algo_name: str) -> None:
        algo = self.algo_repo.get_by_name(algo_name)
        if algo is None:
            raise ValidationFailed(
                "拟合算法不存在", details={"algo_name": algo_name})
        if not algo.enabled:
            raise ValidationFailed(
                "拟合算法已停用", details={"algo_name": algo_name})

    # ---------- 跑拟合 ----------
    def run_fitting(self) -> dict:
        """遍历启用的客户配置 → 取历史同时段序列 → 调算法 → 落客户波形；
        再按模型叠加客户波形 → 落集群波形。返回本次落库计数。

        同一次 run 用统一 generated_at，便于后续按批次取「本次拟合」。
        """
        generated_at = utcnow()
        configs = self.config_repo.list_enabled()

        # 客户级波形：{(ai_consumer, model, period): series}
        customer_series: dict[tuple[str, str, str], list] = {}
        customer_written = 0
        for cfg in configs:
            algo_entry = self.algo_repo.get_by_name(cfg.algo_name)
            if algo_entry is None or not algo_entry.enabled:
                continue
            impl = get_fitting_algorithm(algo_entry.entry_ref)
            params = {**(algo_entry.default_params or {}), **(cfg.params_json or {})}
            delta = float(params.get("delta_tpm", 0.0) or 0.0)

            for period in sorted(WavePeriod.ALL):
                hours = self.period_hours(period)
                past = self._past_series(cfg.ai_consumer, cfg.model_name, hours)
                series = impl.fit(FittingInput(
                    ai_consumer=cfg.ai_consumer,
                    model_name=cfg.model_name,
                    period=period,
                    period_hours=hours,
                    past_series=past,
                    delta_tpm=delta,
                    params=params,
                ))
                customer_series[(cfg.ai_consumer, cfg.model_name, period)] = series
                self.result_repo.add(FittingResult(
                    level=FitLevel.CUSTOMER,
                    ai_consumer=cfg.ai_consumer,
                    cluster_name=None,
                    model_name=cfg.model_name,
                    period=period,
                    algo_name=cfg.algo_name,
                    generated_at=generated_at,
                    series_json=[[ts, tpm] for ts, tpm in series],
                    meta_json={"entry_ref": algo_entry.entry_ref, "delta_tpm": delta,
                               "past_points": len(past)},
                ))
                customer_written += 1

        cluster_written = self._overlay_clusters(customer_series, generated_at)
        db.session.commit()
        return {
            "generated_at": generated_at.isoformat(),
            "customer_results": customer_written,
            "cluster_results": cluster_written,
            "configs_seen": len(configs),
        }

    def _overlay_clusters(self, customer_series: dict, generated_at) -> int:
        """集群级波形叠加：同一 deployed_model 下所有客户拟合波形按时间戳求和，
        产出每个部署该模型的集群一条集群波形（本阶段简化：集群共享同模型的客户叠加结果）。
        """
        # 按 (model, period) 叠加所有客户波形 -> {(model, period): {ts: sum_tpm}}
        model_overlay: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for (ai_consumer, model, period), series in customer_series.items():
            for ts, tpm in series:
                model_overlay[(model, period)][ts] += float(tpm)

        # 最新一日各集群的 (cluster_name, deployed_model)
        clusters = self._latest_clusters()
        written = 0
        for (model, period), ts_map in model_overlay.items():
            overlaid = sorted(ts_map.items())
            targets = [c for c in clusters if (c[1] or "").lower() == (model or "").lower()] or [(None, model)]
            for cluster_name, _model in targets:
                self.result_repo.add(FittingResult(
                    level=FitLevel.CLUSTER,
                    ai_consumer=None,
                    cluster_name=cluster_name,
                    model_name=model,
                    period=period,
                    algo_name=None,  # 集群级为聚合结果，无拟合算法
                    generated_at=generated_at,
                    series_json=[[ts, tpm] for ts, tpm in overlaid],
                    meta_json={"source": "customer_overlay"},
                ))
                written += 1
        return written

    @staticmethod
    def _latest_clusters() -> list[tuple[str, str]]:
        """最新监控批次各集群的 (cluster_name, deployed_model)（deployed_model=cluster_name）。"""
        from ..integrations import resource_client

        snap = resource_client().snapshot()
        return [(c.cluster_name, c.deployed_model) for c in snap.clusters]

    @staticmethod
    def _past_series(ai_consumer: str, model_name: str,
                     hours: frozenset[int]) -> list[tuple[str, float]]:
        """取该客户(ai_consumer)+模型历史跑量中「落在时段小时集合内」的整点序列（TPM=Σio/60），升序。"""
        from ..models import MonitorConsumer

        customer = db.session.execute(
            db.select(MonitorConsumer).where(MonitorConsumer.ai_consumer == ai_consumer)
        ).scalar_one_or_none()
        if customer is None:
            return []

        rows = db.session.execute(
            db.select(
                CustomerUsageHourly.data_time,
                CustomerUsageHourly.input_output,
            ).where(
                CustomerUsageHourly.customer_id == customer.id,
                CustomerUsageHourly.model == model_name,
            )
        ).all()

        acc: dict[str, float] = defaultdict(float)
        for data_time, io in rows:
            if data_time.hour not in hours:
                continue
            acc[data_time.isoformat()] += float(io or 0)
        return [(ts, acc[ts] / 60.0) for ts in sorted(acc)]

    # ---------- 供求解消费 ----------
    def build_fitted_series(self, ai_consumer: str, model_name: str,
                            period: str | None = None) -> list[tuple[str, float]]:
        """读取该客户(ai_consumer)+模型最新客户级拟合波形。

        period 为 idle/busy 时只取对应时段；未指定时合并闲忙时。无任何拟合结果时返回 []，
        调用方据此回退原始序列。
        """
        periods = (period,) if period in WavePeriod.ALL else (WavePeriod.IDLE, WavePeriod.BUSY)
        merged: dict[str, float] = {}
        for wave_period in periods:
            res = self.result_repo.latest_for(
                level=FitLevel.CUSTOMER,
                ai_consumer=ai_consumer,
                model_name=model_name,
                period=wave_period,
            )
            if res is None:
                continue
            for ts, tpm in (res.series_json or []):
                merged[ts] = float(tpm)
        return [(ts, merged[ts]) for ts in sorted(merged)]



# 默认算法目录（主数据）：首次启动幂等 seed 到 fitting_algorithms 表。
# entry_ref 必须在 algorithms.fitting.registry 中已注册。
DEFAULT_FITTING_ALGORITHMS = [
    {
        "algo_name": "demo",
        "display_name": "Demo 平移拟合",
        "description": "把前一天相同时段的量原封不动搬到下一时段；增/减量按时段所有点均摊等量增减。",
        "entry_ref": "demo",
        "enabled": True,
        "default_params": {"delta_tpm": 0.0},
    },
]


def ensure_default_fitting_algorithms(app) -> None:
    """幂等 seed 拟合算法目录（已存在的 algo_name 跳过，保留改动）。create_app 调用。"""
    from ..models import FittingAlgorithm

    with app.app_context():
        existing = {
            a.algo_name
            for a in db.session.execute(db.select(FittingAlgorithm)).scalars()
        }
        added = False
        for cfg in DEFAULT_FITTING_ALGORITHMS:
            if cfg["algo_name"] in existing:
                continue
            db.session.add(FittingAlgorithm(
                algo_name=cfg["algo_name"],
                display_name=cfg.get("display_name", ""),
                description=cfg.get("description", ""),
                entry_ref=cfg["entry_ref"],
                enabled=cfg.get("enabled", True),
                default_params=cfg.get("default_params", {}),
            ))
            added = True
        if added:
            db.session.commit()
