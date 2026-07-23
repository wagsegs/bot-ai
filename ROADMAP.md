# Bot-kun Rewrite Roadmap

## Philosophy

Bot-kun is **not** ChatGPT.

Bot-kun is a long-time server member with its own personality. It isn't always available, doesn't answer everything, isn't trying to solve every problem, and joins conversations naturally. It should feel like someone who's been hanging around the server for years.

This means:

* No personality modes.
* No mood modes.
* No `.ai`.
* No assistant-like behavior.
* No "How can I help you today?"
* No unnecessary walls of text.
* No pretending it did something it didn't.

---

# Phase 1 — Core Conversation (Highest Priority)

This phase determines how the bot behaves in normal day-to-day conversations.

## One Personality

Remove:

* Personality modes
* Mood system
* Personality switching

There should only be one Bot-kun.

**Personality:**

* Friendly
* Funny
* Calm
* Slightly sarcastic
* Emotionally intelligent
* Can take jokes
* Doesn't overreact
* Feels like someone in their mid-20s
* Uses internet slang naturally
* Doesn't constantly say "bro"
* Doesn't constantly say "uwu"
* Doesn't constantly spam emojis

**Emoji usage should slowly adapt to the person it's talking to.**

If someone uses:

```
😭😭💀
```

Bot-kun can mirror that.

If someone never uses emojis:

Bot-kun shouldn't either.

---

## Natural Conversation

Conversation starts with:

```
@Bot-kun
```

or

Replying to Bot-kun.

After that...

Bot-kun remembers who it's talking to.

**Example:**

```
User:
hey bot-kun

Bot:
yo

User:
how've you been

Bot:
alive somehow
```

No mention needed anymore.

---

## Conversation Ownership

Bot-kun should remember:

```
Current conversation
    ↓
Current user
    ↓
Current channel
```

If another person suddenly interrupts:

Bot-kun continues replying to the original person unless the interruption is clearly directed at Bot-kun.

Exactly like humans do.

---

## Reply Speed

Don't answer instantly.

**Average:** 3–8 seconds

**Heavy load:** 8–20 seconds

Feels much more human.

---

# Phase 2 — Reliability

Now make sure the bot never breaks.

## JSON Leaks

Should never happen.

Even if Groq completely breaks.

---

## Tool Execution

Bot-kun never lies.

If it says:

```
I searched YouTube
```

it must have searched YouTube.

If it says:

```
couldn't find anything
```

the API returned nothing.

Never hallucinate actions.

---

## Better Parser

Parser first.

Regex fallback second.

Generic fallback third.

Never expose raw JSON.

---

# Phase 3 — API Management

This is probably the most important engineering phase.

## Rate Limiting

Don't wait until Groq rate limits.

Instead monitor:

```
Requests per 10 seconds
```

**Example:**

```
Limit: 5 / 10s
Target: 4 / 10s
```

Always stay below.

---

## Queue

Instead of rejecting requests:

```
User A
    ↓
Queue
    ↓
Groq
    ↓
Reply
```

During spam:

```
Queue grows
    ↓
Bot replies slower
    ↓
Nobody notices
```

---

## Overflow

If queue gets huge:

Simply ignore new requests.

Not every mention deserves a reply.

---

## Online/Offline

Keep.

It fits the character.

---

# Phase 4 — Tools

Tools should feel natural.

## Trailer

```
pull up interstellar trailer
    ↓
YouTube
```

---

## Meme

```
bot-kun send a meme
    ↓
Meme API
```

---

## GIF

```
that's depressing
```

Bot-kun may naturally respond with a GIF.

Not every time.

---

## Tool Manager

Every tool should live in one place.

Instead of:

```
video.py
gif.py
meme.py
```

being called randomly.

---

# Phase 5 — Memory

Current memory is mostly good.

Improve it.

## Conversation Memory

Don't send every message to Groq.

Store everything locally.

Only when Bot-kun actually needs context:

```
Load last ~60 messages
    ↓
Summarize
    ↓
Send summary
    ↓
Reply
```

Much cheaper.

---

## User Memory

Remember:

* Favorite emojis
* Nickname
* Speech style

Nothing creepy.

---

## Server Memory

On startup cache:

* Members
* Roles
* Channels

So Bot-kun understands:

```
who's who
```

without repeatedly querying Discord.

---

# Phase 6 — Natural Participation

This is where Bot-kun becomes alive.

Every ~50 messages:

Check:

```
Has Bot-kun spoken recently?
    ↓
No
    ↓
Read recent conversation
    ↓
Summarize
    ↓
Reply naturally
```

Not random.

Relevant.

Sometimes don't reply.

---

# Phase 7 — Moderation

Bot-kun shouldn't encourage bad behavior.

## Explicit Requests

First time:

Funny rejection.

Second time:

More sarcastic.

Third time:

Ignore.

---

## Spam

After 3 spam attempts:

Ignore user for 5 minutes.

---

## Blacklist

```
~blacklist @user
```

No interaction.

---

# Phase 8 — Commands

## Public

```
~botkun
```

**Example:**

```
Bot-kun is online and lurking 👀
```

or

```
Bot-kun is taking a break right now.
```

One line.

---

## Admin

```
~bot
```

Toggle On / Off

---

```
~dashboard
```

Shows:

* Uptime
* Provider
* Queue
* Requests/min
* Budget
* Online/offline
* API latency
* Response time
* Conversations
* Cache size
* Memory usage
* Current rate
* Last error
* Provider status

Basically an engineer dashboard.

---

```
~reload
```

Reload personality.

Clear caches.

Restart conversations.

---

```
~blacklist
```

Manage blacklist.

---

```
~clip
```

Read last 30 messages.

Generate:

```
Episode #24
```

Funny summary.

Mention everyone correctly.

Attach GIF or Meme.

Post to:

```
#bombo-times
```

Reply:

```
Done.

https://discord...
```

---

# Phase 9 — Architecture (Before Any New Features)

This is the phase I think is missing today.

Split the project into clear modules:

```text
bot.py
│
├── router/
│   ├── message_router.py
│   ├── intent_detector.py
│   └── conversation_manager.py
│
├── ai/
│   ├── provider.py
│   ├── groq_provider.py
│   ├── prompt_builder.py
│   └── action_planner.py
│
├── tools/
│   ├── youtube.py
│   ├── gifs.py
│   ├── memes.py
│   └── clip.py
│
├── memory/
│   ├── conversation_memory.py
│   ├── user_memory.py
│   └── server_cache.py
│
├── moderation/
│   ├── blacklist.py
│   ├── spam.py
│   └── nsfw.py
│
└── monitoring/
    ├── dashboard.py
    ├── rate_limit.py
    ├── queue.py
    └── logging.py
```

---

# Implementation Priority

**Phase 9 (Architecture) should be completed first.**

Without a clean modular architecture, every other feature becomes harder to implement and maintain.

**Recommended order:**

1. **Phase 9** - Create modular architecture
2. **Phase 1** - Core conversation (single personality, conversation ownership, reply speed)
3. **Phase 2** - Reliability (JSON leak prevention, tool validation)
4. **Phase 3** - API management (rate limiting, queue, overflow)
5. **Phase 4** - Tools (unified tool manager)
6. **Phase 5** - Memory improvements
7. **Phase 6** - Natural participation
8. **Phase 7** - Moderation
9. **Phase 8** - Commands

---

# Current State Assessment

**What exists:**

* Basic Discord bot with mention/reply triggers
* Groq integration with JSON response parsing
* GIF and video search tools
* SQLite conversation memory
* Online/offline availability system
* Response budget system
* Multiple personality modes (to be removed)
* Middleware with queueing and rate limiting

**What needs to change:**

* Remove personality modes → single unified personality
* Tighten tool execution validation → prevent hallucinations
* Improve JSON parsing → parser first, regex second, generic third
* Add conversation ownership tracking
* Implement human-like reply delays
* Add user memory (emojis, nickname, speech style)
* Add server cache (members, roles, channels)
* Implement conversation summarization
* Improve natural participation with context awareness
* Add moderation (spam, blacklist, explicit requests)
* Refactor into modular architecture

---

# Success Criteria

**Bot-kun is successful when:**

1. It feels like another server member, not an AI assistant
2. It maintains conversation context naturally
3. It never hallucinates actions or leaks JSON
4. It handles high load gracefully with queueing
5. It has a clean, modular architecture that's easy to extend
6. It has proper logging and request tracing for debugging
7. It respects rate limits proactively
8. It remembers users without being creepy
9. It participates naturally without being spammy
10. It has clear, simple commands for both users and admins
