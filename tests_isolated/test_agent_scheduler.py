"""Offline scheduler tests: no real HTTP, commands, installs or agent startup."""
import importlib.util
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "scheduler_agent", Path(__file__).resolve().parents[1] / "agent/stella_agent.py")
assert SPEC is not None and SPEC.loader is not None
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)


class SchedulerTests(unittest.TestCase):
    def test_iperf_error_result_retains_authenticated_server_role(self):
        instance = agent.Agent('http://offline.invalid','offline')
        results=[]
        def fail(task): raise RuntimeError('server bind failure')
        with patch.object(instance,'_iperf_server',fail), patch.object(instance,'_post',lambda *a,**kw:results.append(kw)):
            instance._run_iperf({'id':3,'mode':'iperf3','role':'server'})
        self.assertEqual(results[0]['json_body'].get('role'), 'server')
        self.assertEqual(results[0]['status'], 'failed')

    def test_heartbeat_sample_while_task_worker_blocked(self):
        for kind, handler in (("commands", "_run_command"),
                              ("mtr_tasks", "_run_mtr"),
                              ("component_installs", "_run_component_install"),
                              ("net_tasks", "_run_net_task"),
                              ("probes", "run_due_probes"),
                              ("poll", "_get")):
            with self.subTest(kind=kind):
                self._heartbeat_with_blocked_task(kind, handler)

    def _heartbeat_with_blocked_task(self, kind, handler):
        instance = agent.Agent("http://offline.invalid", "offline")
        started, release, sampled, stop = (threading.Event() for _ in range(4))
        calls = []
        updates_during_task = []

        def blocked(*args, **kwargs):
            started.set()
            release.wait(8)
            return {}

        def poll(*args, **kwargs):
            calls.append(1)
            return {kind: [{"id": 1}]}

        def sample():
            if started.is_set() and not release.is_set():
                sampled.set()
            return [{"ts": "offline"}]

        replacements = {
            "_post": lambda *a, **k: {}, "list_interfaces": lambda: [],
            "list_storage": lambda: [], "_check_components": lambda: {},
            "_os_info": lambda: {}, "_probe_public_ip": lambda: {},
            "refresh_config": lambda: None, "check_update": lambda: updates_during_task.append(1) if started.is_set() and not release.is_set() else None,
            "run_due_probes": lambda: None, "collect_sys": lambda: {},
            "collect_metrics": sample, "report": lambda *a: None,
            "_get": poll, handler: blocked,
        }
        with patch.multiple(instance, **replacements), \
                patch.object(agent, "REPORT_INTERVAL", 5 if kind == "commands" else .02), \
                patch.object(agent, "UPDATE_CHECK_INTERVAL", .01), \
                patch.object(agent, "POLL_INTERVAL", .005):
            # The real run loop is exercised; only external IO is replaced.
            errors = []
            def run():
                try:
                    instance.run(stop_event=stop)
                except Exception as exc:
                    errors.append(exc)
            thread = threading.Thread(target=run)
            thread.start()
            try:
                self.assertTrue(started.wait(1), errors)
                self.assertTrue(sampled.wait(6), "sampling blocked behind task execution")
                self.assertEqual(updates_during_task, [], "auto-update must not interrupt a running task")
                if kind not in ("probes", "poll"):
                    self.assertEqual(len(calls), 1, "duplicate poll while batch is in flight")
            finally:
                stop.set()
                release.set()
                thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])

    def test_bounded_single_flight_and_cancel_cleanup(self):
        scheduler = agent._BackgroundScheduler(max_workers=2)
        release = threading.Event()
        started = [threading.Event(), threading.Event()]
        def blocked(index):
            started[index].set()
            release.wait(3)
        try:
            self.assertTrue(scheduler.submit("tasks", lambda: blocked(0)))
            self.assertTrue(scheduler.submit("probes", lambda: blocked(1)))
            self.assertTrue(all(event.wait(1) for event in started))
            for _ in range(50):
                self.assertFalse(scheduler.submit("tasks", lambda: None))
                self.assertFalse(scheduler.submit("probes", lambda: None))
                self.assertFalse(scheduler.submit("overflow", lambda: None))
            scheduler.close(timeout=0)
            self.assertFalse(scheduler.submit("new", lambda: None))
            # Cancellation retains in-flight ownership until actual completion.
            self.assertEqual(len(scheduler._threads), 2)
        finally:
            release.set()
            scheduler.close(timeout=2)
        self.assertEqual(scheduler._threads, {})
        self.assertFalse(scheduler.submit("tasks", lambda: None))

    def test_exception_releases_lane(self):
        scheduler = agent._BackgroundScheduler(max_workers=1)
        def broken():
            raise RuntimeError("offline expected error")
        self.assertTrue(scheduler.submit("tasks", broken))
        with scheduler._lock:
            threads = list(scheduler._threads.values())
        for thread in threads:
            thread.join(1)
        self.assertEqual(scheduler._threads, {})
        finished = threading.Event()
        self.assertTrue(scheduler.submit("tasks", finished.set))
        self.assertTrue(finished.wait(1))
        scheduler.close()
        self.assertEqual(scheduler._threads, {})


if __name__ == "__main__":
    unittest.main()
