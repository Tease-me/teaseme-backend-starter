from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, relationship
from sqlalchemy import Integer, String, Text, ForeignKey, DateTime
from datetime import datetime
from pgvector.sqlalchemy import Vector

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    chats = relationship("Chat", backref="user")

class Chat(Base):
    __tablename__ = "chats"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # UUID string
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    persona_id: Mapped[str] = mapped_column(String)  # Qual persona/mulher neste chat
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    messages = relationship("Message", backref="chat", cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id"), index=True)
    sender: Mapped[str] = mapped_column(String)  # 'user' ou 'ai'
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=True)

class UserScore(Base):
    __tablename__ = "user_scores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    persona_id: Mapped[str] = mapped_column(String)
    score_type: Mapped[str] = mapped_column(String)
    value: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)