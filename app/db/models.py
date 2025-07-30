from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, relationship
from sqlalchemy import Integer, String, Boolean, Text, ForeignKey, DateTime, JSON
from datetime import datetime
from pgvector.sqlalchemy import Vector

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True)
    full_name: Mapped[str] = mapped_column(String, nullable=True)  # Optional full name
    date_of_birth: Mapped[datetime] = mapped_column(DateTime, nullable=True)  # Optional date of birth
    gender: Mapped[str] = mapped_column(String, nullable=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_token: Mapped[str] = mapped_column(String, nullable=True)
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

class Memory(Base):
    __tablename__ = "memories"
    id = mapped_column(Integer, primary_key=True)
    chat_id = mapped_column(String, ForeignKey("chats.id"), index=True)
    content = mapped_column(Text)
    embedding = mapped_column(Vector(1536))
    sender = mapped_column(String)  # 'user', 'ai', 'fact', etc
    created_at = mapped_column(DateTime, default=datetime.utcnow)

class Subscription(Base):
    __tablename__ = "subscriptions"
    id = mapped_column(Integer, primary_key=True)
    user_id = mapped_column(Integer, ForeignKey("users.id"))
    subscription_json = mapped_column(JSON)
    created_at = mapped_column(DateTime, default=datetime.utcnow)