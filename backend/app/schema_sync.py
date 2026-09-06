from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.schema import Column

from app.database import Base, engine

MIGRATION_VERSION = 10


def _has_column(conn, table: str, column: str) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :table AND column_name = :column)"
            ),
            {"table": table, "column": column},
        ).scalar()
    )


def _drop_legacy_received_at(conn) -> None:
    # Older prototypes stored the message date as received_at (NOT NULL).
    # The ORM now writes sent_at, so leftover received_at blocks every insert.
    if not _has_column(conn, "messages", "received_at"):
        return
    if _has_column(conn, "messages", "sent_at"):
        conn.execute(
            text(
                "UPDATE messages SET sent_at = received_at "
                "WHERE sent_at IS NULL AND received_at IS NOT NULL"
            )
        )
        conn.execute(text("ALTER TABLE messages DROP COLUMN received_at"))
    else:
        conn.execute(text("ALTER TABLE messages RENAME COLUMN received_at TO sent_at"))
    conn.execute(text("ALTER TABLE messages ALTER COLUMN sent_at DROP NOT NULL"))


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
        _drop_legacy_received_at(conn)
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
            return _has_column(conn, table, column)

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
        _drop_legacy_received_at(conn)
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
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_user_gmail_id "
                "ON messages (user_id, gmail_message_id) "
                "WHERE gmail_message_id IS NOT NULL"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_attachments_message_checksum "
                "ON attachments (message_id, checksum)"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_pdf_pages_attachment_page "
                "ON pdf_pages (attachment_id, page_number)"
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_status ON messages (status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_user_id ON messages (user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_parent_id ON messages (parent_message_id)"))
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_user_fixture_key "
                "ON messages (user_id, fixture_key) "
                "WHERE fixture_key IS NOT NULL"
            )
        )
        conn.execute(
            text("UPDATE messages SET source = 'gmail' WHERE source IS NULL OR source = ''")
        )
        conn.execute(
            text(
                "DELETE FROM classifications a USING classifications b "
                "WHERE a.message_id = b.message_id AND a.category = b.category "
                "AND (a.created_at < b.created_at OR (a.created_at = b.created_at AND a.id < b.id))"
            )
        )
        conn.execute(
            text(
                "DELETE FROM extracted_fields a USING extracted_fields b "
                "WHERE a.message_id = b.message_id AND a.field = b.field "
                "AND (a.created_at < b.created_at OR (a.created_at = b.created_at AND a.id < b.id))"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_classifications_message_category "
                "ON classifications (message_id, category)"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_extracted_fields_message_field "
                "ON extracted_fields (message_id, field)"
            )
        )
        conn.execute(
            text(
                "UPDATE gmail_credentials SET sync_enabled = true "
                "WHERE refresh_token_encrypted IS NOT NULL "
                "AND refresh_token_encrypted <> '' "
                "AND sync_enabled = false"
            )
        )
        conn.execute(
            text(
                "INSERT INTO app_schema_migrations (version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": MIGRATION_VERSION},
        )
