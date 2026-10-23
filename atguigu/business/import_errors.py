"""Safe public error classes: never persist raw provider responses or credentials."""


class ImportFailure(Exception):
    def __init__(self, code, message, retryable=False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


class LeaseLost(Exception):
    pass


def classify_error(error, stage="processing"):
    if isinstance(error, ImportFailure):
        return error
    import httpx
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        retryable = status in {408, 409, 425, 429} or status >= 500
        return ImportFailure("MODEL_HTTP_" + str(status), f"模型服务请求失败（HTTP {status}），未生成可用索引", retryable)
    if isinstance(error, (httpx.TimeoutException, httpx.NetworkError, TimeoutError, ConnectionError)):
        return ImportFailure("DEPENDENCY_TIMEOUT", "外部服务超时或网络不可达", True)
    if stage in {"embedding", "images"}:
        return ImportFailure("MODEL_INVALID_RESPONSE", "模型服务配置或响应无效；请检查服务日志和模型配置", isinstance(error, OSError))
    if stage in {"indexing", "storage"}:
        return ImportFailure("STORAGE_UNAVAILABLE", "对象存储或向量存储请求失败；请检查服务连接", True)
    return ImportFailure("PROCESSING_ERROR", "文档处理失败，请检查文件格式和 worker 日志", False)
