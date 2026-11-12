"""Process-local bounded gateways, fed by one dedicated direct PostgreSQL session.

Hints contain no content. Every stream authenticates at establishment and at
least every heartbeat; idle streams do not extend login-session lifetime.
"""

import asyncio
from datetime import datetime, timezone
from contextlib import suppress
from dataclasses import dataclass, field
import json
import logging
import os
from urllib.parse import urlsplit
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from starlette.responses import StreamingResponse

from ..operation_policy import operation_policy
from ..authentication import SESSION_COOKIE, hash_secret
from ..config import integer_environment
from ..database import database_url, pool
from . import reading

CHANNEL = "wathiq_messages"
MAX_CONNECTIONS = integer_environment(
    "MESSAGING_STREAM_MAX_CONNECTIONS", 1000, minimum=1
)
MAX_USER_CONNECTIONS = integer_environment(
    "MESSAGING_STREAM_MAX_USER_CONNECTIONS", 20, minimum=1
)
QUEUE_SIZE = integer_environment("MESSAGING_STREAM_QUEUE_SIZE", 64, minimum=1)
HEARTBEAT_SECONDS = integer_environment(
    "MESSAGING_STREAM_HEARTBEAT_SECONDS", 15, minimum=1
)
SEND_TIMEOUT = integer_environment(
    "MESSAGING_STREAM_SEND_TIMEOUT_SECONDS", 5, minimum=1
)
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/messages", tags=["messages"])


def event(kind, **fields):
    return {"schema_version": 1, "event_type": kind, **fields}


def authenticate(token):
    # Read-only: transport heartbeats must not silently defeat session idle expiry.
    with pool.connection() as c:
        row = c.execute(
            """SELECT s.user_id FROM login_sessions s
            JOIN users u ON u.id=s.user_id JOIN user_credentials p ON p.user_id=u.id
            WHERE s.session_token_hash=%s AND s.revoked_at IS NULL
            AND s.expires_at>CURRENT_TIMESTAMP AND s.absolute_expires_at>CURRENT_TIMESTAMP
            AND u.status='active' AND u.account_type='person' AND NOT p.must_change_password""",
            (hash_secret(token),),
        ).fetchone()
    return row["user_id"] if row else None


def visible(user, identity):
    with pool.connection() as c:
        c.execute("SELECT set_config('app.user_id',%s,true)", (str(user),))
        return bool(
            c.execute(
                f"""SELECT 1 FROM {reading.JOIN}
            WHERE d.id=%s AND d.recipient_user_id=%s AND {reading.ACTIVE_INBOX}
            AND {reading.VISIBLE}""",
                (identity, user, user),
            ).fetchone()
        )


def credentials(connection):
    authorization = connection.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    else:
        token = connection.cookies.get(SESSION_COOKIE, "")
        # Cookie-authenticated upgrades need same-origin protection. SSE is a
        # same-origin read; reject cross-origin origins when one is supplied.
        origin = connection.headers.get("origin")
        if isinstance(connection, WebSocket) or origin:
            parsed = urlsplit(origin or "")
            expected_scheme = (
                "https" if connection.url.scheme in {"https", "wss"} else "http"
            )
            if (
                parsed.scheme != expected_scheme
                or parsed.netloc != connection.url.netloc
            ):
                raise HTTPException(403, "message_stream_origin_denied")
    if not token or len(token) > 4096 or connection.query_params:
        raise HTTPException(401, "message_stream_authentication_required")
    return token


@dataclass(eq=False)
class Subscriber:
    user: int
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(QUEUE_SIZE))
    overflow: bool = False

    def push(self, value):
        if self.overflow:
            return
        try:
            self.queue.put_nowait(value)
        except asyncio.QueueFull:
            self.overflow = True
            # Wake the consumer without retaining a backlog after disconnection.
            while not self.queue.empty():
                self.queue.get_nowait()
            self.queue.put_nowait(None)


class Gateway:
    def __init__(self):
        self.clients = {}
        self.connection = None
        self.task = None
        self.ready = False
        self.health_changed = asyncio.Event()
        self.generation = 0
        self.stopping = False
        self.notifications_received = 0
        self.last_notification_at = None
        self.slow_disconnects = 0

    def health(self):
        return {
            "listener_connected": self.ready,
            "listener_generation": self.generation,
        }

    def operational_health(self):
        return {**self.health(), "notifications_received": self.notifications_received,
                "last_notification_at": self.last_notification_at,
                "active_connections": sum(map(len,self.clients.values())),
                "slow_disconnects": self.slow_disconnects}

    def start(self):
        self.stopping = False
        self.task = asyncio.create_task(
            self.listen(), name="messaging-postgres-listener"
        )

    async def stop(self):
        self.stopping = True
        if self.task:
            self.task.cancel()
            # Close the dedicated socket as well: an idle notification wait can
            # otherwise delay lifespan shutdown after task cancellation.
            if self.connection is not None:
                await self.connection.close()
            with suppress(asyncio.CancelledError):
                await self.task
        for group in tuple(self.clients.values()):
            for client in tuple(group):
                client.push(None)
        self.clients.clear()

    def subscribe(self, user):
        if (
            sum(map(len, self.clients.values())) >= MAX_CONNECTIONS
            or len(self.clients.get(user, ())) >= MAX_USER_CONNECTIONS
        ):
            raise HTTPException(503, "message_stream_capacity_reached")
        subscriber = Subscriber(user)
        self.clients.setdefault(user, set()).add(subscriber)
        subscriber.push(event("reconciliation_required"))
        return subscriber

    def remove(self, subscriber):
        group = self.clients.get(subscriber.user)
        if group is not None and subscriber in group:
            if subscriber.overflow:
                self.slow_disconnects += 1
            group.discard(subscriber)
            if not group:
                self.clients.pop(subscriber.user, None)

    def broadcast(self, payload):
        self.notifications_received += 1
        self.last_notification_at = datetime.now(timezone.utc)
        try:
            data = json.loads(payload)
            identity = str(UUID(data["delivery_id"]))
            user, sequence = data["recipient_user_id"], data["mailbox_sequence"]
            if (
                type(user) is not int
                or type(sequence) is not int
                or user < 1
                or not 0 < sequence <= 9223372036854775807
            ):
                return
        except (ValueError, KeyError, TypeError):
            return
        hint = event("message_available", delivery_id=identity, mailbox_cursor=sequence)
        for client in tuple(self.clients.get(user, ())):
            client.push(hint)

    async def listen(self):
        backoff = 1
        while not self.stopping:
            try:
                # Deliberately not pool.connection(): subscription state never
                # enters the request pool. Autocommit avoids idle transactions.
                async with await psycopg.AsyncConnection.connect(
                    os.environ.get("MESSAGING_LISTENER_DATABASE_URL") or database_url(),
                    autocommit=True,
                    connect_timeout=5,
                    keepalives_idle=30,
                    keepalives_interval=10,
                    keepalives_count=3,
                    application_name="wathiq-message-listener",
                ) as connection:
                    self.connection = connection
                    await connection.execute("LISTEN " + CHANNEL)
                    self.ready = True
                    self.generation += 1
                    self.health_changed.set()
                    backoff = 1
                    for group in tuple(self.clients.values()):
                        for client in tuple(group):
                            client.push(event("reconciliation_required"))
                    async for notification in connection.notifies():
                        self.broadcast(notification.payload)
            except asyncio.CancelledError:
                raise
            except (psycopg.Error, OSError):
                if not self.stopping:
                    logger.warning(
                        "Messaging listener disconnected; durable Inbox remains available"
                    )
            finally:
                was_ready = self.ready
                self.ready = False
                self.connection = None
                if was_ready:
                    self.health_changed.set()
            if self.stopping:
                return
            await asyncio.sleep(backoff)
            backoff = min(30, backoff * 2)


async def next_event(subscriber, token):
    try:
        value = await asyncio.wait_for(subscriber.queue.get(), HEARTBEAT_SECONDS)
    except asyncio.TimeoutError:
        value = event("heartbeat")
    if subscriber.overflow or value is None:
        return None
    if await asyncio.to_thread(authenticate, token) != subscriber.user:
        raise HTTPException(401, "message_stream_session_expired")
    if value["event_type"] == "message_available" and not await asyncio.to_thread(
        visible, subscriber.user, value["delivery_id"]
    ):
        return event("heartbeat")
    return value


@router.websocket("/stream/ws")
async def websocket_stream(websocket: WebSocket):
    gateway = websocket.app.state.messaging_gateway
    subscriber = None
    receiver = None
    try:
        token = credentials(websocket)
        user = await asyncio.to_thread(authenticate, token)
        if user is None:
            raise HTTPException(401, "message_stream_authentication_required")
        subscriber = gateway.subscribe(user)
        await websocket.accept()

        async def receive():
            # No client subscriptions or arbitrary routing commands are accepted.
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                if message.get("text") or message.get("bytes"):
                    await websocket.close(code=1008)
                    return

        receiver = asyncio.create_task(receive())
        while not receiver.done():
            pending = asyncio.create_task(next_event(subscriber, token))
            try:
                done, _ = await asyncio.wait(
                    {receiver, pending}, return_when=asyncio.FIRST_COMPLETED
                )
                if receiver in done:
                    break
                value = pending.result()
                if value is None:
                    await websocket.close(code=1013)
                    break
                await asyncio.wait_for(websocket.send_json(value), SEND_TIMEOUT)
            finally:
                pending.cancel()
                with suppress(asyncio.CancelledError):
                    await pending
    except HTTPException as error:
        with suppress(RuntimeError, WebSocketDisconnect):
            await websocket.close(
                code=(
                    4401
                    if error.status_code == 401
                    else 4403 if error.status_code == 403 else 1013
                )
            )
    except asyncio.TimeoutError:
        if subscriber:
            subscriber.overflow = True
        with suppress(RuntimeError, WebSocketDisconnect):
            await websocket.close(code=1013)
    except (WebSocketDisconnect, OSError, psycopg.Error):
        with suppress(RuntimeError, WebSocketDisconnect):
            await websocket.close(code=1013)
    finally:
        if receiver:
            receiver.cancel()
            with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
                await receiver
        if subscriber:
            gateway.remove(subscriber)


class BoundedStream(StreamingResponse):
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            if getattr(self, "cleanup", None):
                self.cleanup()

    async def stream_response(self, send):
        async def bounded_send(message):
            await asyncio.wait_for(send(message), SEND_TIMEOUT)

        try:
            await super().stream_response(bounded_send)
        except asyncio.TimeoutError:
            if getattr(self, "on_slow", None):
                self.on_slow()
        finally:
            await self.body_iterator.aclose()


@router.get("/stream/sse")
@operation_policy("relationship_scoped")
async def sse_stream(request: Request):
    token = credentials(request)
    user = await asyncio.to_thread(authenticate, token)
    if user is None:
        raise HTTPException(401, "message_stream_authentication_required")
    gateway = request.app.state.messaging_gateway
    subscriber = gateway.subscribe(user)

    async def events():
        try:
            while True:
                value = await next_event(subscriber, token)
                if value is None:
                    return
                yield "data: " + json.dumps(value, separators=(",", ":")) + "\n\n"
        except (HTTPException, psycopg.Error):
            return
        finally:
            gateway.remove(subscriber)

    response = BoundedStream(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )
    response.on_slow = lambda: setattr(subscriber, "overflow", True)
    response.cleanup = lambda: gateway.remove(subscriber)
    return response
