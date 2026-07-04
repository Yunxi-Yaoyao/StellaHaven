from pydantic_settings import BaseSettings
from urllib.parse import quote_plus

class  Settings(BaseSettings):
    app_name: str = "StellaHaven"
    app_port: int = 12031

    #数据库
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "stalla"
    postgres_password: str = "St@106954021"
    postgres_db: str = "stella"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{quote_plus(self.postgres_password)}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
    
    model_config = {
        "env_file": ".env",      # 自动读项目根目录的 .env
        "env_file_encoding": "utf-8",
    }

settings = Settings()  # 全局单例，其他模块 import 它