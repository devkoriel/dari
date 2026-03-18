# 다리 (Dari)

> A bridge between languages — real-time Telegram translation bot powered by Claude Haiku.

**다리** means "bridge" in Korean. Dari sits in your Telegram group chat and seamlessly translates every message between participants, preserving context, tone, and nuance.

## Features

- **Context-aware translation** — maintains a rolling buffer of the last 20 messages for natural, coherent translations
- **Multi-format support** — text, photo captions, voice messages (via Groq Whisper), video notes
- **Phrase table** — instant lookup for common phrases without API calls
- **Learn mode** — `/learn on` adds pronunciation guides to translations
- **Smart skip** — detects same-language messages, emoji-only, and numbers to avoid unnecessary translations
- **Long message support** — handles messages up to 10,000 characters with auto-chunking for Telegram's 4096 char limit
- **Flag prefixes** — 🇰🇷 🇹🇼 🇺🇸 flags indicate source language at a glance
- **Webhook mode** — Cloudflare Tunnel for reliable 24/7 operation
- **Prompt caching** — reduces API costs with Anthropic's ephemeral cache

## Commands

| Command | Description |
|---------|-------------|
| `/learn on\|off` | Toggle pronunciation in translations |
| `/say <phrase>` | Ask how to say something in your target language |
| `/teach <word>` | Get cultural context and usage for a word |
| `/lang <code>` | Override your target language |
| `/dday [set DATE NAME]` | Track important dates |
| `/stats` | Bot statistics (admin only) |

## Quick Start

```bash
# Clone and install
git clone https://github.com/devkoriel/dari.git
cd dari
uv sync

# Configure
cp .env.example .env
# Edit .env with your tokens

# Run
uv run python -m src
```

### Environment Variables

```
TELEGRAM_BOT_TOKEN=<from BotFather>
ANTHROPIC_API_KEY=<your Anthropic key>
ADMIN_USER_ID=<your Telegram user ID>
USER_MAP={"123456":"zh-TW","789012":"ko"}
CLAUDE_MODEL=claude-haiku-4-5-20251001
GROQ_API_KEY=<for voice transcription>
WEBHOOK_URL=https://your-domain.com
WEBHOOK_PORT=8443
```

## Project Structure

```
dari/
├── src/
│   ├── __main__.py      # Entry point
│   ├── bot.py           # Telegram handlers, webhook setup
│   ├── translator.py    # Claude API, context buffer, phrase table
│   ├── transcriber.py   # Groq Whisper voice/video transcription
│   ├── storage.py       # JSON file persistence
│   ├── config.py        # Environment config
│   └── quotes.py        # Daily quote feature
├── tests/
│   ├── test_bot.py
│   ├── test_translator.py
│   ├── test_config.py
│   └── test_storage.py
├── deploy/
│   └── com.koriel.dari.plist
├── pyproject.toml
└── README.md
```

## Deployment (macOS)

Dari runs as a launchd service with Cloudflare Tunnel for webhook delivery.

```bash
# Install launchd service
cp deploy/com.koriel.dari.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.koriel.dari.plist

# Check status
launchctl list | grep dari

# View logs
tail -f ~/Library/Logs/dari.log
```

## Testing

```bash
uv run python -m pytest tests/ -v
```

93 tests covering translation, context buffering, language detection, response cleaning, bot handlers, storage, and configuration.

## Architecture

```
Telegram ──webhook──▶ Cloudflare Tunnel ──▶ Dari (localhost:8443)
                                                │
                                    ┌───────────┼───────────┐
                                    ▼           ▼           ▼
                              Claude Haiku  Groq Whisper  JsonStore
                              (translate)   (transcribe)  (persist)
```

## Cost

- Claude Haiku 4.5 with prompt caching: ~$1–3/month for typical couple usage
- Groq Whisper: free tier
- Cloudflare Tunnel: free

## License

MIT
