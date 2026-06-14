import time

from prometheus_client import Counter, Gauge, generate_latest, REGISTRY

_start = time.time()

events_received = Counter(
    "tg_if_events_received_total",
    "Events received from Telegram",
    labelnames=["bot"],
)

events_matched = Counter(
    "tg_if_events_matched_total",
    "Events matched by the rules engine",
    labelnames=["bot"],
)

events_published = Counter(
    "tg_if_events_published_total",
    "Events published to RabbitMQ",
    labelnames=["bot"],
)

responses_consumed = Counter(
    "tg_if_responses_consumed_total",
    "Responses consumed from outgoing.responses",
)

responses_sent = Counter(
    "tg_if_responses_sent_total",
    "Responses sent to Telegram",
)

responses_failed = Counter(
    "tg_if_responses_failed_total",
    "Responses that permanently failed after retries",
)

broker_connected = Gauge(
    "tg_if_broker_connected",
    "Broker connection status (1=connected, 0=disconnected)",
)

client_connected = Gauge(
    "tg_if_client_connected",
    "Telegram client connection status (1=connected, 0=disconnected)",
    labelnames=["bot"],
)

uptime_seconds = Gauge(
    "tg_if_uptime_seconds",
    "Service uptime in seconds",
)

uptime_seconds.set_function(lambda: time.time() - _start)


def generate_metrics() -> str:
    return generate_latest(REGISTRY).decode()
