from __future__ import annotations

import json
import os
from typing import Any

import psycopg


class RagVectorRepo:
    def __init__(self) -> None:
        self.enabled = os.getenv("VECTOR_STORE_PROVIDER", "pgvector").lower() == "pgvector"
        self.dsn = os.getenv("VECTOR_DB_DSN", "postgresql://postgres:postgres@vector-db:5432/mdm")
        self.dim = int(os.getenv("EMBEDDING_DIM", "1024"))
        self._ready = False

    def _conn(self):
        return psycopg.connect(self.dsn)

    def ensure_schema(self) -> None:
        if not self.enabled or self._ready:
            return
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS rag_documents (
                  id BIGSERIAL PRIMARY KEY,
                  doc_key TEXT UNIQUE NOT NULL,
                  content TEXT NOT NULL,
                  metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                  embedding vector({self.dim}) NOT NULL,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            conn.commit()
        self._ready = True

    def upsert_document(self, *, doc_key: str, content: str, embedding: list[float], metadata: dict[str, Any] | None = None) -> None:
        if not self.enabled:
            return
        self.ensure_schema()
        if len(embedding) != self.dim:
            raise ValueError(f"embedding dim mismatch: expected {self.dim}, got {len(embedding)}")
        vec_literal = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rag_documents (doc_key, content, metadata, embedding)
                VALUES (%s, %s, %s::jsonb, %s::vector)
                ON CONFLICT (doc_key)
                DO UPDATE SET
                  content = EXCLUDED.content,
                  metadata = EXCLUDED.metadata,
                  embedding = EXCLUDED.embedding
                """,
                (doc_key, content, json.dumps(metadata or {}), vec_literal),
            )
            conn.commit()

    def search(self, *, embedding: list[float], k: int = 5) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        self.ensure_schema()
        if len(embedding) != self.dim:
            return []
        vec_literal = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT doc_key, content, metadata::text, 1 - (embedding <=> %s::vector) AS score
                FROM rag_documents
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (vec_literal, vec_literal, k),
            )
            rows = cur.fetchall()
        out: list[dict[str, Any]] = []
        for doc_key, content, metadata_text, score in rows:
            out.append({
                "doc_key": doc_key,
                "content": content,
                "metadata": json.loads(metadata_text) if metadata_text else {},
                "score": float(score),
            })
        return out
