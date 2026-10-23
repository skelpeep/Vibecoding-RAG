"""Private version-scoped MinIO objects; clients receive API file IDs, never URLs."""
from functools import lru_cache
from io import BytesIO
from pathlib import PurePosixPath

from minio import Minio
from minio.error import S3Error
from urllib3 import PoolManager, Timeout

from atguigu.config.config import ImportConfig, MinIoConfig, RuntimeConfig


class KnowledgeStorage:
    def __init__(self):
        ImportConfig.validate()
        self.bucket = ImportConfig.bucket
        self.client = Minio(MinIoConfig.minio_endpoint, access_key=MinIoConfig.minio_access_key,
                            secret_key=MinIoConfig.minio_secret_key, secure=MinIoConfig.secure,
                            http_client=PoolManager(timeout=Timeout(total=RuntimeConfig.service_timeout), retries=False))
        self.anonymous = Minio(MinIoConfig.minio_endpoint, secure=MinIoConfig.secure,
                              http_client=PoolManager(timeout=Timeout(total=RuntimeConfig.service_timeout), retries=False))
        if not self.client.bucket_exists(self.bucket):
            try:
                self.client.make_bucket(self.bucket)
            except S3Error as error:
                if error.code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                    raise
        # A public bucket would bypass every API authorization check. Read only;
        # never change an existing installation's bucket policy here.
        try:
            self.client.get_bucket_policy(self.bucket)
        except S3Error as error:
            if error.code not in {"NoSuchBucketPolicy", "AccessDenied"}:
                raise
        else:
            raise RuntimeError("知识文件桶存在匿名访问策略，请改用独立私有桶")

    def _validate(self, key, bucket):
        if bucket not in (None, self.bucket):
            raise ValueError("文件不属于知识存储桶")
        if not key.startswith("units/") or "\\" in key or ".." in PurePosixPath(key).parts:
            raise ValueError("非法知识对象键")

    def put_bytes(self, object_key, data, content_type="application/octet-stream", bucket=None):
        self._validate(object_key, bucket)
        self.client.put_object(self.bucket, object_key, BytesIO(data), len(data), content_type=content_type)
        self._assert_private(object_key)

    def _assert_private(self, object_key):
        # Least-privilege upload accounts may not inspect bucket policies. An actual
        # unsigned GET of each exact object is the relevant access boundary.
        try:
            response = self.anonymous.get_object(self.bucket, object_key, offset=0, length=1)
        except S3Error as error:
            if error.code == "AccessDenied":
                return
            raise
        else:
            response.close()
            response.release_conn()
            raise RuntimeError("知识对象可匿名读取；请将桶配置为私有后再导入")

    def get_bytes(self, object_key, bucket=None):
        self._validate(object_key, bucket)
        self._assert_private(object_key)
        response = self.client.get_object(self.bucket, object_key)
        try:
            # Prevent a replaced/oversized source object from exhausting worker memory.
            data = response.read(max(RuntimeConfig.upload_max_bytes, ImportConfig.max_expanded_bytes) + 1)
            if len(data) > max(RuntimeConfig.upload_max_bytes, ImportConfig.max_expanded_bytes):
                raise ValueError("存储对象超出读取限额")
            return data
        finally:
            response.close()
            response.release_conn()

    def delete_object(self, object_key, bucket=None):
        self._validate(object_key, bucket)
        self.client.remove_object(self.bucket, object_key)


@lru_cache
def get_storage():
    return KnowledgeStorage()
