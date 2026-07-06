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

    POLICY_SNAPSHOT_RETENTION_DAYS = 180
    ALERT_THRESHOLD_LOW = 0.7
    ALERT_THRESHOLD_HIGH = 1.5

    DASHBOARD_CACHE_TTL_SECONDS = 60


class DevConfig(BaseConfig):
    DEBUG = True


class TestConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SCHEDULER_ENABLED = False


class ProdConfig(BaseConfig):
    DEBUG = False


CONFIG_MAP = {
    "dev": DevConfig,
    "test": TestConfig,
    "prod": ProdConfig,
}
