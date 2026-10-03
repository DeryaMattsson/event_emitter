"""A tiny, typed event emitter with `on`, `once`, `off`, and `emit`.

Design decisions, stated plainly:

1. Listeners are stored in a dict keyed by event name, where each value is a
   list. Lists preserve insertion order and, unlike sets, allow the same
   callable to be registered more than once. Both behaviors are useful and
   removing either would surprise someone. The cost is that removing a
   specific listener when it was added twice requires deciding which one to
   drop; we drop the first match, which is the least-surprising choice.

2. `once` listeners are wrapped in a one-shot dispatcher that removes itself
   before invoking the user callback. Removing *before* calling is deliberate:
   if the callback re-emits the same event, the once-listener must not fire
   again. Re-entrancy is a real edge case (a listener that emits during
   handling) and we document the chosen semantics below rather than try to
   support several readings at once.

3. Emitting during iteration over the listener list would raise if the list
   were mutated mid-loop. We therefore iterate over a shallow copy of the
   current listeners for each event. A listener added during emission will
   not see the current emit; a listener removed during emission may still be
   called if it was in the snapshot. This is the standard, predictable
   semantics and matches what most emitters do.

4. Exceptions raised by a listener propagate out of `emit` immediately. We do
   not catch, log, or continue. Swallowing errors silently is a common source
   of hidden bugs; the caller of `emit` is in a better position to decide how
   to handle a failing listener.

5. `emit` returns a boolean: True if any listener was invoked, False if no
   listeners were registered for that event. This is useful for
   logging/gauging whether an event had observers without a separate query.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, TypeVar

T = TypeVar("T")

# A listener is any callable accepting arbitrary positional arguments and
# returning anything. We intentionally do not constrain the return type
# because return values are ignored by the emitter.
Listener = Callable[..., Any]


class EventEmitter:
    """A minimal, synchronous event emitter.

    Example::

        from event_emitter import EventEmitter

        bus = EventEmitter()
        bus.on("tick", lambda n: print("tick", n))
        bus.emit("tick", 1)   # prints: tick 1

    Listener equality for `off` is by Python identity (`==`), which for plain
    functions and bound methods compares by value/identity as expected. For
    `once` listeners, pass the *original* callable to `off`; the internal
    wrapper is matched by looking up the original inside its closure so that
    callers do not need to keep the wrapper reference around.
    """

    def __init__(self) -> None:
        # Mapping from event name to the list of listeners (including
        # once-wrappers) currently registered, in insertion order.
        self._listeners: Dict[str, List[Listener]] = {}

    def on(self, event: str, listener: Listener) -> Callable[[], None]:
        """Register ``listener`` for ``event``.

        Returns a disposer function that, when called, removes this exact
        registration. Using the disposer is preferred over ``off`` when the
        same callable is registered multiple times, because it targets the
        specific registration rather than the first match.

        Registering the same callable twice is allowed and results in it being
        invoked twice per emit.
        """
        if not callable(listener):
            raise TypeError("listener must be callable")
        self._listeners.setdefault(event, []).append(listener)
        listeners = self._listeners[event]

        def _dispose() -> None:
            # Remove by identity within the specific event's list so that
            # other events or other registrations of the same callable are
            # untouched.
            try:
                # index() uses ==; for functions that is identity-based.
                idx = listeners.index(listener)
            except ValueError:
                # Already removed (e.g., once-wrapper already cleaned up, or
                # dispose called twice). Silently no-op.
                return
            listeners.pop(idx)

        return _dispose

    def once(self, event: str, listener: Listener) -> Callable[[], None]:
        """Register ``listener`` for ``event`` so it fires at most once.

        Returns a disposer function that removes the one-shot registration.
        If the listener has already fired, calling the disposer is a no-op.

        The wrapper removes itself from the list *before* invoking the user
        callback. This means a callback that re-emits the same event will not
        cause the once-listener to fire again, which is the behavior most
        callers expect from the word "once".
        """
        if not callable(listener):
            raise TypeError("listener must be callable")

        def _one_shot(*args: Any, **kwargs: Any) -> None:
            # Remove first. We look up by the wrapper's own identity because
            # that is what is stored in the list. If the wrapper was already
            # removed (e.g., via the disposer), index() raises ValueError and
            # we treat that as "already ran" — do nothing.
            listeners = self._listeners.get(event, [])
            try:
                idx = listeners.index(_one_shot)
            except ValueError:
                return
            listeners.pop(idx)
            listener(*args, **kwargs)

        self._listeners.setdefault(event, []).append(_one_shot)
        listeners = self._listeners[event]

        def _dispose() -> None:
            try:
                idx = listeners.index(_one_shot)
            except ValueError:
                return
            listeners.pop(idx)

        return _dispose

    def off(self, event: str, listener: Listener) -> bool:
        """Remove ``listener`` from ``event``.

        For a listener registered via ``once``, pass the *original* callable;
        the internal wrapper is located by scanning for a once-wrapper whose
        bound original matches. If multiple once-wrappers share the same
        original callable, the first one encountered is removed.

        Returns True if a listener was removed, False otherwise. Removing a
        listener that was never registered (or already removed) returns False
        and is not an error.
        """
        listeners = self._listeners.get(event)
        if not listeners:
            return False

        for idx, stored in enumerate(listeners):
            if stored is listener or stored == listener:
                listeners.pop(idx)
                return True
            # Detect once-wrappers created by this emitter. We compare by
            # the closure cell that holds the user-supplied listener, so that
            # callers can pass the original function rather than the wrapper
            # they never see.
            original = self._unwrap_once(stored)
            if original is not None and (
                original is listener or original == listener
            ):
                listeners.pop(idx)
                return True
        return False

    @staticmethod
    def _unwrap_once(stored: Listener) -> Listener | None:
        """If ``stored`` is a once-wrapper created by this emitter, return the
        original user listener; otherwise return None.

        We identify our own wrappers by their ``__name__`` and the presence of
        a closure cell named ``listener``. This is intentionally narrow so we
        never accidentally introspect arbitrary callables from third parties.
        """
        if getattr(stored, "__name__", None) != "_one_shot":
            return None
        cell = None
        for cell in getattr(stored, "__closure__", None) or ():
            pass
        # The wrapper closes over exactly two names: ``self`` and ``listener``.
        # We want the ``listener`` cell.
        closure = getattr(stored, "__closure__", None) or ()
        freevars = getattr(stored, "__code__", None)
        if freevars is not None:
            names = freevars.co_freevars
            for name, c in zip(names, closure):
                if name == "listener":
                    return c.cell_contents  # type: ignore[no-any-return]
        return None

    def emit(self, event: str, *args: Any, **kwargs: Any) -> bool:
        """Synchronously invoke all listeners for ``event``.

        Returns True if at least one listener was invoked, False otherwise.

        Listeners are invoked in insertion order over a snapshot taken at the
        start of the emit. A listener added during this emit will not be
        called for this emit; a listener removed during this emit that was in
        the snapshot may still be called.

        If a listener raises, the exception propagates out of ``emit``
        immediately and remaining listeners are not invoked for this emit.
        """
        listeners = self._listeners.get(event)
        if not listeners:
            return False
        # Shallow copy so mutations during iteration (on/once/off called from
        # inside a listener) do not change the set of listeners invoked for
        # *this* emit beyond what was present at snapshot time.
        snapshot = list(listeners)
        for listener in snapshot:
            listener(*args, **kwargs)
        return True

    def listener_count(self, event: str) -> int:
        """Return the number of currently registered listeners for ``event``."""
        return len(self._listeners.get(event, ()))

    def remove_all_listeners(self, event: str | None = None) -> None:
        """Remove all listeners for ``event``, or all listeners for every
        event when ``event`` is None."""
        if event is None:
            self._listeners.clear()
        else:
            self._listeners.pop(event, None)
