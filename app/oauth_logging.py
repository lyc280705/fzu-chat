"""Keep authorization codes and state out of Uvicorn access logs."""
import logging


class OAuthAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            path = args[2]
            if path.startswith(("/api/auth/oauth/", "/api/auth/callback/")):
                record.args = (*args[:2], path.split("?", 1)[0], *args[3:])
        return True


def install_oauth_log_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, OAuthAccessLogFilter) for item in logger.filters):
        logger.addFilter(OAuthAccessLogFilter())
