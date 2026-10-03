import unittest

from event_emitter import EventEmitter


class OnOffTests(unittest.TestCase):
    def test_on_then_emit_invokes_listener(self):
        bus = EventEmitter()
        seen = []
        bus.on("tick", lambda n: seen.append(n))
        fired = bus.emit("tick", 5)
        self.assertEqual(seen, [5])
        self.assertTrue(fired)

    def test_emit_with_no_listeners_returns_false(self):
        bus = EventEmitter()
        self.assertFalse(bus.emit("nothing"))

    def test_multiple_listeners_called_in_order(self):
        bus = EventEmitter()
        order = []
        bus.on("e", lambda: order.append("a"))
        bus.on("e", lambda: order.append("b"))
        bus.on("e", lambda: order.append("c"))
        bus.emit("e")
        self.assertEqual(order, ["a", "b", "c"])

    def test_same_callable_registered_twice_fires_twice(self):
        bus = EventEmitter()
        calls = []

        def cb():
            calls.append(1)

        bus.on("e", cb)
        bus.on("e", cb)
        bus.emit("e")
        self.assertEqual(calls, [1, 1])

    def test_off_removes_first_match(self):
        bus = EventEmitter()
        calls = []

        def cb():
            calls.append(1)

        bus.on("e", cb)
        bus.on("e", cb)
        self.assertTrue(bus.off("e", cb))
        bus.emit("e")
        self.assertEqual(calls, [1])

    def test_off_unknown_returns_false(self):
        bus = EventEmitter()
        self.assertFalse(bus.off("e", lambda: None))

    def test_off_specific_event_does_not_touch_other_events(self):
        bus = EventEmitter()
        a = []
        b = []
        cb_a = lambda: a.append(1)
        cb_b = lambda: b.append(1)
        bus.on("a", cb_a)
        bus.on("b", cb_b)
        bus.off("a", cb_a)
        bus.emit("a")
        bus.emit("b")
        self.assertEqual(a, [])
        self.assertEqual(b, [1])

    def test_disposer_targets_specific_registration(self):
        bus = EventEmitter()
        calls = []

        def cb():
            calls.append(1)

        d1 = bus.on("e", cb)
        bus.on("e", cb)
        d1()
        bus.emit("e")
        # Only the second registration remains.
        self.assertEqual(calls, [1])
        self.assertEqual(bus.listener_count("e"), 1)

    def test_disposer_is_idempotent(self):
        bus = EventEmitter()
        calls = []
        d = bus.on("e", lambda: calls.append(1))
        d()
        d()  # second call must not raise
        bus.emit("e")
        self.assertEqual(calls, [])


class OnceTests(unittest.TestCase):
    def test_once_fires_only_on_first_emit(self):
        bus = EventEmitter()
        calls = []
        bus.once("e", lambda n: calls.append(n))
        bus.emit("e", 1)
        bus.emit("e", 2)
        self.assertEqual(calls, [1])
        self.assertEqual(bus.listener_count("e"), 0)

    def test_once_returns_true_only_when_invoked(self):
        bus = EventEmitter()
        bus.once("e", lambda: None)
        self.assertTrue(bus.emit("e"))  # fires
        self.assertFalse(bus.emit("e"))  # no listeners now

    def test_once_disposer_prevents_firing(self):
        bus = EventEmitter()
        calls = []
        d = bus.once("e", lambda: calls.append(1))
        d()
        self.assertFalse(bus.emit("e"))
        self.assertEqual(calls, [])

    def test_off_removes_once_listener_by_original_callable(self):
        bus = EventEmitter()
        calls = []

        def cb():
            calls.append(1)

        bus.once("e", cb)
        self.assertTrue(bus.off("e", cb))
        bus.emit("e")
        self.assertEqual(calls, [])

    def test_once_does_not_refire_when_callback_reemits(self):
        # The wrapper removes itself BEFORE calling the user callback, so a
        # re-entrant emit must not re-invoke the once listener.
        bus = EventEmitter()
        log = []

        def cb():
            log.append("once")
            if len(log) < 3:
                bus.emit("e")

        bus.once("e", cb)
        bus.emit("e")
        self.assertEqual(log, ["once"])


class EmitSnapshotTests(unittest.TestCase):
    def test_listener_added_during_emit_not_called_for_current_emit(self):
        bus = EventEmitter()
        seen = []

        def adder():
            seen.append("first")
            bus.on("e", lambda: seen.append("second"))

        bus.on("e", adder)
        bus.emit("e")
        self.assertEqual(seen, ["first"])
        # The newly added listener IS registered for future emits.
        bus.emit("e")
        self.assertEqual(seen, ["first", "first", "second"])

    def test_listener_removed_during_emit_still_called_if_in_snapshot(self):
        # Removing a sibling listener from inside a listener: the removed one
        # was already in the snapshot, so it still fires for this emit. This
        # documents the chosen semantics rather than treating it as a bug.
        bus = EventEmitter()
        log = []

        def first():
            log.append("first")
            bus.off("e", second)

        def second():
            log.append("second")

        bus.on("e", first)
        bus.on("e", second)
        bus.emit("e")
        self.assertEqual(log, ["first", "second"])
        # And it is gone for the next emit.
        log.clear()
        bus.emit("e")
        self.assertEqual(log, ["first"])


class ExceptionPropagationTests(unittest.TestCase):
    def test_listener_exception_propagates_and_halts(self):
        bus = EventEmitter()
        log = []

        def boom():
            raise ValueError("nope")

        bus.on("e", boom)
        bus.on("e", lambda: log.append("after"))
        with self.assertRaises(ValueError):
            bus.emit("e")
        self.assertEqual(log, [])


class MiscTests(unittest.TestCase):
    def test_kwargs_are_forwarded(self):
        bus = EventEmitter()
        captured = {}
        bus.on("e", lambda **kw: captured.update(kw))
        bus.emit("e", a=1, b=2)
        self.assertEqual(captured, {"a": 1, "b": 2})

    def test_remove_all_listeners_for_one_event(self):
        bus = EventEmitter()
        a = []
        b = []
        bus.on("a", lambda: a.append(1))
        bus.on("b", lambda: b.append(1))
        bus.remove_all_listeners("a")
        self.assertEqual(bus.listener_count("a"), 0)
        self.assertEqual(bus.listener_count("b"), 1)

    def test_remove_all_listeners_everything(self):
        bus = EventEmitter()
        bus.on("a", lambda: None)
        bus.on("b", lambda: None)
        bus.remove_all_listeners()
        self.assertEqual(bus.listener_count("a"), 0)
        self.assertEqual(bus.listener_count("b"), 0)

    def test_on_rejects_non_callable(self):
        bus = EventEmitter()
        with self.assertRaises(TypeError):
            bus.on("e", 42)

    def test_once_rejects_non_callable(self):
        bus = EventEmitter()
        with self.assertRaises(TypeError):
            bus.once("e", "not a callable")


if __name__ == "__main__":
    unittest.main()
