import logging

logger = logging.getLogger(__name__)

# Shared with main.py's logging.basicConfig() call and api/log_broadcaster.py -
# keeping one definition means log lines served via GET /system/logs and
# /ws/logs are formatted identically to what `docker logs`/the console show.
LOG_FORMAT = "%(asctime)s %(name)-20s - %(levelname)-8s - %(message)s"
