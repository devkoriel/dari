# Telegram Translator Bot — Design Spec

**Date:** 2026-03-17
**Status:** Approved

## Purpose

A Telegram bot that provides real-time, context-aware translation in a group chat between two users:
- **User A (koriel):** Writes in English and Korean → bot translates to Traditional Chinese (繁體中文)
- **User B (girlfriend):** Writes in Traditional Chinese → bot translates to Korean (한국어)

The bot uses Claude Haiku 4.5 as the translation engine, with the last 20 messages as conversation context for natural, coherent translations.

## Architecture

```
Telegram Group Chat
    │
    ▼
telegram-translator-bot (Python, long-polling)
    │
    ├── Receives text message
    ├── Looks up sender's Telegram user ID → determines target language
    │     • koriel's user ID → target: zh-TW (繁體中文)
    │     • girlfriend's user ID → target: ko (한국어)
    ├── Builds prompt: system instructions + last 20 messages as context
    ├── Calls Claude Haiku 4.5 via Anthropic SDK
    └── Replies to the original message with the translation
```

### Stack

- **Runtime:** Python 3.14 (asdf)
- **Package manager:** uv
- **Telegram:** `python-telegram-bot` (async, polling mode)
- **Translation:** `anthropic` SDK, model configurable via `CLAUDE_MODEL` env var (default: `claude-haiku-4-5-20251001`)
- **Config:** `python-dotenv` for `.env` loading
- **Logging:** `structlog` for structured logging
- **Persistence:** None — in-memory context buffer only

## Translation Rules

1. English or Korean message from koriel → translate to **繁體中文**
2. Traditional Chinese message from girlfriend → translate to **한국어**
3. Mixed-language messages → translate the entire message to the target language
4. Bot's own messages → ignored (prevents infinite loops)
5. Non-text messages (photos, stickers, voice, etc.) → ignored
6. Pure emoji / number-only messages → skipped (no translation needed)
7. Short messages ("ok", "ㅋㅋ", "哈哈") → translated (they carry cross-language meaning)

## Context Handling

- **Buffer:** In-memory `collections.deque(maxlen=20)` storing recent messages
- **Entry format:** `{sender: str, original: str, translation: str}`
- **System prompt:** Instructs Claude to act as a translator, output ONLY the translation with no labels, explanations, or decorations
- **Context benefits:** Resolves pronouns, maintains topic continuity, handles slang/idioms, disambiguates abbreviations

The buffer is a single global deque (single group chat). Resets on bot restart, which is acceptable for a personal bot.

## Configuration

### Environment Variables (`.env`)

```
TELEGRAM_BOT_TOKEN=<from BotFather>
ANTHROPIC_API_KEY=<your Anthropic key>
USER_MAP={"123456":"zh-TW","789012":"ko"}
```

- `USER_MAP` is a JSON dict mapping Telegram user ID (string) to target translation language code
- Users not in the map are ignored (bot won't translate messages from unknown users)

## Project Structure

```
telegram-translator-bot/
├── src/
│   ├── __init__.py
│   ├── __main__.py      # Entry point (uv run python -m src)
│   ├── bot.py           # Telegram bot setup, polling, message handler
│   ├── translator.py    # Claude API call, context buffer management
│   └── config.py        # Load .env, parse USER_MAP, validate config
├── tests/
│   ├── __init__.py
│   ├── test_bot.py         # Bot handler integration tests
│   ├── test_translator.py  # Context buffer, prompt construction
│   └── test_config.py      # USER_MAP parsing, validation
├── deploy/
│   └── com.koriel.telegram-translator-bot.plist  # launchd config
├── .env                 # Secrets (gitignored)
├── .env.example         # Template with placeholder values
├── .gitignore           # .env, __pycache__, etc.
├── pyproject.toml       # Project metadata + dependencies (uv)
└── README.md            # This file
```

## Deployment

**Target:** Mac mini (home server, SSH access, always-on)

### Process Management

- **launchd** plist at `~/Library/LaunchAgents/com.koriel.telegram-translator-bot.plist`
- Auto-start on login, restart on crash (`KeepAlive: true`)
- Logs to `~/Library/Logs/telegram-translator-bot.log`

### Setup Steps

1. Create bot via Telegram BotFather, obtain token
2. Add bot to the group chat
3. Obtain both users' Telegram user IDs (e.g., via `@userinfobot`)
4. Clone repo to Mac mini, copy `.env.example` → `.env`, fill in values
5. `uv sync` to install dependencies
6. `uv run python -m src` to verify it works
7. Install launchd plist for persistence

## Cost Estimate

- Claude Haiku 4.5: ~$0.01-0.03 per message with 20-message context
- Typical personal usage (50-100 messages/day): ~$1-3/month
- No other infrastructure costs (runs on existing Mac mini)

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Bot restarts | Context buffer resets, translations continue without history |
| Unknown user sends message | Ignored, no translation |
| Message is only emojis/numbers | Skipped |
| Claude API error | Log error, skip translation for that message |
| Telegram polling timeout | `python-telegram-bot` handles reconnection automatically |
| Very long message | Send to Claude as-is; context entries dropped oldest-first if needed (unlikely — Haiku has 200K context) |
| Spam burst | Simple asyncio.Semaphore(3) to cap concurrent API calls |

## Non-Goals

- Voice message transcription
- Message queuing / offline catch-up
- Multi-group support (single group chat only for now)
- Database / persistent conversation history
- Web UI or admin interface
