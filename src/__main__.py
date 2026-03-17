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


def main() -> None:
    load_dotenv()
    config = load_config()

    log = structlog.get_logger()
    log.info("starting_bot", model=config.claude_model, users=len(config.user_map))

    app = create_app(config)
    app.run_polling()


if __name__ == "__main__":
    main()
