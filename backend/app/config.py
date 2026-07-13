import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)


class BaseConfig:
    SECRET_KEY = os.environ.get("KONGMING_SECRET", "dev-secret")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "KONGMING_DATABASE_URI",
        f"sqlite:///{INSTANCE_DIR / 'kongming.db'}",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_SORT_KEYS = False

    SCHEDULER_ENABLED = True

    FILING_PLATFORM_MODE = os.environ.get("FILING_PLATFORM_MODE", "mock")
    FILING_PLATFORM_BASE_URL = os.environ.get("FILING_PLATFORM_BASE_URL", "")
    CRM_CLIENT_MODE = os.environ.get("CRM_CLIENT_MODE", "mock")
    RESOURCE_CLIENT_MODE = os.environ.get("RESOURCE_CLIENT_MODE", "mock")
    BILLING_CLIENT_MODE = os.environ.get("BILLING_CLIENT_MODE", "mock")
    MONITORING_CLIENT_MODE = os.environ.get("MONITORING_CLIENT_MODE", "mock")
    VENDOR_CLIENT_MODE = os.environ.get("VENDOR_CLIENT_MODE", "mock")

    # ---- 资源模型监控数据接口（winlink kingress）----
    RESOURCE_MONITOR_MODE = os.environ.get("RESOURCE_MONITOR_MODE", "http")  # mock | http
    RESOURCE_MONITOR_BASE_URL = os.environ.get(
        "RESOURCE_MONITOR_BASE_URL",
        "http://winlink.sre.ksyun.com/ksp_service/api/v1/kingress/resource-model-monitor-data/list",
    )
    RESOURCE_MONITOR_TIMEOUT = int(os.environ.get("RESOURCE_MONITOR_TIMEOUT", "30"))

    POLICY_SNAPSHOT_RETENTION_DAYS = 180
    ALERT_THRESHOLD_LOW = 0.7
    ALERT_THRESHOLD_HIGH = 1.5

    DASHBOARD_CACHE_TTL_SECONDS = 60

    # ---- 时段(time_period)策略口径开关（默认生效，可回退）----
    # 自建只算「本模型自建集群 provider」提供的量（provider 白名单）
    SELF_PROVIDER_WHITELIST_ENABLED = os.environ.get("KONGMING_SELF_PROVIDER_WHITELIST", "1") == "1"
    # 整户剔除的客户（转售/网络客户，量不计入切量考量），逗号分隔 customer_code
    EXCLUDE_CUSTOMER_CODES = tuple(
        c for c in os.environ.get("KONGMING_EXCLUDE_CUSTOMER_CODES", "C0005").split(",") if c
    )
    # 模型级供需再平衡：跨模型把富余机器挪给紧缺模型（仅满足峰值可承接 + 正收益 + 一台只搬一次）
    MODEL_REBALANCE_ENABLED = os.environ.get("KONGMING_MODEL_REBALANCE", "1") == "1"

    # ---- 波形拟合(wave fitting)口径 ----
    # 忙时 = 9-24（包左不包右，即 9..23）；闲时 = 其 24 小时补集 = 0..8。所有客户共用此全局边界。
    WAVE_FIT_BUSY_HOURS = tuple(
        int(h) for h in os.environ.get(
            "KONGMING_WAVE_FIT_BUSY_HOURS",
            "9,10,11,12,13,14,15,16,17,18,19,20,21,22,23",
        ).split(",") if h != ""
    )
    # 是否用拟合波形覆盖 time_period 求解输入的 tpm_series（关闭时退化为直接搬原始序列）
    WAVE_FIT_ENABLED = os.environ.get("KONGMING_WAVE_FIT_ENABLED", "1") == "1"


class DevConfig(BaseConfig):
    DEBUG = True


class TestConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SCHEDULER_ENABLED = False
    # 测试基线：默认关闭新口径/再平衡，既有用例不受扰动；需要时用例内显式开启。
    SELF_PROVIDER_WHITELIST_ENABLED = False
    EXCLUDE_CUSTOMER_CODES = ()
    MODEL_REBALANCE_ENABLED = False
    # 拟合接入求解默认关闭，既有 time_period 用例仍消费原始 tpm_series，不受扰动。
    WAVE_FIT_ENABLED = False
    # 监控接口固定走 mock，避免测试触网。
    RESOURCE_MONITOR_MODE = "mock"


class ProdConfig(BaseConfig):
    DEBUG = False


CONFIG_MAP = {
    "dev": DevConfig,
    "test": TestConfig,
    "prod": ProdConfig,
}
