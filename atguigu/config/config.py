"""Environment configuration shared by the original import and query graphs."""
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)

def env(name, default=""):
    return os.getenv(name) or default

def flag(name, default=False):
    return env(name, str(default)).lower() in {"1", "true", "yes", "on"}

def local_path(name, default):
    path = Path(env(name, default)).expanduser()
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()

class RuntimeConfig:
    host = env("APP_HOST", "127.0.0.1")
    import_port = int(env("IMPORT_PORT", "8100"))
    query_port = int(env("QUERY_PORT", "8101"))
    platform_port = int(env("PLATFORM_PORT", "8102"))
    data_dir = local_path("DATA_DIR", "var/data")
    upload_max_bytes = int(env("UPLOAD_MAX_MB", "50")) * 1024 * 1024
    service_timeout = float(env("SERVICE_TIMEOUT_SECONDS", "5"))
    model_timeout = float(env("MODEL_TIMEOUT_SECONDS", "60"))
    cors_origins = [s.strip() for s in env("CORS_ORIGINS", "http://127.0.0.1:8100,http://127.0.0.1:8101,http://127.0.0.1:5173,http://localhost:5173").split(",") if s.strip()]

class MineruConfig:
    mineru_token = env("MINERU_TOKEN")
    mineru_base_url = env("MINERU_BASE_URL", "https://mineru.net/api/v4").rstrip("/")
    poll_timeout = int(env("MINERU_POLL_TIMEOUT_SECONDS", "300"))

class LLMConfig:
    openai_api_key = env("OPENAI_API_KEY")
    openai_api_base = env("OPENAI_API_BASE")
    llm_default_model = env("LLM_DEFAULT_MODEL")
    llm_default_temperature = float(env("LLM_DEFAULT_TEMPERATURE", "0"))
    vl_model = env("VL_MODEL", llm_default_model)
    vl_base_url = env("VL_BASE_URL").rstrip("/")
    vl_api_key = env("VL_API_KEY")
    item_model = env("ITEM_MODEL", llm_default_model)

class MinIoConfig:
    minio_endpoint = env("MINIO_ENDPOINT", "127.0.0.1:9000")
    minio_access_key = env("MINIO_ACCESS_KEY")
    minio_secret_key = env("MINIO_SECRET_KEY")
    minio_bucket_name = env("MINIO_BUCKET_NAME", "kb-stage1")
    minio_img_dir = env("MINIO_IMG_DIR", "upload-images")
    secure = flag("MINIO_SECURE")
    public_base_url = env("MINIO_PUBLIC_BASE_URL", f"{'https' if secure else 'http'}://{minio_endpoint}").rstrip("/")

class RerankConfig:
    rerank_base_url = env("RERANK_BASE_URL", "https://emrank.tech/v1").rstrip("/")
    rerank_api_key = env("RERANK_API_KEY")
    model = env("RERANK_MODEL", "Qwen/Qwen3-Reranker-8B")

class EmbeddingConfig:
    embedding_base_url = env("EMBEDDING_BASE_URL", RerankConfig.rerank_base_url).rstrip("/")
    embedding_api_key = env("EMBEDDING_API_KEY", RerankConfig.rerank_api_key)
    model = env("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B")
    dimensions = int(env("EMBEDDING_DIMENSIONS", "4096"))
    if not 1 <= dimensions <= 4096:
        raise ValueError("EMBEDDING_DIMENSIONS 必须在 1 到 4096 之间")

    # Retained only for the legacy manual download script; the graphs use the API.
    bge_m3_path = str(local_path("BGE_M3_PATH", "var/models/bge-m3"))
    bge_m3 = env("BGE_M3", "BAAI/bge-m3")

class MilvusConfig:
    milvus_url = env("MILVUS_URL", "http://127.0.0.1:19530")
    milvus_token = env("MILVUS_TOKEN")
    chunks_collection = env("CHUNKS_COLLECTION", "kb_stage1_chunks")
    item_name_collection = env("ITEM_NAME_COLLECTION", "kb_stage1_items")

class MongoConfig:
    mongo_url = env("MONGO_URL", "mongodb://127.0.0.1:27017/")
    mongo_db_name = env("MONGO_DB_NAME", "kb_stage1")

class McpConfig:
    enabled = flag("WEB_SEARCH_ENABLED")
    mcp_base_url = env("MCP_DASHSCOPE_BASE_URL")
    api_key = env("MCP_API_KEY")

class BusinessConfig:
    mysql_url = env("MYSQL_URL", "mysql+pymysql://127.0.0.1:3306/kb_platform")
    redis_url = env("REDIS_URL", "redis://127.0.0.1:6379/0")
    jwt_secret = env("JWT_SECRET")
    jwt_issuer = "kb-platform"
    jwt_audience = "kb-platform-api"
    jwt_minutes = int(env("JWT_EXPIRE_MINUTES", "60"))


class SettlementConfig:
    min_frequency = max(2, int(env("FAQ_MIN_FREQUENCY", "3")))
    similarity = min(1.0, max(0.8, float(env("FAQ_MINING_SIMILARITY", "0.92"))))
    window_days = max(1, min(365, int(env("SETTLEMENT_WINDOW_DAYS", "30"))))
    max_logs = max(100, int(env("SETTLEMENT_MAX_LOGS", "5000")))
    interval = max(30, int(env("SETTLEMENT_INTERVAL_SECONDS", "300")))
    cache_ttl = max(30, int(env("FAQ_CACHE_TTL_SECONDS", "3600")))
    cache_prefix = env("FAQ_CACHE_PREFIX", "kb-platform:faq:v1:")


class ImportConfig:
    # Stage 4 uses private objects and a dedicated version-aware vector collection.
    bucket = env("KNOWLEDGE_BUCKET", MinIoConfig.minio_bucket_name)
    collection = env("KNOWLEDGE_CHUNKS_COLLECTION", "kb_platform_chunks_v1")
    max_files = int(env("IMPORT_MAX_FILES", "100"))
    batch_max_bytes = int(env("IMPORT_BATCH_MAX_MB", "200")) * 1024 * 1024
    max_expanded_bytes = int(env("IMPORT_EXPANDED_MAX_MB", "200")) * 1024 * 1024
    max_images = int(env("IMPORT_MAX_IMAGES", "100"))
    max_pages = int(env("IMPORT_MAX_PAGES", "500"))
    max_text_chars = int(env("IMPORT_MAX_TEXT_CHARS", "2000000"))
    chunk_size = int(env("IMPORT_CHUNK_SIZE", "800"))
    chunk_overlap = int(env("IMPORT_CHUNK_OVERLAP", "80"))
    embedding_batch_size = int(env("IMPORT_EMBEDDING_BATCH_SIZE", "8"))
    concurrency = int(env("IMPORT_CONCURRENCY", "1"))
    lease_seconds = int(env("IMPORT_LEASE_SECONDS", "90"))
    heartbeat_seconds = int(env("IMPORT_HEARTBEAT_SECONDS", "15"))
    task_timeout_seconds = int(env("IMPORT_TASK_TIMEOUT_SECONDS", "900"))
    max_attempts = int(env("IMPORT_MAX_ATTEMPTS", "3"))
    retry_base_seconds = int(env("IMPORT_RETRY_BASE_SECONDS", "15"))
    poll_seconds = float(env("IMPORT_POLL_SECONDS", "2"))
    pdf_ocr = flag("IMPORT_PDF_OCR")
    image_summaries = flag("IMPORT_IMAGE_SUMMARIES")

    @classmethod
    def validate(cls):
        if not 1 <= cls.concurrency <= 8:
            raise ValueError("IMPORT_CONCURRENCY 必须在 1 到 8 之间")
        if not 0 < cls.heartbeat_seconds < cls.lease_seconds / 2:
            raise ValueError("心跳间隔必须小于租约时长的一半")
        if not 0 <= cls.chunk_overlap < cls.chunk_size <= 8000:
            raise ValueError("切片长度或重叠配置无效")
        if cls.collection in {MilvusConfig.chunks_collection, MilvusConfig.item_name_collection}:
            raise ValueError("知识版本索引必须使用独立集合，禁止复用阶段一集合")


class RagConfig:
    """Bounded permission-aware retrieval; corpus and model thresholds are configurable."""
    dense_limit = int(env("RAG_DENSE_LIMIT", "24"))
    dense_max_limit = int(env("RAG_DENSE_MAX_LIMIT", "96"))
    dense_batch_size = int(env("RAG_DENSE_BATCH_SIZE", "200"))
    lexical_limit = int(env("RAG_LEXICAL_LIMIT", "40"))
    lexical_scan_limit = int(env("RAG_LEXICAL_SCAN_LIMIT", "2000"))
    rrf_k = int(env("RAG_RRF_K", "60"))
    rerank_limit = int(env("RAG_RERANK_LIMIT", "12"))
    final_limit = int(env("RAG_FINAL_LIMIT", "6"))
    dense_min_score = float(env("RAG_DENSE_MIN_SCORE", "0.35"))
    rerank_min_score = float(env("RAG_RERANK_MIN_SCORE", "0.2"))
    lexical_min_score = float(env("RAG_LEXICAL_MIN_SCORE", "0.1"))
    context_max_chars = int(env("RAG_CONTEXT_MAX_CHARS", "14000"))
    history_max_chars = int(env("RAG_HISTORY_MAX_CHARS", "6000"))
    question_max_chars = int(env("RAG_QUESTION_MAX_CHARS", "2000"))
    rewrite_enabled = flag("RAG_REWRITE_ENABLED", True)
    hyde_enabled = flag("RAG_HYDE_ENABLED")
    web_enabled = McpConfig.enabled
    generation_max_tokens = int(env("RAG_GENERATION_MAX_TOKENS", "1600"))
    stream_chunk_chars = int(env("RAG_STREAM_CHUNK_CHARS", "80"))

    @classmethod
    def validate(cls):
        if not 1 <= cls.dense_limit <= cls.dense_max_limit <= 512:
            raise ValueError("RAG 召回数量配置无效")
        if not 1 <= cls.final_limit <= cls.rerank_limit <= 100:
            raise ValueError("RAG 重排数量配置无效")
        if not 1 <= cls.dense_batch_size <= 1000 or not 1 <= cls.lexical_limit <= cls.lexical_scan_limit <= 20000:
            raise ValueError("RAG 检索窗口配置无效")
        if not 0 <= cls.rerank_min_score <= 1 or not -1 <= cls.dense_min_score <= 1 or cls.lexical_min_score < 0:
            raise ValueError("RAG 置信度阈值无效")
        if not 1 <= cls.rrf_k <= 1000 or not 1 <= cls.stream_chunk_chars <= 1000:
            raise ValueError("RAG 融合或流式分片配置无效")
        if not 1000 <= cls.context_max_chars <= 100000 or not 0 <= cls.history_max_chars <= 30000:
            raise ValueError("RAG 上下文长度配置无效")
        if not 1 <= cls.question_max_chars <= 10000 or not 128 <= cls.generation_max_tokens <= 8192:
            raise ValueError("RAG 问题或生成长度配置无效")
