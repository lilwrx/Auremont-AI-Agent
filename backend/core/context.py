"""Request-scoped context shared between middleware, logging and audit.

Lives in its own module so `logging_config` can read the request id without
importing the middleware, and the middleware can set it without importing the
logging config — otherwise the two would form an import cycle.

Propagation note: FastAPI runs sync `def` endpoints through
`anyio.to_thread.run_sync`, which copies the current context into the worker
thread. The whole of `backend/services/*` is synchronous, so anything called
below an endpoint sees the same request id without having to pass it around.
"""

from contextvars import ContextVar, Token

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def set_request_id(request_id: str) -> Token[str]:
    """Bind the id for the current context; keep the token to undo it later."""
    return request_id_var.set(request_id)


def reset_request_id(token: Token[str]) -> None:
    """Restore the previous value.

    Always call this in a `finally`. Without it, a request that raised would
    leave its id bound to the worker thread and the next request handled by that
    same thread would be logged under the wrong id.
    """
    request_id_var.reset(token)


def get_request_id() -> str:
    """Current request id, or "" outside a request (startup, tests, scripts)."""
    return request_id_var.get()
