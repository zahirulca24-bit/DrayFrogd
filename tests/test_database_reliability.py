import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy.orm import sessionmaker

from app.database import (
    build_engine,
    initialize_database,
    normalize_database_url,
    validate_database_configuration,
)
from app.models import RiskRuntimeState


class DatabaseReliabilityTests(unittest.TestCase):
    def test_render_postgres_url_is_normalized_for_psycopg3(self) -> None:
        self.assertEqual(
            normalize_database_url("postgres://user:pass@host:5432/drayfrogd"),
            "postgresql+psycopg://user:pass@host:5432/drayfrogd",
        )
        self.assertEqual(
            normalize_database_url("postgresql://user:pass@host:5432/drayfrogd"),
            "postgresql+psycopg://user:pass@host:5432/drayfrogd",
        )

    def test_production_rejects_ephemeral_sqlite(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Production requires PostgreSQL"):
            validate_database_configuration("sqlite:///./app.db", "production")

    def test_local_sqlite_state_survives_engine_restart(self) -> None:
        with TemporaryDirectory() as directory:
            database_url = f"sqlite:///{Path(directory) / 'restart.db'}"
            first_engine = build_engine(database_url, "development")
            initialize_database(first_engine)
            FirstSession = sessionmaker(bind=first_engine)
            with FirstSession() as session:
                session.add(
                    RiskRuntimeState(
                        id=1,
                        trades_day="2026-07-12",
                        trades_today=4,
                        active_symbols='["BTCUSDT"]',
                    )
                )
                session.commit()
            first_engine.dispose()

            second_engine = build_engine(database_url, "development")
            initialize_database(second_engine)
            SecondSession = sessionmaker(bind=second_engine)
            with SecondSession() as session:
                restored = session.query(RiskRuntimeState).filter(RiskRuntimeState.id == 1).one()
                self.assertEqual(restored.trades_today, 4)
                self.assertEqual(restored.active_symbols, '["BTCUSDT"]')
            second_engine.dispose()

    def test_render_blueprint_uses_linux_commands_and_managed_database(self) -> None:
        blueprint = Path("render.yaml").read_text(encoding="utf-8")
        self.assertIn("python -m pip install", blueprint)
        self.assertIn("python -m app.database_bootstrap", blueprint)
        self.assertIn("python -m uvicorn", blueprint)
        self.assertNotIn("py -3", blueprint)
        self.assertIn("fromDatabase:", blueprint)
        self.assertIn("name: drayfrogd-db", blueprint)
        self.assertIn("property: connectionString", blueprint)
        self.assertIn("APP_ENV", blueprint)
        self.assertIn("value: production", blueprint)


if __name__ == "__main__":
    unittest.main()
