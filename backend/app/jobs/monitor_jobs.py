from ..services import ResourceMonitorService, UsageAggregationService, VendorRuntimeSyncService
from .decorators import with_job_log


@with_job_log("resource_monitor_collect")
def resource_monitor_collect(app):
    """后台定时采集资源模型监控数据：全局拉集群/GPU 产能 + 逐 enabled consumer 拉客户瞬时 TPM。"""
    batch = ResourceMonitorService().run_collection(triggered_by="cron")
    return f"batch={batch.batch_no} status={batch.status} clusters={batch.cluster_rows} consumers={batch.consumer_rows}"


@with_job_log("usage_hourly_aggregate")
def usage_hourly_aggregate(app):
    """把上一小时 consumer_model_tpm 按 客户×模型 聚合写入 customer_usage_hourly。"""
    result = UsageAggregationService().aggregate_hourly()
    return f"hour={result.get('hour_start')} rows={result.get('rows')}"


def vendor_runtime_sync_fixed(app):
    """固定后端逻辑：每分钟用最新 consumer_model_tpm 刷新三方实跑与冗余，不写入 job_schedules。"""
    with app.app_context():
        result = VendorRuntimeSyncService().sync_from_latest_consumer_tpm()
        app.logger.info("vendor runtime synced: %s", result)
        return result
