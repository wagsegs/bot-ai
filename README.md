# AI Discord Companion Bot — Bot-kun

Bot-kun is a Discord server member with its own personality — not an assistant.

## Features

- Single unified personality (friendly, funny, calm, slightly sarcastic)
- Conversation ownership — remembers who it's talking to per channel
- Natural conversation flow after initial @mention or reply
- Human-like reply delays (3–8s normal, 8–20s under load)
- Groq-powered responses (llama-3.3-70b-versatile)
- YouTube, meme, and GIF tools
- Local conversation memory with summarization
- Proactive rate limiting and request queue
- Online/offline availability cycles
- Natural participation every ~50 messages
- Moderation: spam filter, blacklist, explicit request handling

## Project structure

```
bot.py
├── cogs/ai_chat.py          — thin orchestrator
├── router/                  — message routing, intents, conversation ownership
├── ai/                      — Groq provider, prompts, response parsing
├── tools/                   — YouTube, GIFs, memes, clip
├── memory/                  — conversation, user, server cache
├── moderation/              — blacklist, spam, NSFW
├── monitoring/              — dashboard, rate limit, queue, logging
└── utils/                   — database, availability, budget (legacy shims)
```

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Fill in `.env`:
   - `DISCORD_TOKEN`
   - `GROQ_API_KEY`
   - `KLIPY_KEY` (optional, for GIFs)
   - `YOUTUBE_API_KEY` (optional, for video search)
   - `BOT_NAME` (optional, default: Nova)

3. Run:
   ```bash
   python bot.py
   ```

## Commands

### Public
- `~botkun` — one-line online/offline status

### Admin
- `~bot` — toggle bot on/off
- `~dashboard` — full engineer dashboard
- `~reload` — reload personality, clear caches, restart conversations
- `~blacklist [@user]` — manage blacklist
- `~clip` — generate Episode summary from last 30 messages, post to #bombo-times

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| DISCORD_TOKEN | — | Required |
| GROQ_API_KEY | — | Required |
| BOT_NAME | Nova | Bot display name |
| KLIPY_KEY | — | GIF API key |
| YOUTUBE_API_KEY | — | YouTube search |
| BOT_ONLINE_MIN/MAX | 25/40 | Online window (minutes) |
| BOT_OFFLINE_MIN/MAX | 15/60 | Offline window (minutes) |
| BUDGET_CAP | 100 | API requests per hour |
| RESPONSE_DELAY_MIN/MAX | 3/8 | Normal reply delay (seconds) |
| RESPONSE_DELAY_HEAVY_MIN/MAX | 8/20 | Heavy load delay (seconds) |

## Railway deployment

Set `DISCORD_TOKEN`, `GROQ_API_KEY`, and optional keys. Start with `python bot.py`.
