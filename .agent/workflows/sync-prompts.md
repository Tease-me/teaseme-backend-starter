---
description: How to edit, version, and sync system prompts across dev environments
---

# System Prompt Sync Workflow

## ⚡ Quick Reference

```bash
# Preview what would change (safe, changes nothing)
// turbo
docker exec teaseme-backend python -m app.scripts.seed_system_prompts --dry-run

# Normal sync — only applies YAML changes with bumped versions
docker exec teaseme-backend python -m app.scripts.seed_system_prompts

# Force sync — overwrites ALL prompts from YAML (use after git pull or fresh env)
docker exec teaseme-backend python -m app.scripts.seed_system_prompts --force
```

---

## How Versioning Works

Each prompt in `app/data/system_prompts.yaml` has a `version` field:

```yaml
- key: BASE_SYSTEM
  version: 2          # ← this controls sync behavior
  prompt: "..."
```

The sync script compares YAML version vs DB version:

| YAML | DB | Result |
|------|----|--------|
| v2   | v1 | ✅ Update — YAML is newer |
| v1   | v1 | ⏭️ Skip — already synced |
| v1   | v2 | ⚠️ Skip — DB was edited via admin API |
| any  | any | 🔧 `--force` overrides all checks |

---

## Developer Workflows

### 1. Editing a prompt (the normal flow)

1. Open `app/data/system_prompts.yaml`
2. Edit the prompt text
3. **Bump the `version` number** (e.g., `1` → `2`)
4. Rebuild + sync:
   ```bash
   docker compose up -d --build
   docker exec teaseme-backend python -m app.scripts.seed_system_prompts
   ```
5. Commit the YAML change to git

> **Rule: If you touch a prompt, bump its version. No exceptions.**

### 2. Pulling new code from another dev

After `git pull`, the YAML may have new versions. Run:

```bash
docker compose up -d --build
docker exec teaseme-backend alembic upgrade head
docker exec teaseme-backend python -m app.scripts.seed_system_prompts --force
```

Use `--force` here because your local DB may have stale versions that don't match what's in the pulled YAML. Force ensures your DB matches the repo exactly.

### 3. Fresh environment setup

```bash
docker compose up -d --build
docker exec teaseme-backend alembic upgrade head
docker exec teaseme-backend python -m app.scripts.seed_system_prompts --force
docker exec teaseme-backend python -m app.scripts.seed_influencers
```

### 4. Quick-testing a prompt via admin API

If you edit a prompt via the admin API (`POST /admin/system-prompts/{key}`), the DB version auto-increments. This protects your admin edits from being overwritten by normal syncs.

**To make it permanent:** Copy your admin edit back into the YAML and set the version higher than whatever the DB has.

### 5. Two devs editing different prompts

No conflict — each prompt has its own independent version number. Git merges cleanly since they're on different YAML lines.

### 6. Two devs editing the SAME prompt

Standard git merge conflict. Resolve in the YAML, pick the highest version number (or increment past both), then sync with `--force`.

---

## Flags

| Flag | Short | Effect |
|------|-------|--------|
| `--force` | `-f` | Overwrite all prompts from YAML regardless of version |
| `--dry-run` | `-n` | Show what would change without writing to DB |
| `--help` | `-h` | Show usage help |
