from flask import current_app

from .filing_platform_client import FilingPlatformClient
from .crm_client import CRMClient
from .resource_client import ResourceClient
from .billing_client import BillingClient
from .monitoring_client import MonitoringClient
from .vendor_client import VendorClient


def filing_client() -> FilingPlatformClient:
    return FilingPlatformClient(
        mode=current_app.config["FILING_PLATFORM_MODE"],
        base_url=current_app.config["FILING_PLATFORM_BASE_URL"],
    )


def crm_client() -> CRMClient:
    return CRMClient(mode=current_app.config["CRM_CLIENT_MODE"])


def resource_client() -> ResourceClient:
    return ResourceClient(mode=current_app.config["RESOURCE_CLIENT_MODE"])


def billing_client() -> BillingClient:
    return BillingClient(mode=current_app.config["BILLING_CLIENT_MODE"])


def monitoring_client() -> MonitoringClient:
    return MonitoringClient(mode=current_app.config["MONITORING_CLIENT_MODE"])


def vendor_client() -> VendorClient:
    return VendorClient(mode=current_app.config["VENDOR_CLIENT_MODE"])


__all__ = [
    "filing_client",
    "crm_client",
    "resource_client",
    "billing_client",
    "monitoring_client",
    "vendor_client",
    "FilingPlatformClient",
    "CRMClient",
    "ResourceClient",
    "BillingClient",
    "MonitoringClient",
    "VendorClient",
]
