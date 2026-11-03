#!/usr/bin/env python3
"""Практическое задание к Главе 05: WebSockets, Connection Manager и Server-Sent Events.

Данный модуль содержит эталонную реализацию архитектурных компонентов:
1. WebSocketConnection: Эмуляция ASGI WebSocket соединения с обработкой disconnect.
2. ConnectionManager: Управление соединениями по комнатам, broadcast и unicast.
3. RedisPubSubBroker: Симуляция шины сообщений для масштабирования WebSockets между воркерами.
4. SSEFormatter: Форматирование событий по спецификации W3C Server-Sent Events.
5. AsyncStreamCollector: Потоковое потребление данных без переполнения памяти.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, AsyncGenerator


class WebSocketDisconnect(Exception):
    """Исключение при разрыве WebSocket соединения."""

    def __init__(self, code: int = 1000) -> None:
        self.code = code
        super().__init__(f"WebSocket disconnected with code {code}")


class MockWebSocket:
    """Эмулятор ASGI WebSocket соединения для тестирования."""

    def __init__(self, client_id: str) -> None:
        self.client_id = client_id
        self.accepted = False
        self.closed = False
        self.close_code: int | None = None
        self.incoming_queue: asyncio.Queue[str] = asyncio.Queue()
        self.sent_messages: list[str] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, data: str) -> None:
        if self.closed:
            raise WebSocketDisconnect(1006)
        self.sent_messages.append(data)

    async def send_json(self, data: Any) -> None:
        await self.send_text(json.dumps(data))

    async def receive_text(self) -> str:
        if self.closed:
            raise WebSocketDisconnect(self.close_code or 1006)
        return await self.incoming_queue.get()

    async def receive_json(self) -> Any:
        raw = await self.receive_text()
        return json.loads(raw)

    async def close(self, code: int = 1000) -> None:
        self.closed = True
        self.close_code = code


class ConnectionManager:
    """Менеджер WebSocket соединений: управление комнатами и рассылками."""

    def __init__(self) -> None:
        # Словарь: room_id -> список подключенных MockWebSocket
        self.active_rooms: dict[str, list[MockWebSocket]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def connect(self, room_id: str, websocket: MockWebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.active_rooms[room_id].append(websocket)

    async def disconnect(self, room_id: str, websocket: MockWebSocket) -> None:
        async with self._lock:
            if websocket in self.active_rooms[room_id]:
                self.active_rooms[room_id].remove(websocket)
            if not self.active_rooms[room_id]:
                self.active_rooms.pop(room_id, None)

    async def broadcast_to_room(self, room_id: str, message: dict[str, Any]) -> int:
        """Широковещательная рассылка по комнате с автоматической чисткой мертвых сокетов."""
        async with self._lock:
            targets = list(self.active_rooms.get(room_id, []))

        dead_sockets: list[MockWebSocket] = []
        sent_count = 0

        for ws in targets:
            try:
                await ws.send_json(message)
                sent_count += 1
            except Exception:
                dead_sockets.append(ws)

        for dead in dead_sockets:
            await self.disconnect(room_id, dead)

        return sent_count


class RedisPubSubBroker:
    """Шина сообщений для распределенной синхронизации между воркерами FastAPI."""

    def __init__(self) -> None:
        # channel_name -> list of subscriber callbacks
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def subscribe(self, channel: str) -> asyncio.Queue[dict[str, Any]]:
        async with self._lock:
            q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
            self._subscribers[channel].append(q)
            return q

    async def unsubscribe(self, channel: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            if q in self._subscribers[channel]:
                self._subscribers[channel].remove(q)
            if not self._subscribers[channel]:
                self._subscribers.pop(channel, None)

    async def publish(self, channel: str, message: dict[str, Any]) -> int:
        async with self._lock:
            subscribers = list(self._subscribers.get(channel, []))

        for q in subscribers:
            await q.put(message)
        return len(subscribers)


@dataclass
class SSEEvent:
    data: str
    event: str | None = None
    event_id: str | int | None = None
    retry_ms: int | None = None


class SSEFormatter:
    """Форматирование сообщений в соответствии со спецификацией W3C Server-Sent Events."""

    @staticmethod
    def format(event: SSEEvent) -> str:
        lines: list[str] = []
        if event.event:
            lines.append(f"event: {event.event}")
        if event.event_id is not None:
            lines.append(f"id: {event.event_id}")
        if event.retry_ms is not None:
            lines.append(f"retry: {event.retry_ms}")

        # По спецификации data может быть многострочной (каждая строка с префиксом data: )
        for data_line in event.data.split("\n"):
            lines.append(f"data: {data_line}")

        # Завершается обязательным двойным переводом строки
        return "\n".join(lines) + "\n\n"


async def mock_llm_stream(text: str) -> AsyncGenerator[str, None]:
    """Генератор посимвольного/пословного стриминга ответа LLM."""
    words = text.split(" ")
    for idx, word in enumerate(words):
        await asyncio.sleep(0.01)
        suffix = " " if idx < len(words) - 1 else ""
        yield SSEFormatter.format(
            SSEEvent(
                data=json.dumps({"token": word + suffix, "index": idx}),
                event="token",
                event_id=idx,
            )
        )
    yield SSEFormatter.format(SSEEvent(data="[DONE]", event="finish"))


# ---------------------------------------------------------------------------
# Модульные тесты
# ---------------------------------------------------------------------------
import unittest


class TestWebSocketsAndSSE(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.manager = ConnectionManager()
        self.broker = RedisPubSubBroker()

    async def test_connection_manager_broadcast(self) -> None:
        """Рассылка сообщений участникам комнаты."""
        ws1 = MockWebSocket("client_1")
        ws2 = MockWebSocket("client_2")
        ws3 = MockWebSocket("client_3")

        # Клиенты 1 и 2 в комнате "room_A", клиент 3 в "room_B"
        await self.manager.connect("room_A", ws1)
        await self.manager.connect("room_A", ws2)
        await self.manager.connect("room_B", ws3)

        sent = await self.manager.broadcast_to_room("room_A", {"text": "Привет всем в комнате А!"})
        self.assertEqual(sent, 2)

        self.assertEqual(len(ws1.sent_messages), 1)
        self.assertEqual(len(ws2.sent_messages), 1)
        self.assertEqual(len(ws3.sent_messages), 0)

        msg = json.loads(ws1.sent_messages[0])
        self.assertEqual(msg["text"], "Привет всем в комнате А!")

    async def test_connection_manager_dead_socket_cleanup(self) -> None:
        """Автоматическое удаление закрытого сокета при рассылке."""
        ws_alive = MockWebSocket("alive")
        ws_dead = MockWebSocket("dead")

        await self.manager.connect("lobby", ws_alive)
        await self.manager.connect("lobby", ws_dead)

        # Симулируем разрыв сокета у ws_dead
        await ws_dead.close(code=1001)

        # Рассылаем сообщение
        await self.manager.broadcast_to_room("lobby", {"ping": "pong"})

        # Сокет ws_dead должен быть автоматически отписан из активных
        self.assertNotIn(ws_dead, self.manager.active_rooms.get("lobby", []))
        self.assertIn(ws_alive, self.manager.active_rooms["lobby"])

    async def test_pubsub_broker_inter_worker_sync(self) -> None:
        """Синхронизация нескольких воркеров через Pub/Sub шину."""
        sub_queue_worker1 = await self.broker.subscribe("chat:tech")
        sub_queue_worker2 = await self.broker.subscribe("chat:tech")

        # Воркер 3 публикует сообщение
        delivered = await self.broker.publish("chat:tech", {"event": "new_post", "id": 101})
        self.assertEqual(delivered, 2)

        msg1 = await sub_queue_worker1.get()
        msg2 = await sub_queue_worker2.get()

        self.assertEqual(msg1, msg2)
        self.assertEqual(msg1["id"], 101)

        await self.broker.unsubscribe("chat:tech", sub_queue_worker1)
        await self.broker.unsubscribe("chat:tech", sub_queue_worker2)

    def test_sse_formatter_structure(self) -> None:
        """Проверка строгого соответствия стандарту SSE."""
        event = SSEEvent(
            event="message",
            event_id=42,
            retry_ms=3000,
            data="Первая строка\nВторая строка",
        )
        formatted = SSEFormatter.format(event)
        expected = (
            "event: message\n"
            "id: 42\n"
            "retry: 3000\n"
            "data: Первая строка\n"
            "data: Вторая строка\n\n"
        )
        self.assertEqual(formatted, expected)

    async def test_llm_streaming_generation(self) -> None:
        """Потоковое получение чанков ответа LLM."""
        chunks: list[str] = []
        async for chunk in mock_llm_stream("FastAPI Realtime Streaming"):
            chunks.append(chunk)

        # 3 слова + 1 завершающий фрейм [DONE]
        self.assertEqual(len(chunks), 4)
        self.assertIn("event: token", chunks[0])
        self.assertIn("FastAPI ", chunks[0])
        self.assertIn("event: finish", chunks[-1])
        self.assertIn("[DONE]", chunks[-1])


if __name__ == "__main__":
    unittest.main()
