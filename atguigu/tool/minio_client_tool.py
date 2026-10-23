from minio import Minio
from urllib3 import PoolManager, Timeout
from atguigu.config.config import MinIoConfig, RuntimeConfig

minio_client = None

def get_minio_client():
    global minio_client
    if minio_client is None:
        if not MinIoConfig.minio_access_key or not MinIoConfig.minio_secret_key:
            raise RuntimeError("请配置 MINIO_ACCESS_KEY 和 MINIO_SECRET_KEY")
        client = Minio(
            endpoint=MinIoConfig.minio_endpoint,
            access_key=MinIoConfig.minio_access_key,
            secret_key=MinIoConfig.minio_secret_key,
            secure=MinIoConfig.secure,
            http_client=PoolManager(timeout=Timeout(total=RuntimeConfig.service_timeout), retries=False),
        )
        if not client.bucket_exists(MinIoConfig.minio_bucket_name):
            client.make_bucket(MinIoConfig.minio_bucket_name)
        # Preserve existing bucket policy; never make existing files public on startup.
        minio_client = client
    return minio_client
