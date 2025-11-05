# MCP Server - Developer Guide

## What is MCP?

MCP (Model Context Protocol) is an administrative API that provides tools to manage application data (influencers, users, chats) via HTTP endpoints.

**Note:** This is an administrative tool, not used by the frontend. The frontend continues using normal endpoints (`/chat/*`, `/influencer/*`, etc.).

---

## Server Configuration

- **Base URL:** `https://localhost:8080`
- **Protocol:** HTTPS (with self-signed certificate)
- **Use `-k` flag in curl** to ignore certificate warnings

---

## Available Tools

### 1. List All Tools

```bash
curl -k https://localhost:8080/mcp/tools | jq
```

### 2. Chat Tools

- `get_chat_history` - Get message history for a chat
- `get_or_create_chat` - Get or create a chat between user and influencer

### 3. User Tools

- `check_user_credits` - Check user's credit balance
- `get_user_info` - Get user information

### 4. Influencer Tools

- `list_influencers` - List all influencers
- `get_influencer_persona` - Get influencer details including prompt
- `update_influencer` - Update a specific influencer
- `update_all_influencers` - Bulk update all influencers

---

## Usage Examples

### Update a Specific Influencer

```bash
curl -k -X POST https://localhost:8080/mcp/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "name": "update_influencer",
    "arguments": {
      "influencer_id": "anna",
      "display_name": "Anna Updated",
      "prompt_template": "You are Anna, a sweet and playful AI assistant...",
      "voice_id": "new_voice_id_123",
      "voice_prompt": "Speak in a warm, friendly tone...",
      "daily_scripts": ["Morning greeting", "Evening goodbye"]
    }
  }' | jq
```

**Available fields:**

- `influencer_id` (required) - The influencer ID to update
- `display_name` (optional) - New display name
- `prompt_template` (optional) - New AI personality prompt
- `voice_id` (optional) - New voice ID for TTS
- `voice_prompt` (optional) - New voice prompt
- `daily_scripts` (optional) - Array of daily script strings
- `influencer_agent_id_third_part` (optional) - Third-party agent ID

---

### Bulk Update All Influencers

```bash
curl -k -X POST https://localhost:8080/mcp/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "name": "update_all_influencers",
    "arguments": {
      "voice_id": "new_voice_id_for_all"
    }
  }' | jq
```

**Response:**

```json
{
  "content": {
    "updated_count": 3,
    "total_influencers": 3,
    "updated_ids": ["anna", "bella", "loli"]
  },
  "isError": false
}
```

---

### List All Influencers

```bash
curl -k -X POST https://localhost:8080/mcp/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "name": "list_influencers",
    "arguments": {"limit": 10}
  }' | jq
```

---

### Get Influencer Details

```bash
curl -k -X POST https://localhost:8080/mcp/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "name": "get_influencer_persona",
    "arguments": {
      "influencer_id": "anna"
    }
  }' | jq
```

**Response includes:**

- `id`, `display_name`, `voice_id`
- `prompt_template` - The AI personality prompt
- `voice_prompt` - Voice configuration
- `created_at`

---

### Check User Credits

```bash
curl -k -X POST https://localhost:8080/mcp/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "name": "check_user_credits",
    "arguments": {
      "user_id": 1,
      "feature": "text"
    }
  }' | jq
```

**Available features:** `text`, `voice`, `live_chat`

---

### Get Chat History

```bash
curl -k -X POST https://localhost:8080/mcp/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "name": "get_chat_history",
    "arguments": {
      "chat_id": "abc123",
      "limit": 20,
      "page": 1
    }
  }' | jq
```

---

## Python Example

```python
import httpx
import asyncio

async def update_influencer_prompt():
    async with httpx.AsyncClient(
        base_url="https://localhost:8080",
        verify=False  # Ignore self-signed certificate
    ) as client:
        response = await client.post(
            "/mcp/tools/call",
            json={
                "name": "update_influencer",
                "arguments": {
                    "influencer_id": "anna",
                    "prompt_template": "You are Anna, a sweet AI assistant..."
                }
            }
        )
        print(response.json())

asyncio.run(update_influencer_prompt())
```

---

## Important Notes

1. **All fields are optional** except those marked as `required` in the tool schema
2. **Updates are immediate** - changes are committed to the database right away
3. **Changes affect next conversations** - existing conversations continue with old data
4. **No authentication required currently** - may be added in the future
5. **Frontend doesn't use MCP** - it uses normal endpoints (`/chat/*`, `/influencer/*`)

---

## How It Works

1. **MCP updates database** → Changes stored in `influencers` table
2. **Backend reads from database** → `handle_turn()` fetches `influencer.prompt_template`
3. **AI uses updated prompt** → Next messages use the new personality
4. **Frontend sees changes** → Automatically, without any code changes

---

## Common Use Cases

### Update AI Personality

```bash
# Make Anna more affectionate
curl -k -X POST https://localhost:8080/mcp/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "name": "update_influencer",
    "arguments": {
      "influencer_id": "anna",
      "prompt_template": "You are Anna. Be EXTREMELY affectionate and sweet..."
    }
  }'
```

### Change Voice for All Influencers

```bash
curl -k -X POST https://localhost:8080/mcp/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "name": "update_all_influencers",
    "arguments": {
      "voice_id": "new_elevenlabs_voice_id"
    }
  }'
```

### Test Different Prompts

```bash
# Update, test conversation, update again - no code changes needed
curl -k -X POST https://localhost:8080/mcp/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "name": "update_influencer",
    "arguments": {
      "influencer_id": "anna",
      "prompt_template": "You are Anna. Be playful and teasing..."
    }
  }'
```

---

## Troubleshooting

### Certificate Error

```bash
# Always use -k flag with curl
curl -k https://localhost:8080/mcp/tools
```

### Tool Not Found

```bash
# List available tools first
curl -k https://localhost:8080/mcp/tools | jq '.tools[].name'
```

### Empty Response

- Check if server is running on port 8080
- Verify you're using HTTPS (not HTTP)
- Check server logs for errors

---

## API Reference

### Endpoint: `POST /mcp/tools/call`

**Request:**

```json
{
  "name": "tool_name",
  "arguments": {
    "field1": "value1",
    "field2": "value2"
  }
}
```

**Response:**

```json
{
  "content": {
    // Tool-specific response data
  },
  "isError": false
}
```

**Error Response:**

```json
{
  "content": {
    "error": "Error message"
  },
  "isError": true
}
```

---

## Quick Reference

| Task              | Command                                                                                                                                                                                          |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| List tools        | `curl -k https://localhost:8080/mcp/tools \| jq`                                                                                                                                                 |
| List influencers  | `curl -k -X POST https://localhost:8080/mcp/tools/call -H "Content-Type: application/json" -d '{"name":"list_influencers"}' \| jq`                                                               |
| Update influencer | `curl -k -X POST https://localhost:8080/mcp/tools/call -H "Content-Type: application/json" -d '{"name":"update_influencer","arguments":{"influencer_id":"anna","prompt_template":"..."}}' \| jq` |
| Bulk update       | `curl -k -X POST https://localhost:8080/mcp/tools/call -H "Content-Type: application/json" -d '{"name":"update_all_influencers","arguments":{"voice_id":"..."}}' \| jq`                          |

---

For more details, check the tool schemas:

```bash
curl -k https://localhost:8080/mcp/tools | jq '.tools[] | {name, description, inputSchema}'
```
