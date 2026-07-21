# AI Discord Companion Bot

This is a separate standalone Discord AI companion bot built with Python, discord.py, Groq, and optional GIF support.

## Features

- Mention-triggered conversations
- Reply-to-bot conversation continuity
- Temporary SQLite conversation memory
- Playful personality with emoji and meme-aware tone
- Optional GIF reactions via Klipy
- Safe, privacy-focused behavior

## Project structure

- bot.py - entry point
- config.py - environment configuration
- cogs/ai_chat.py - message handling and AI responses
- utils/personality.py - editable bot personality
- utils/conversation.py - temporary session helpers
- utils/database.py - SQLite memory storage
- utils/gif_api.py - optional GIF lookup

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

3. Run the bot:
   ```bash
   python bot.py
   ```

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
here