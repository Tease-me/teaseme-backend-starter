"""
Seed script for Influencer Subscription Plans.

Usage:
    poetry run python -m app.scripts.seed_subscription_plans
"""
import asyncio
from sqlalchemy import select
from app.db.session import SessionLocal
from app.db.models import InfluencerSubscriptionPlan


async def main():
    """Seed subscription plans."""
    print("🌱 Seeding subscription plans...")
    
    async with SessionLocal() as db:
        # Check what plans already exist
        result = await db.execute(select(InfluencerSubscriptionPlan))
        existing = result.scalars().all()
        existing_names = {p.plan_name for p in existing}
        
        print(f"📋 Found {len(existing)} existing plans: {', '.join(existing_names)}")
        
        plans = [
            InfluencerSubscriptionPlan(
                plan_name="Basic",
                price_cents=9900, 
                currency="USD",
                interval="monthly",
                plan_type="recurring",
                description="$99/month - 100 minutes included. Monthly recurring, 18+ only.",
                features={
                    "credits_per_month": 9900,
                    "minutes_equivalent": 100,
                    "priority_support": False,
                },
                display_order=1,
                is_active=True,
                is_featured=False,
            ),
            
            InfluencerSubscriptionPlan(
                plan_name="Plus",
                price_cents=14900, 
                currency="USD",
                interval="monthly",
                plan_type="recurring",
                description="$149/month - 200 minutes included. Monthly recurring, 18+ only.",
                features={
                    "credits_per_month": 14900,
                    "minutes_equivalent": 200,
                    "priority_support": True,
                },
                display_order=2,
                is_active=True,
                is_featured=True,
            ),
            
            InfluencerSubscriptionPlan(
                plan_name="Premium",
                price_cents=19900,
                currency="USD",
                interval="monthly",
                plan_type="recurring",
                description="$199/month - 350 minutes included. Monthly recurring, 18+ only.",
                features={
                    "credits_per_month": 19900,
                    "minutes_equivalent": 350,
                    "priority_support": True,
                    "exclusive_content": True,
                },
                display_order=3,
                is_active=True,
                is_featured=False,
            ),
            
            # ========================================
            # ADD-ON PACKS (Top-ups, require subscription)
            # ========================================
            InfluencerSubscriptionPlan(
                plan_name="$29 Add-on",
                price_cents=2900,  # $29
                currency="USD",
                interval="addon", 
                plan_type="addon",
                description="$29 add-on pack. Requires active subscription.",
                features={
                    "credits_granted": 2900,  
                    "requires_subscription": True,
                    "stackable": True,
                },
                display_order=10,
                is_active=True,
                is_featured=False,
            ),
            
            InfluencerSubscriptionPlan(
                plan_name="$49 Add-on",
                price_cents=4900,  # $49
                currency="USD",
                interval="addon",
                plan_type="addon",
                description="$49 add-on pack. Requires active subscription.",
                features={
                    "credits_granted": 4900,  # Pay $49, get $49 credits
                    "requires_subscription": True,
                    "stackable": True,
                },
                display_order=11,
                is_active=True,
                is_featured=True,
            ),
            
            InfluencerSubscriptionPlan(
                plan_name="$69 Add-on",
                price_cents=6900,  # $69
                currency="USD",
                interval="addon",
                plan_type="addon",
                description="$69 add-on pack. Requires active subscription.",
                features={
                    "credits_granted": 6900,  # Pay $69, get $69 credits
                    "requires_subscription": True,
                    "stackable": True,
                },
                display_order=12,
                is_active=True,
                is_featured=False,
            ),
            
            InfluencerSubscriptionPlan(
                plan_name="$89 Add-on",
                price_cents=8900,  # $89
                currency="USD",
                interval="addon",
                plan_type="addon",
                description="$89 add-on pack. Requires active subscription.",
                features={
                    "credits_granted": 8900,  # Pay $89, get $89 credits
                    "requires_subscription": True,
                    "stackable": True,
                },
                display_order=13,
                is_active=True,
                is_featured=False,
            ),
        ]
        
        # Filter out plans that already exist by name
        plans_to_add = [p for p in plans if p.plan_name not in existing_names]
        
        if not plans_to_add:
            print("✅ All plans already exist. No new plans to add.")
            return
        
        print(f"➕ Adding {len(plans_to_add)} new plans...")
        
        for plan in plans_to_add:
            db.add(plan)
        
        await db.commit()
        
        print(f"✅ Successfully seeded {len(plans_to_add)} subscription plans:")
        
        recurring = [p for p in plans_to_add if p.interval == "monthly"]
        if recurring:
            print("\n📋 Recurring Plans:")
            for plan in recurring:
                featured = "⭐" if plan.is_featured else ""
                print(f"   {featured} {plan.plan_name}: ${plan.price_cents/100:.0f}/month")
        
        addons = [p for p in plans_to_add if p.interval == "addon"]
        if addons:
            print("\n🎁 Add-on Packs:")
            for plan in addons:
                featured = "⭐" if plan.is_featured else ""
                credits = plan.features.get("credits_granted", 0)
                print(f"   {featured} {plan.plan_name}: ${plan.price_cents/100:.0f} → ${credits/100:.0f} credits")
    
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
