"""应用配置：pydantic-settings，从 .env / 环境变量加载，启动时校验关键配置。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 基础设施
    database_url: str = "postgresql+asyncpg://kbrag:kbrag@localhost:5432/kbrag"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "kb_chunks"
    redis_url: str = "redis://localhost:6379"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "kbrag"
    minio_secret_key: str = "kbrag123456"
    minio_bucket: str = "kbrag"
    minio_secure: bool = False

    # 鉴权（本地单用户部署默认关闭；开启后 API 需带 X-API-Key）
    auth_enabled: bool = False
    api_key_query: str = "dev-query-key-change-me"
    api_key_admin: str = "dev-admin-key-change-me"
    app_secret: str = "dev-app-secret-change-me"

    # 云模型（兜底默认值，网页设置优先）
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_api_key: str = ""
    llm_model: str = "qwen-max"
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1024
    rerank_model: str = "gte-rerank-v2"
    vlm_model: str = "qwen-vl-max"

    # 检索与生成
    retrieve_vector_top_k: int = 30
    retrieve_bm25_top_k: int = 30
    rerank_top_k: int = 8
    context_token_budget: int = 5000
    chunk_token_target: int = 400
    chunk_token_max: int = 500

    # 目录监视
    watch_dir_important: str = "./data/kb-drop/important"
    watch_dir_normal: str = "./data/kb-drop/normal"

    # 上传
    upload_max_mb: int = 500

    def validate_startup(self) -> None:
        """启动时校验：密钥存在性、query/admin key 不重复。"""
        if self.api_key_query == self.api_key_admin:
            raise ValueError("API_KEY_QUERY 与 API_KEY_ADMIN 必须不同")
        if self.app_secret.startswith("dev-"):
            self._warn("APP_SECRET 使用开发默认值，生产环境必须替换")
        if not self.llm_api_key:
            self._warn("LLM_API_KEY 未配置（可在网页设置页配置后使用）")

    def _warn(self, msg: str) -> None:
        print(f"[config warning] {msg}")


@lru_cache
def get_settings() -> Settings:
    s = Settings()  # type: ignore[call-arg]
    s.validate_startup()
    return s
