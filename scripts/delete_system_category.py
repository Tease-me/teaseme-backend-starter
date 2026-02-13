"""
Delete all API usage records with category='system'.

This removes old records from before we split 'system' into granular categories:
- embedding
- moderation
- transcription
- analysis
- extraction
- assistant

Usage:
    python -m scripts.delete_system_category [--dry-run]

Options:
    --dry-run : Preview what will be deleted without actually deleting
"""
import asyncio
import sys
import argparse
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, delete, func
from app.db.session import SessionLocal
from app.db.models.api_usage import ApiUsageLog


async def delete_system_records(dry_run: bool = False):
    """Delete all records with category='system'."""

    print("🗑️  Deleting old 'system' category records...")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE DELETE'}\n")

    async with SessionLocal() as db:
        # Count records to be deleted
        count_stmt = select(func.count(ApiUsageLog.id)).where(
            ApiUsageLog.category == "system"
        )
        count_result = await db.execute(count_stmt)
        total_count = count_result.scalar()

        if total_count == 0:
            print("✅ No 'system' category records found")
            return

        print(f"📊 Found {total_count:,} records with category='system'\n")

        # Get breakdown by purpose
        purpose_stmt = select(
            ApiUsageLog.purpose,
            func.count(ApiUsageLog.id).label('count'),
            func.sum(ApiUsageLog.estimated_cost_micros).label('total_cost')
        ).where(
            ApiUsageLog.category == "system"
        ).group_by(ApiUsageLog.purpose)

        purpose_result = await db.execute(purpose_stmt)
        purpose_rows = purpose_result.all()

        print("Breakdown by purpose:")
        print("-" * 60)
        for row in purpose_rows:
            cost_usd = (row.total_cost or 0) / 1_000_000
            print(f"  {row.purpose:30s} {row.count:>6,} records  ${cost_usd:.6f}")
        print("-" * 60)
        print()

        if dry_run:
            print("🔍 DRY RUN - Would delete these records")
            print("   Run without --dry-run to actually delete")
        else:
            print("⚠️  Deleting records...")

            # Delete all system category records
            delete_stmt = delete(ApiUsageLog).where(
                ApiUsageLog.category == "system"
            )
            await db.execute(delete_stmt)
            await db.commit()

            print(f"✅ Deleted {total_count:,} records")
            print()
            print("The 'system' category will no longer appear in analytics.")


def main():
    parser = argparse.ArgumentParser(
        description="Delete old 'system' category API usage records"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what will be deleted without actually deleting"
    )

    args = parser.parse_args()

    # Run deletion
    asyncio.run(delete_system_records(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
