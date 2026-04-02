import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AiConversationMemory(Base):
    """Memoria conversacional por usuario+tienda (usada por memory.py)."""
    __tablename__ = "ai_conversation_memory"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    store_id: Mapped[str | None] = mapped_column(String(100))
    user_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    role: Mapped[str | None] = mapped_column(String(20), server_default=text("'system'"))
    content: Mapped[str | None] = mapped_column(Text, server_default=text("''"))
    pos_memory: Mapped[dict | None] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    conversation_history: Mapped[dict | None] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    last_data_items: Mapped[dict | None] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    last_store_id: Mapped[str | None] = mapped_column(String(100))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


class AiStoreLearning(Base):
    """Aprendizaje por tienda: few-shot examples (usada por store_learning.py)."""
    __tablename__ = "ai_store_learnings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(String(100), nullable=False)
    interaction_type: Mapped[str | None] = mapped_column(String(20))
    user_question: Mapped[str | None] = mapped_column(Text)
    detected_intent: Mapped[str | None] = mapped_column(String(100))
    resolved_action: Mapped[str | None] = mapped_column(Text)
    result_summary: Mapped[str | None] = mapped_column(Text)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


class AiDailyUsage(Base):
    """Conteo diario de consultas IA por organización."""
    __tablename__ = "ai_daily_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    usage_date: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    query_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


class AiSuperpower(Base):
    __tablename__ = "ai_superpower"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AiSuperpowerSession(Base):
    __tablename__ = "ai_superpower_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    superpower_id: Mapped[int] = mapped_column(Integer, ForeignKey("ai_superpower.id"), nullable=False)
    store_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    input_data: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    output_data: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
