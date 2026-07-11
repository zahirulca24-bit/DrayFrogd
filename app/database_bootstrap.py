from __future__ import annotations

from app.config import settings
from app.database import DATABASE_URL, initialize_database


def main() -> None:
    initialize_database()
    dialect = "sqlite" if DATABASE_URL.startswith("sqlite://") else "postgresql"
    print(f"Database bootstrap complete: environment={settings.app_env}, dialect={dialect}")


if __name__ == "__main__":
    main()
