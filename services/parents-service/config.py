from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PORTAL_URL: str = "https://parents.msrit.edu/newparents/index.php"
    SCRAPE_TIMEOUT_MS: int = 30_000   # page load timeout
    NAV_WAIT_MS: int = 3_000          # wait after login click
    MAX_TABLES: int = 20              # cap on how many tables to collect

    class Config:
        env_file = ".env"


settings = Settings()
