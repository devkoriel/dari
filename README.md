<p align="center">
  <img src="assets/banner.png" alt="Dari Bot — Welcome" width="600" />
</p>

<h1 align="center">다리 (Dari)</h1>

<p align="center">
  <em>A bridge between languages — real-time Telegram translation bot powered by Claude Haiku</em>
</p>

<p align="center">
  <a href="https://github.com/devkoriel/dari/actions/workflows/deploy.yml"><img src="https://github.com/devkoriel/dari/actions/workflows/deploy.yml/badge.svg" alt="CI/CD" /></a>
  <img src="https://img.shields.io/badge/python-3.14-blue" alt="Python 3.14" />
  <img src="https://img.shields.io/badge/claude-haiku%204.5-blueviolet" alt="Claude Haiku 4.5" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License" />
</p>

---

**다리** means "bridge" in Korean. Dari sits in your Telegram group chat and seamlessly translates every message between participants — preserving context, tone, and nuance across Korean, Chinese, and English.

## Features

| Feature | Description |
|---------|-------------|
| **Context-aware** | Rolling buffer of last 20 messages for natural, coherent translations |
| **Multi-format** | Text, photo captions, voice messages, video notes |
| **Phrase table** | Instant lookup for common phrases — zero API latency |
| **Learn mode** | `/learn on` adds pronunciation guides to every translation |
| **Smart skip** | Detects same-language, emoji-only, and number-only messages |
| **Long messages** | Up to 10,000 characters with auto-chunking for Telegram's limit |
| **Flag prefixes** | 🇰🇷 🇹🇼 🇺🇸 flags show source language at a glance |
| **Webhook mode** | Cloudflare Tunnel for rock-solid 24/7 uptime |
| **Prompt caching** | Reduced API costs via Anthropic's ephemeral cache |
| **Voice/Video** | Groq Whisper transcription → translation pipeline |

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
git clone https://github.com/devkoriel/dari.git
cd dari
uv sync
cp .env.example .env  # Fill in your tokens
uv run python -m src
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | From [@BotFather](https://t.me/BotFather) |
| `ANTHROPIC_API_KEY` | Yes | [Anthropic Console](https://console.anthropic.com/) |
| `ADMIN_USER_ID` | Yes | Your Telegram user ID |
| `USER_MAP` | Yes | JSON: `{"user_id": "target_lang"}` |
| `CLAUDE_MODEL` | No | Default: `claude-haiku-4-5-20251001` |
| `GROQ_API_KEY` | No | For voice/video transcription |
| `WEBHOOK_URL` | No | Webhook domain (e.g. `https://bot.example.com`) |
| `WEBHOOK_PORT` | No | Default: `8443` |

## Architecture

```
Telegram ──webhook──▶ Cloudflare Tunnel ──▶ Dari (localhost:8443)
                                                │
                                    ┌───────────┼───────────┐
                                    ▼           ▼           ▼
                              Claude Haiku  Groq Whisper  JsonStore
                              (translate)   (transcribe)  (persist)
```

### Project Structure

```
dari/
├── src/
│   ├── __main__.py       # Entry point
│   ├── bot.py            # Telegram handlers & webhook
│   ├── translator.py     # Claude API, context buffer, phrase table
│   ├── transcriber.py    # Groq Whisper voice/video transcription
│   ├── storage.py        # JSON persistence (atomic writes)
│   ├── config.py         # Environment config
│   └── quotes.py         # Daily couple quotes
├── tests/                # 93 tests
├── deploy/
│   └── com.koriel.dari.plist
├── assets/
│   ├── banner.png
│   └── avatar.png
├── .github/workflows/
│   └── deploy.yml        # CI/CD: lint → test → deploy
├── pyproject.toml
└── renovate.json
```

## CI/CD

Fully automated pipeline on every push to `main`:

```
Lint (ruff check + format) → Test (93 tests) → Deploy (Mac mini)
```

Runs on a self-hosted GitHub Actions runner on the deployment target itself — no external access needed.

## Deployment (macOS)

Dari runs as a launchd service with Cloudflare Tunnel for webhook delivery.

```bash
# Install service
cp deploy/com.koriel.dari.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.koriel.dari.plist

# Check status
launchctl list | grep dari
tail -f ~/Library/Logs/dari.log
```

## Testing

```bash
uv run python -m pytest tests/ -v
```

## Cost

| Service | Cost |
|---------|------|
| Claude Haiku 4.5 (w/ prompt caching) | ~$1–3/month |
| Groq Whisper | Free tier |
| Cloudflare Tunnel | Free |

## License

MIT
