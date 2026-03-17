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


def main() -> None:
    load_dotenv()

    try:
        config = load_config()
    except ValueError as e:
        log.error("config_error", error=str(e))
        sys.exit(1)

    log.info("starting_bot", model=config.claude_model, users=len(config.user_map))

    app = create_app(config)
    app.run_polling(allowed_updates=["message", "my_chat_member"])


if __name__ == "__main__":
    main()
