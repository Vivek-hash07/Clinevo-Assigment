from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.schema import Column

from app.database import Base, engine

MIGRATION_VERSION = 4


def _default_clause(column: Column) -> str:
    if column.nullable:
        return ""
    if column.server_default is not None:
        return " DEFAULT now()"
    type_name = type(column.type).__name__
    if type_name == "JSONB":
        return " DEFAULT '{}'::jsonb"
    if type_name == "Boolean":
        return " DEFAULT false"
    if type_name in {"Integer", "Float"}:
        arg = column.default.arg if column.default is not None and not callable(column.default.arg) else 0
        if callable(arg):
            arg = 0
        return f" DEFAULT {arg}"
    if type_name in {"DateTime"}:
        return " DEFAULT now()"
    arg = column.default.arg if column.default is not None else ""
    if callable(arg) or arg is None:
        arg = ""
    if isinstance(arg, str):
        return f" DEFAULT '{arg.replace(chr(39), chr(39)+chr(39))}'"
    return " DEFAULT ''"


def ensure_schema() -> None:
    from app import models  # noqa: F401

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS app_schema_migrations ("
                "version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
        )
        applied = conn.execute(
            text("SELECT 1 FROM app_schema_migrations WHERE version = :version"),
            {"version": MIGRATION_VERSION},
        ).scalar()
        if applied:
            return

    Base.metadata.create_all(bind=engine)
    pg = postgresql.dialect()
    with engine.begin() as conn:
        def has_column(table: str, column: str) -> bool:
            return bool(
                conn.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = :table AND column_name = :column)"
                    ),
                    {"table": table, "column": column},
                ).scalar()
            )

        for table in Base.metadata.sorted_tables:
            present = conn.execute(text("SELECT to_regclass(:name)"), {"name": f"public.{table.name}"}).scalar()
            if not present:
                continue
            for column in table.columns:
                type_sql = column.type.compile(dialect=pg)
                null_sql = "NULL" if column.nullable else f"NOT NULL{_default_clause(column)}"
                conn.execute(
                    text(
                        f'ALTER TABLE "{table.name}" ADD COLUMN IF NOT EXISTS '
                        f'"{column.name}" {type_sql} {null_sql}'
                    )
                )
        # Compatibility defaults for columns created by the earlier prototype.
        if has_column("users", "full_name"):
            conn.execute(text("ALTER TABLE users ALTER COLUMN full_name SET DEFAULT ''"))
            conn.execute(
                text("UPDATE users SET name = full_name WHERE name = '' AND full_name <> ''")
            )
        if has_column("users", "email_verified"):
            conn.execute(text("ALTER TABLE users ALTER COLUMN email_verified SET DEFAULT false"))
        if has_column("audit_events", "actor"):
            conn.execute(text("ALTER TABLE audit_events ALTER COLUMN actor SET DEFAULT 'system'"))
        if has_column("audit_events", "payload_json"):
            conn.execute(text("ALTER TABLE audit_events ALTER COLUMN payload_json SET DEFAULT '{}'"))
        if has_column("gmail_credentials", "google_email"):
            conn.execute(text("ALTER TABLE gmail_credentials ALTER COLUMN google_email SET DEFAULT ''"))
        if has_column("gmail_credentials", "encrypted_refresh_token"):
            conn.execute(
                text("ALTER TABLE gmail_credentials ALTER COLUMN encrypted_refresh_token SET DEFAULT ''")
            )
        for table_name in (
            "users",
            "audit_events",
            "password_reset_tokens",
            "refresh_tokens",
            "gmail_credentials",
        ):
            if has_column(table_name, "created_at"):
                conn.execute(
                    text(f'ALTER TABLE "{table_name}" ALTER COLUMN created_at SET DEFAULT now()')
                )
            if has_column(table_name, "updated_at"):
                conn.execute(
                    text(f'ALTER TABLE "{table_name}" ALTER COLUMN updated_at SET DEFAULT now()')
                )
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_google_sub ON users (google_sub)"))
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_password_reset_tokens_hash "
                "ON password_reset_tokens (token_hash)"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_refresh_tokens_hash "
                "ON refresh_tokens (token_hash)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO app_schema_migrations (version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": MIGRATION_VERSION},
        )
