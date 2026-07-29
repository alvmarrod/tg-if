from prometheus_client import generate_latest, CollectorRegistry, Counter, Gauge

from infrastructure.metrics_exporter import generate_metrics


class TestGenerateMetrics:
    def test_returns_prometheus_text(self) -> None:
        text = generate_metrics()
        assert isinstance(text, str)
        assert len(text) > 0
        assert "# HELP" in text
        assert "# TYPE" in text

    def test_contains_expected_metric_names(self) -> None:
        text = generate_metrics()
        names = [
            "tg_if_events_received_total",
            "tg_if_events_matched_total",
            "tg_if_events_published_total",
            "tg_if_responses_consumed_total",
            "tg_if_responses_sent_total",
            "tg_if_responses_failed_total",
            "tg_if_broker_connected",
            "tg_if_client_connected",
            "tg_if_uptime_seconds",
        ]
        for name in names:
            assert name in text, f"missing {name}"

    def test_uptime_metric_has_value(self) -> None:
        text = generate_metrics()
        for line in text.splitlines():
            if line.startswith("tg_if_uptime_seconds"):
                val = float(line.split()[-1])
                assert val > 0
                return
        raise AssertionError("uptime_seconds metric not found")


class TestCounterOnSeparateRegistry:
    def test_counter_increment_reflected(self) -> None:
        reg = CollectorRegistry()
        c = Counter("test_counter", "help", registry=reg)
        c.inc(3)
        text = generate_latest(reg).decode()
        assert "test_counter_total 3.0" in text

    def test_labelled_counter_reflects_labels(self) -> None:
        reg = CollectorRegistry()
        c = Counter("test_labelled", "help", labelnames=["env"], registry=reg)
        c.labels(env="prod").inc(7)
        text = generate_latest(reg).decode()
        assert 'test_labelled_total{env="prod"} 7.0' in text

    def test_gauge_value_reflected(self) -> None:
        reg = CollectorRegistry()
        g = Gauge("test_gauge", "help", registry=reg)
        g.set(42)
        text = generate_latest(reg).decode()
        assert "test_gauge 42.0" in text
