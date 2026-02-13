"""
SQLAlchemy database models.

All models are organized by domain for better maintainability:
- base: Base declarative class
- user: User account models  
- influencer: Influencer/AI persona models
- chat: Chat, messages, and call records
- billing: Subscriptions, payments, and credits
- relationship: Relationship state tracking
- content: Moderation and re-engagement
- system: System configuration
- verification: Identity verification

Import any model from this module:
    from app.db.models import User, Influencer, Chat, Message
"""

# Base class (must be imported first)
from .base import Base

# User models
from .user import User

# Influencer models
from .influencer import Influencer, InfluencerFollower, PreInfluencer

# Chat and messaging models
from .chat import Chat, Message, Chat18, Message18, Memory, CallRecord

# Billing and subscription models
from .billing import (
    Subscription,
    Pricing,
    InfluencerWallet,
    InfluencerCreditTransaction,
    DailyUsage,
    InfluencerSubscriptionPlan,
    InfluencerSubscription,
    InfluencerSubscriptionAddonPurchase,
    InfluencerSubscriptionPayment,
    PayPalTopUp,
)

# Relationship models
from .relationship import RelationshipState

# Content moderation and engagement
from .content import ContentViolation, ReEngagementLog

# System models
from .system import SystemPrompt

# Verification models
from .verification import IdentityVerification

# API usage tracking
from .api_usage import ApiUsageLog

# Export all models
__all__ = [
    # Base
    "Base",
    # User
    "User",
    # Influencer
    "Influencer",
    "InfluencerFollower",
    "PreInfluencer",
    # Chat
    "Chat",
    "Message",
    "Chat18",
    "Message18",
    "Memory",
    "CallRecord",
    # Billing
    "Subscription",
    "Pricing",
    "InfluencerWallet",
    "InfluencerCreditTransaction",
    "DailyUsage",
    "InfluencerSubscriptionPlan",
    "InfluencerSubscription",
    "InfluencerSubscriptionAddonPurchase",
    "InfluencerSubscriptionPayment",
    "PayPalTopUp",
    # Relationship
    "RelationshipState",
    # Content
    "ContentViolation",
    "ReEngagementLog",
    # System
    "SystemPrompt",
    # Verification
    "IdentityVerification",
    # API Usage
    "ApiUsageLog",
    "ApiUsageMonthly",
]
