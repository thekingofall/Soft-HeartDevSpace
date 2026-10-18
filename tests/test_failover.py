import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("failover", Path(__file__).resolve().parents[1] / "relay/failover.py")
failover = importlib.util.module_from_spec(spec)
spec.loader.exec_module(failover)


class FailoverTests(unittest.TestCase):
    def test_transient_failure_and_dead_backup_keep_route(self):
        one = failover.choose({}, {"cloudflare": False, "frp": True}, 100)
        self.assertEqual(one["active"], "cloudflare")
        two = failover.choose(one, {"cloudflare": False, "frp": False}, 110)
        self.assertEqual(two["active"], "cloudflare")
        three = failover.choose(two, {"cloudflare": False, "frp": True}, 120)
        self.assertEqual(three["active"], "frp")

    def test_recovery_requires_successes_and_hold_time(self):
        state = dict(active="frp", switched_at=100)
        for now in (110, 120, 130):
            state = failover.choose(state, {"cloudflare": True, "frp": True}, now)
            self.assertEqual(state["active"], "frp")
        self.assertEqual(failover.choose(state, {"cloudflare": True, "frp": True}, 160)["active"], "cloudflare")

    def test_failed_reload_restores_route(self):
        with tempfile.TemporaryDirectory() as temp:
            route = Path(temp) / "route.conf"
            route.write_text("original")
            config = dict(route_file=str(route), ports={"frp": 17677}, validate_command=["nginx", "-t"], reload_command=["reload"])
            with patch.object(failover.subprocess, "run", side_effect=[None, RuntimeError("reload failed"), None, None]) as run:
                with self.assertRaises(RuntimeError):
                    failover.switch(config, "frp")
                self.assertEqual(run.call_count, 4)
            self.assertEqual(route.read_text(), "original")

    def test_crash_after_route_reload_recovers_from_route(self):
        with tempfile.TemporaryDirectory() as temp:
            route, state = Path(temp)/"route", Path(temp)/"state"
            route.write_text('set $heart_transport frp;\n')
            state.write_text('{"active":"cloudflare","failures":5}')
            loaded = failover.load_state(dict(route_file=str(route), state_file=str(state)))
            self.assertEqual(loaded["active"], "frp")
            self.assertTrue(loaded["reload_required"])
            self.assertNotIn("failures", loaded)
