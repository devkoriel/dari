import os
import sys

import structlog
from dotenv import load_dotenv

from src.bot import create_app
from src.config import load_config

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
)

log = structlog.get_logger()

ALLOWED_UPDATES = ["message", "my_chat_member"]


def main() -> None:
    load_dotenv()

    try:
        config = load_config()
    except ValueError as e:
        log.error("config_error", error=str(e))
        sys.exit(1)

    os.makedirs(config.data_dir, exist_ok=True)
    log.info("starting_bot", model=config.claude_model, users=len(config.user_map))

    app = create_app(config)

    if config.webhook_url:
        webhook_path = "/webhook"
        full_url = f"{config.webhook_url.rstrip('/')}{webhook_path}"
        log.info("webhook_mode", url=full_url, port=config.webhook_port)
        app.run_webhook(
            listen="127.0.0.1",
            port=config.webhook_port,
            url_path=webhook_path,
            webhook_url=full_url,
            allowed_updates=ALLOWED_UPDATES,
            drop_pending_updates=True,
            secret_token=config.telegram_token[:32],
        )
    else:
        log.info("polling_mode")
        app.run_polling(
            allowed_updates=ALLOWED_UPDATES,
            drop_pending_updates=True,
            poll_interval=1.0,
            timeout=30,
        )


if __name__ == "__main__":
    main()
