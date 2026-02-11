import asyncio
import yaml
import sys
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import select

from app.core.config import settings

from app.db.models import SystemPrompt
from app.db.session import SessionLocal

SYSTEM_PROMPTS_FILE = Path(__file__).parent.parent / "data" / "system_prompts.yaml"


def _parse_args() -> dict:
    """Minimal arg parser — no external deps needed."""
    args = {"force": False, "dry_run": False}
    for a in sys.argv[1:]:
        if a in ("--force", "-f"):
            args["force"] = True
        elif a in ("--dry-run", "-n"):
            args["dry_run"] = True
        elif a in ("--help", "-h"):
            print(
                "Usage: python -m app.scripts.seed_system_prompts [OPTIONS]\n"
                "\n"
                "Options:\n"
                "  --force, -f    Overwrite ALL prompts regardless of version.\n"
                "                 Use after pulling new code or for fresh environments.\n"
                "  --dry-run, -n  Show what WOULD change without writing to DB.\n"
                "  --help, -h     Show this help message.\n"
            )
            sys.exit(0)
    return args


async def main():
    opts = _parse_args()
    force = opts["force"]
    dry_run = opts["dry_run"]

    if force:
        print("🔧 FORCE mode — overwriting all prompts regardless of version.")
    if dry_run:
        print("👀 DRY RUN — no changes will be written.\n")

    if not SYSTEM_PROMPTS_FILE.exists():
        print(f"File not found: {SYSTEM_PROMPTS_FILE}")
        return

    with open(SYSTEM_PROMPTS_FILE, "r") as f:
        prompts_data = yaml.safe_load(f)

    if not prompts_data:
        print("No prompts found in YAML file.")
        return

    created = 0
    updated = 0
    skipped = 0

    async with SessionLocal() as db:
        for prompt_entry in prompts_data:
            key = prompt_entry.get("key")
            if not key:
                print(f"Skipping entry without key: {prompt_entry}")
                continue

            yaml_version = prompt_entry.get("version", 1)
            existing = await db.scalar(select(SystemPrompt).where(SystemPrompt.key == key))

            if existing:
                db_version = existing.version or 0

                if force or yaml_version > db_version:
                    label = "FORCE" if force and yaml_version <= db_version else "↑"
                    print(f"  {label} Updating '{key}': v{db_version} → v{yaml_version}")
                    if not dry_run:
                        existing.prompt = prompt_entry.get("prompt")
                        existing.name = prompt_entry.get("name")
                        existing.description = prompt_entry.get("description")
                        existing.type = prompt_entry.get("type", "normal")
                        existing.version = yaml_version
                        existing.updated_at = datetime.now(timezone.utc)
                    updated += 1
                elif yaml_version == db_version:
                    print(f"  = Skipping '{key}': already at v{db_version}")
                    skipped += 1
                else:
                    print(f"  ⚠ Skipping '{key}': DB v{db_version} > YAML v{yaml_version} (edited via admin?)")
                    skipped += 1
            else:
                print(f"  + Creating '{key}': v{yaml_version}")
                if not dry_run:
                    new_prompt = SystemPrompt(
                        key=key,
                        name=prompt_entry.get("name"),
                        prompt=prompt_entry.get("prompt"),
                        description=prompt_entry.get("description"),
                        type=prompt_entry.get("type", "normal"),
                        version=yaml_version,
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                    )
                    db.add(new_prompt)
                created += 1

        if not dry_run:
            await db.commit()

    action = "Would have" if dry_run else "Done:"
    print(f"\n{action} {created} created, {updated} updated, {skipped} skipped.")


if __name__ == "__main__":
    asyncio.run(main())
