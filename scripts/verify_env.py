"""Verify EduAgent configuration, local models, PostgreSQL and Milvus."""

from __future__ import annotations

import asyncio
import platform
import socket
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _ok(message: str) -> None:
    print(f"[OK] {message}")


def _fail(message: str) -> None:
    print(f"[FAIL] {message}")


def _check_port(host: str, port: int, service: str) -> bool:
    try:
        with socket.create_connection((host, port), timeout=3):
            _ok(f"{service} TCP reachable at {host}:{port}")
            return True
    except OSError as exc:
        _fail(f"{service} TCP unavailable at {host}:{port}: {exc}")
        return False


def _check_files(settings) -> bool:
    checks = {
        "PostgreSQL schema": PROJECT_ROOT / "scripts" / "init_db.sql",
        "frontend package": PROJECT_ROOT / "frontend" / "package.json",
        "BGE-M3": PROJECT_ROOT / "backend" / settings.bge_m3_model_path,
        "reranker": PROJECT_ROOT / "backend" / settings.reranker_model_path,
        "classifier": PROJECT_ROOT / "backend" / settings.classifier_model_path,
        "fine-tuned classifier": PROJECT_ROOT / "backend" / settings.finetuned_classifier_path,
    }
    passed = True
    for label, path in checks.items():
        if path.exists():
            _ok(f"{label}: {path.relative_to(PROJECT_ROOT)}")
        else:
            _fail(f"{label} missing: {path}")
            passed = False
    return passed


async def _check_postgres(settings) -> bool:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            value = await connection.scalar(text("SELECT 1"))
            table_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
        _ok(f"PostgreSQL query succeeded (SELECT {value}, public tables={table_count})")
        return True
    except Exception as exc:
        _fail(f"PostgreSQL query failed: {exc}")
        return False
    finally:
        await engine.dispose()


def _check_milvus(settings) -> bool:
    from pymilvus import MilvusClient

    client = None
    try:
        client = MilvusClient(uri=f"http://{settings.milvus_host}:{settings.milvus_port}")
        collections = client.list_collections()
        _ok(f"Milvus query succeeded (collections={collections})")
        return True
    except Exception as exc:
        _fail(f"Milvus query failed: {exc}")
        return False
    finally:
        if client is not None:
            client.close()


async def _run() -> int:
    passed = True

    if sys.version_info[:2] == (3, 11):
        _ok(f"Python {platform.python_version()}")
    else:
        _fail(f"Python 3.11 required, current version is {platform.python_version()}")
        passed = False

    try:
        from backend.config import get_settings

        settings = get_settings()
        _ok(".env.local loaded and required settings validated")
    except Exception as exc:
        _fail(f"configuration validation failed: {exc}")
        return 1

    passed = _check_files(settings) and passed
    postgres_port_open = _check_port(settings.db_host, settings.db_port, "PostgreSQL")
    milvus_port_open = _check_port(settings.milvus_host, settings.milvus_port, "Milvus")

    if postgres_port_open:
        passed = await _check_postgres(settings) and passed
    else:
        passed = False

    if milvus_port_open:
        passed = _check_milvus(settings) and passed
    else:
        passed = False

    if passed:
        print("\nEduAgent environment is ready.")
        return 0

    print("\nEduAgent environment check failed. Start Docker services and retry.")
    return 1


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
