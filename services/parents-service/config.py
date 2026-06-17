from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PORTAL_URL: str = "https://parents.msrit.edu/newparents/index.php"
    SCRAPE_TIMEOUT_MS: int = 120_000   # page load timeout (increased to 2 mins)
    NAV_WAIT_MS: int = 10_000          # wait after login click (increased to 10s)
    MAX_TABLES: int = 20              # cap on how many tables to collect

    class Config:
        env_file = ".env"


settings = Settings()
