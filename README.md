# AI Discord Companion Bot

This is a separate standalone Discord AI companion bot built with Python, discord.py, Groq, and optional GIF support.

## Features

- Mention-triggered conversations
- Reply-to-bot conversation continuity
- Temporary SQLite conversation memory
- Playful personality with emoji and meme-aware tone
- Optional GIF reactions via Klipy
- Safe, privacy-focused behavior
- Automatic online/offline cycles for natural presence
- Graceful API usage throttling to prevent rate limits
- Multiple personality modes (admin-controlled)

## Project structure

- bot.py - entry point
- config.py - environment configuration
- cogs/ai_chat.py - message handling and AI responses
- utils/personality.py - editable bot personality
- utils/conversation.py - temporary session helpers
- utils/database.py - SQLite memory storage
- utils/gif_api.py - optional GIF lookup
- utils/availability.py - online/offline cycle management
- utils/response_budget.py - API usage throttling
- utils/natural_participation.py - spontaneous conversation joining

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Fill in the environment values in .env:
   - DISCORD_TOKEN
   - GROQ_API_KEY
   - KLIPY_KEY (optional)
   - BOT_NAME (optional)
   - BOT_ONLINE_MIN (optional, default: 25)
   - BOT_ONLINE_MAX (optional, default: 40)
   - BOT_OFFLINE_MIN (optional, default: 15)
   - BOT_OFFLINE_MAX (optional, default: 60)
   - BUDGET_CAP (optional, default: 100)
   - BUDGET_THRESHOLD_NORMAL (optional, default: 50)
   - BUDGET_THRESHOLD_REDUCED (optional, default: 80)
   - BUDGET_THRESHOLD_CRITICAL (optional, default: 95)

3. Run the bot:
   ```bash
   python bot.py
   ```

## Commands

- `~aihelp` - Show help menu
- `~mode` - Show current personality
- `~mode <personality>` - Change personality (admin only)
- `~status` - Show bot status including availability and budget
- `~availability` - Show availability window status (admin only)
- `~forceonline [minutes]` - Force bot online (admin only)
- `~forceoffline [minutes]` - Force bot offline (admin only)

## Railway deployment

Set these environment variables in Railway:

- DISCORD_TOKEN
- GROQ_API_KEY
- KLIPY_KEY
- BOT_NAME

Use the startup command:

```bash
python bot.py
```