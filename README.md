# event_emitter

A tiny, dependency-free typed event emitter for Python with `on`, `once`, `off`, `emit`, `listener_count`, and `remove_all_listeners`.

```python
from event_emitter import EventEmitter

bus = EventEmitter()

# Register a persistent listener; on() returns a disposer that removes
# exactly this registration.
dispose = bus.on("tick", lambda n: print("tick", n))
bus.emit("tick", 1)        # tick 1
print(bus.emit("tick", 2)) # tick 2\nTrue

# One-shot listener that removes itself before invoking the callback.
bus.once("boom", lambda: print("boom!"))
bus.emit("boom")  # boom!\nTrue
bus.emit("boom")  # (nothing)\nFalse

# Remove by the original callable. Works for both on() and once() listeners.
def handler():
    print("hi")

bus.on("greet", handler)
bus.off("greet", handler)  # -> True
bus.off("greet", handler)  # -> False (already gone)
```

## Why this exists

The standard library has no general-purpose event emitter, and the common
third-party options pull in more machinery than a small project needs. This
library is a single module with no dependencies and a small, predictable
surface: register, emit, remove. The trade-off is that there is no async
support, no wildcard listeners, no namespacing, and no built-in error
handling — if a listener raises, the exception propagates out of `emit`
immediately and remaining listeners for that emit are skipped.

## Edges you will hit

- **Registering the same callable twice fires it twice.** This is intentional.
  Use the disposer returned by `on` to remove one specific registration
  rather than `off`, which removes the first match.
- **`once` removes itself *before* calling your callback.** If your callback
  re-emits the same event, the once-listener will not fire again. That is the
  chosen interpretation of "once".
- **Emitting iterates over a snapshot.** A listener added during an emit will
  not be called for that emit (only future ones). A listener removed during an
  emit that was already in the snapshot may still be called for that emit.
- **`off` for a `once` listener takes the original callable**, not the
  internal wrapper. The wrapper is matched by introspection limited to
  wrappers created by this emitter, so passing arbitrary callables is safe.
