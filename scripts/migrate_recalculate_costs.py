"""
Migrate historical API usage data to recalculate costs with fixed formula.

This script recalculates estimated_cost_micros for all existing api_usage_logs
entries using the corrected cost calculation formula.

Usage:
    python -m scripts.migrate_recalculate_costs [--dry-run] [--batch-size=1000]

Options:
    --dry-run       : Preview changes without updating database
    --batch-size=N  : Process N records at a time (default: 1000)
"""
import asyncio
import sys
import argparse
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, update, func
from app.db.session import SessionLocal
from app.db.models.api_usage import ApiUsageLog


# Pricing constants (copied from token_tracker.py)
_PRICING_INPUT = {
    "gpt-5.2": 2_500,
    "gpt-4.1": 2_000,
    "gpt-4o": 2_500,
    "gpt-4o-mini": 150,
    "text-embedding-3-small": 20,
    "grok-4-1-fast-reasoning": 3_000,
}

_PRICING_OUTPUT = {
    "gpt-5.2": 10_000,
    "gpt-4.1": 8_000,
    "gpt-4o": 10_000,
    "gpt-4o-mini": 600,
    "text-embedding-3-small": 0,
    "grok-4-1-fast-reasoning": 15_000,
}

_ELEVENLABS_CONVAI_COST_PER_SEC = 1_667
_ELEVENLABS_TTS_COST_PER_SEC = 3_000
_WHISPER_COST_PER_MINUTE = 6_000


def recalculate_cost(row: ApiUsageLog) -> int | None:
    """Recalculate cost using the FIXED formula."""

    # Handle ElevenLabs time-based pricing
    if row.provider == "elevenlabs" and row.duration_secs is not None:
        rate = (
            _ELEVENLABS_CONVAI_COST_PER_SEC
            if row.purpose == "call_conversation"
            else _ELEVENLABS_TTS_COST_PER_SEC
        )
        return int(row.duration_secs * rate)

    # Handle Whisper time-based pricing
    if row.model == "whisper-1" and row.duration_secs is not None:
        duration_mins = row.duration_secs / 60.0
        return int(duration_mins * _WHISPER_COST_PER_MINUTE)

    # Handle token-based pricing (FIXED VERSION)
    cost = 0
    has_pricing = False

    if row.input_tokens:
        if row.model in _PRICING_INPUT:
            cost += row.input_tokens * _PRICING_INPUT[row.model]
            has_pricing = True

    if row.output_tokens:
        if row.model in _PRICING_OUTPUT:
            cost += row.output_tokens * _PRICING_OUTPUT[row.model]
            has_pricing = True

    # Divide once at the end (FIXED!)
    return (cost // 1_000_000) if has_pricing else None


async def migrate_costs(dry_run: bool = False, batch_size: int = 1000):
    """Migrate all historical costs to use fixed calculation."""

    print("🔄 Starting cost recalculation migration...")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE UPDATE'}")
    print(f"Batch size: {batch_size}\n")

    async with SessionLocal() as db:
        # Count total records
        count_result = await db.execute(select(func.count(ApiUsageLog.id)))
        total_count = count_result.scalar()
        print(f"📊 Total records to process: {total_count:,}\n")

        if total_count == 0:
            print("✅ No records to migrate")
            return

        # Process in batches
        offset = 0
        updated_count = 0
        unchanged_count = 0
        error_count = 0

        total_old_cost = 0
        total_new_cost = 0

        while offset < total_count:
            # Fetch batch
            stmt = (
                select(ApiUsageLog)
                .order_by(ApiUsageLog.id)
                .offset(offset)
                .limit(batch_size)
            )
            result = await db.execute(stmt)
            rows = result.scalars().all()

            if not rows:
                break

            print(f"Processing batch {offset//batch_size + 1} "
                  f"(records {offset+1:,} to {offset+len(rows):,})...")

            batch_updates = 0
            for row in rows:
                try:
                    old_cost = row.estimated_cost_micros or 0
                    new_cost = recalculate_cost(row)

                    if new_cost != old_cost:
                        total_old_cost += old_cost
                        total_new_cost += (new_cost or 0)

                        if not dry_run:
                            row.estimated_cost_micros = new_cost

                        batch_updates += 1
                        updated_count += 1
                    else:
                        unchanged_count += 1

                except Exception as e:
                    print(f"  ⚠️  Error processing record {row.id}: {e}")
                    error_count += 1

            if not dry_run and batch_updates > 0:
                await db.commit()
                print(f"  ✅ Updated {batch_updates} records in batch")
            elif batch_updates > 0:
                print(f"  👀 Would update {batch_updates} records (dry run)")
            else:
                print(f"  ⏭️  No changes in batch")

            offset += len(rows)

        print("\n" + "="*60)
        print("📈 MIGRATION SUMMARY")
        print("="*60)
        print(f"Total records processed: {total_count:,}")
        print(f"Records updated:         {updated_count:,}")
        print(f"Records unchanged:       {unchanged_count:,}")
        print(f"Errors:                  {error_count:,}")
        print()
        print(f"Old total cost:          ${total_old_cost / 1_000_000:.6f}")
        print(f"New total cost:          ${total_new_cost / 1_000_000:.6f}")
        print(f"Difference:              ${(total_new_cost - total_old_cost) / 1_000_000:.6f}")
        print(f"Change factor:           {total_new_cost / total_old_cost if total_old_cost > 0 else 'N/A'}")
        print()

        if dry_run:
            print("🔍 DRY RUN - No changes were written to database")
            print("   Run without --dry-run to apply changes")
        else:
            print("✅ Migration completed successfully!")


def main():
    parser = argparse.ArgumentParser(
        description="Recalculate historical API usage costs with fixed formula"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without updating database"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Number of records to process per batch (default: 1000)"
    )

    args = parser.parse_args()

    # Run migration
    asyncio.run(migrate_costs(
        dry_run=args.dry_run,
        batch_size=args.batch_size
    ))


if __name__ == "__main__":
    main()
