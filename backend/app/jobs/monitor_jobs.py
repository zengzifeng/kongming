from ..services import ResourceMonitorService, UsageAggregationService
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
