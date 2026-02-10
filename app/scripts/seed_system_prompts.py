import asyncio
import yaml
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import select

from app.core.config import settings

from app.db.models import SystemPrompt
from app.db.session import SessionLocal

SYSTEM_PROMPTS_FILE = Path(__file__).parent.parent / "data" / "system_prompts.yaml"

async def main():
    if not SYSTEM_PROMPTS_FILE.exists():
        print(f"File not found: {SYSTEM_PROMPTS_FILE}")
        return

    with open(SYSTEM_PROMPTS_FILE, "r") as f:
        prompts_data = yaml.safe_load(f)

    if not prompts_data:
        print("No prompts found in YAML file.")
        return

    async with SessionLocal() as db:
        for prompt_entry in prompts_data:
            key = prompt_entry.get("key")
            if not key:
                print(f"Skipping entry without key: {prompt_entry}")
                continue

            existing = await db.scalar(select(SystemPrompt).where(SystemPrompt.key == key))
            
            if existing:
                print(f"Updating prompt: {key}")
                existing.prompt = prompt_entry.get("prompt")
                existing.name = prompt_entry.get("name")
                existing.description = prompt_entry.get("description")
                existing.type = prompt_entry.get("type", "normal")
                existing.updated_at = datetime.now(timezone.utc)
            else:
                print(f"Creating new prompt: {key}")
                new_prompt = SystemPrompt(
                    key=key,
                    name=prompt_entry.get("name"),
                    prompt=prompt_entry.get("prompt"),
                    description=prompt_entry.get("description"),
                    type=prompt_entry.get("type", "normal"),
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                db.add(new_prompt)
        
        await db.commit()
    print("System prompts synced successfully.")

if __name__ == "__main__":
    asyncio.run(main())
