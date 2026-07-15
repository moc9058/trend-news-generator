"""Research Chat HTTP surface, mounted on pipeline-api (design doc 11 §5.4).

Like the rest of pipeline-api there is no app-level auth: Cloud Run IAM does it
(admin-sa holds run.invoker), and `requestedBy` arrives from the admin's IAP
header. Reads stay in the admin UI via Firestore direct — only these
state-changing calls come here.

The streaming endpoint runs the graph on a worker thread and drains a queue on
the response thread. Two reasons, both load-bearing:
  - the graph is sync (FastAPI would otherwise block its threadpool worker for
    minutes), and
  - a disconnected client must not kill the run. The worker keeps going and
    writes the final message to Firestore, so a reload shows a complete answer.
"""

import json
import queue
import threading
from datetime import datetime, timezone
from typing import Iterator, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.chat import prompts
from app.chat.graph import build_graph, make_context
from app.chat.schemas import (
    ChatDepth,
    ChatMessage,
    ChatMessageStatus,
    ChatMode,
    ChatThread,
    ChatTitle,
    ChatUsage,
)
from app.config import get_settings
from app.repo import chat as chat_repo
from app.research import llm
from app.utils.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api/chat")

# Firestore allows ~1 write/s/document; the assistant message is rewritten as it
# streams, so incremental saves are throttled well clear of that.
CONTENT_FLUSH_SECONDS = 1.5
# Cancel is a Firestore read; polling it per token would be absurd.
CANCEL_POLL_SECONDS = 5.0
# How long the response generator waits before emitting an SSE keep-alive.
PING_SECONDS = 15.0

_SENTINEL = object()


class ChatMessageRequest(BaseModel):
    threadId: Optional[str] = None
    content: str
    mode: str = ChatMode.chat.value
    depth: str = ChatDepth.quick.value
    requestedBy: str = ""
    locale: Optional[str] = None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class _CancelPoller:
    """Throttled view of chatThreads/{id}.cancelRequested."""

    def __init__(self, thread_id: str, interval: float = CANCEL_POLL_SECONDS):
        self._thread_id, self._interval = thread_id, interval
        self._last_check = 0.0
        self._cancelled = False

    def __call__(self) -> bool:
        if self._cancelled:
            return True
        now = _monotonic()
        if now - self._last_check < self._interval:
            return False
        self._last_check = now
        try:
            self._cancelled = chat_repo.is_cancelled(self._thread_id)
        except Exception as exc:  # noqa: BLE001 — a failed poll must not end the run
            log.warning("cancel poll failed", extra={"fields": {
                "thread": self._thread_id, "error": str(exc)}})
        return self._cancelled


def _monotonic() -> float:
    import time
    return time.monotonic()


@router.post("/messages")
def post_message(req: ChatMessageRequest) -> StreamingResponse:
    if not req.content.strip():
        raise HTTPException(400, "content is required")
    if req.mode not in (ChatMode.chat.value, ChatMode.research.value):
        raise HTTPException(400, f"unknown mode {req.mode}")
    if req.depth not in (ChatDepth.quick.value, ChatDepth.deep.value):
        raise HTTPException(400, f"unknown depth {req.depth}")

    settings = get_settings()
    thread_id = req.threadId or ""
    if thread_id:
        if chat_repo.get_thread(thread_id) is None:
            raise HTTPException(404, "chat thread not found")
        # A new message clears a cancel left over from the previous one.
        chat_repo.clear_cancel(thread_id)
    else:
        thread_id = chat_repo.create_thread(ChatThread(requestedBy=req.requestedBy))

    is_research = req.mode == ChatMode.research.value
    depth = req.depth if is_research else ChatDepth.quick.value
    history = chat_repo.recent_history(thread_id, settings.chat_history_max_messages)

    user_message_id = chat_repo.append_message(thread_id, ChatMessage(
        role="user", mode=req.mode, depth=depth if is_research else None,
        content=req.content, status=ChatMessageStatus.complete.value))
    assistant_message_id = chat_repo.append_message(thread_id, ChatMessage(
        role="assistant", mode=req.mode, depth=depth if is_research else None,
        content="", status=ChatMessageStatus.streaming.value))

    events: queue.Queue = queue.Queue()
    worker = threading.Thread(
        target=_run_graph, name=f"chat-{thread_id}", daemon=True,
        kwargs={"req": req, "thread_id": thread_id, "depth": depth,
                "history": history, "assistant_message_id": assistant_message_id,
                "events": events})
    worker.start()

    meta = {"threadId": thread_id, "userMessageId": user_message_id,
            "assistantMessageId": assistant_message_id}
    return StreamingResponse(
        _drain(events, meta), media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Cloud Run's proxy buffers by default, which would hold the whole
            # answer back until the run finished — defeating streaming entirely.
            "X-Accel-Buffering": "no",
        })


def _drain(events: queue.Queue, meta: dict) -> Iterator[str]:
    """Turn the worker's queue into an SSE body. Never raises into the response:
    the worker owns persistence, so a broken pipe here loses nothing."""
    yield _sse("meta", meta)
    while True:
        try:
            item = events.get(timeout=PING_SECONDS)
        except queue.Empty:
            # An SSE comment: keeps proxies and the browser from timing out a
            # quiet stretch (a long fetch, a slow model).
            yield ": ping\n\n"
            continue
        if item is _SENTINEL:
            return
        yield _sse(item["event"], item["data"])


def _run_graph(*, req: ChatMessageRequest, thread_id: str, depth: str,
               history: list[dict], assistant_message_id: str,
               events: queue.Queue) -> None:
    """Worker thread: run the graph, stream out, persist the result.

    EVERYTHING is inside try/finally, including resource setup. If this thread
    dies without putting the sentinel, `_drain` pings forever and the client's
    request never ends — so the sentinel is a hard guarantee, not a happy path.
    """
    buffer: list[str] = []
    sources: list = []
    status = ChatMessageStatus.complete.value
    error = ""
    ctx = None

    try:
        cancel = _CancelPoller(thread_id)
        registry, fetcher = ({}, None)
        if req.mode == ChatMode.research.value:
            # Constructing these can fail (e.g. the grounded connector wants a
            # Gemini key) — inside the try so it surfaces as a failed message
            # rather than a hung request.
            from app.research.fetch.fetcher import Fetcher
            from app.research.sources.base import build_registry
            registry, fetcher = build_registry(), Fetcher()

        ctx = make_context(depth=depth, cancel_check=cancel, registry=registry,
                           fetcher=fetcher)
        state = {
            "thread_id": thread_id, "assistant_message_id": assistant_message_id,
            "mode": req.mode, "depth": depth, "history": history,
            "user_input": req.content, "loops": 0, "stop_reason": "",
        }
        last_flush = _monotonic()

        graph = build_graph()
        for chunk in graph.stream(
                state, context=ctx, stream_mode="custom",
                config={"run_name": "research-chat",
                        "metadata": {"threadId": thread_id, "mode": req.mode,
                                     "depth": depth}}):
            kind, data = chunk.get("type"), chunk.get("data", {})
            if kind == "token":
                buffer.append(data.get("delta", ""))
                events.put({"event": "token", "data": data})
                now = _monotonic()
                if now - last_flush >= CONTENT_FLUSH_SECONDS:
                    last_flush = now
                    _safe_update(thread_id, assistant_message_id,
                                 {"content": "".join(buffer)})
            elif kind == "sources":
                sources = data.get("sources", [])
                events.put({"event": "sources", "data": data})
            elif kind == "status":
                events.put({"event": "status", "data": data})
        if cancel():
            status = ChatMessageStatus.cancelled.value
    except BaseException as exc:  # noqa: BLE001 — never leave a message streaming
        log.exception("chat run failed", extra={"fields": {
            "thread": thread_id, "message": assistant_message_id}})
        status = ChatMessageStatus.error.value
        error = str(exc)[:500] or type(exc).__name__
    finally:
        usage = _finalise(thread_id, assistant_message_id, req, ctx, buffer,
                          sources, status, error)
        if status == ChatMessageStatus.error.value:
            events.put({"event": "error", "data": {
                "message": error, "messageId": assistant_message_id}})
        else:
            events.put({"event": "usage", "data": usage.model_dump()})
            events.put({"event": "done", "data": {
                "messageId": assistant_message_id, "status": status}})
        events.put(_SENTINEL)


def _finalise(thread_id: str, assistant_message_id: str, req: ChatMessageRequest,
              ctx, buffer: list[str], sources: list, status: str,
              error: str) -> ChatUsage:
    """Terminal write. Best-effort: by here the answer is already streamed, and
    raising would only cost us the sentinel."""
    cost = ctx.budget.state.usdSpent if ctx is not None else 0.0
    usage = _sum_usage(ctx.llm_events if ctx is not None else [], cost)
    try:
        chat_repo.finish_message(
            thread_id, assistant_message_id, content="".join(buffer),
            status=status, sources=sources, usage=usage.model_dump(), error=error)
        if cost:
            chat_repo.add_thread_cost(thread_id, cost)
            chat_repo.add_usage(cost)
        if ctx is not None and status == ChatMessageStatus.complete.value:
            _maybe_title(thread_id, req.content, ctx)
    except Exception:  # noqa: BLE001 — nothing left to salvage; log and move on
        log.exception("chat persist failed", extra={"fields": {"thread": thread_id}})
    return usage


def _sum_usage(llm_events: list, cost: float) -> ChatUsage:
    return ChatUsage(
        costUsd=round(cost, 6),
        promptTokens=sum(int(e.get("tokensIn") or 0) for e in llm_events),
        completionTokens=sum(int(e.get("tokensOut") or 0) for e in llm_events),
        model=(llm_events[-1].get("model", "") if llm_events else ""))


def _safe_update(thread_id: str, message_id: str, fields: dict) -> None:
    """An incremental save is best-effort — losing one costs nothing, since the
    terminal write carries the whole answer."""
    try:
        chat_repo.update_message(thread_id, message_id, fields)
    except Exception as exc:  # noqa: BLE001
        log.warning("chat incremental save failed", extra={"fields": {
            "thread": thread_id, "error": str(exc)}})


def _maybe_title(thread_id: str, first_question: str, ctx) -> None:
    """Name a thread from its opening question, once."""
    thread = chat_repo.get_thread(thread_id)
    if thread is None or thread.title:
        return
    try:
        result: ChatTitle = llm.structured(
            ChatTitle, get_settings().chat_fast_model, prompts.TITLE_SYSTEM,
            prompts.TITLE_USER.format(question=first_question[:1000]),
            budget=ctx.budget, run_id=thread_id, phase="title", actor="titler",
            prompt_version=prompts.PROMPT_VERSION, event_sink=ctx.llm_events.append)
    except Exception as exc:  # noqa: BLE001 — an untitled thread is not a failure
        log.warning("chat title failed", extra={"fields": {"error": str(exc)}})
        return
    if result.title:
        chat_repo.update_thread(thread_id, {"title": result.title[:80]})


@router.post("/threads/{thread_id}/cancel", status_code=202)
def cancel_thread(thread_id: str) -> dict:
    if not chat_repo.request_cancel(thread_id):
        raise HTTPException(404, "chat thread not found")
    return {"ok": True}
