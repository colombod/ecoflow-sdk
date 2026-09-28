"""A minimal MQTT 3.1.1 broker behaving like EcoFlow's public broker.

EcoFlow rules reproduced (AGENTS.md):
* Quirk 1: about 10 unique client IDs per account per day. The next new ID
  gets 135.
* Quirk 2: one active session per account. A second CONNECT gets 135 and the
  first session keeps running.
* Quirk 3: an empty client ID gets 135.
Refusals are CONNACK return code 5, which paho/aiomqtt report as 135.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, cast

from ecoflow_twin import mqtt_codec as mc
from ecoflow_twin.recording import Recording
from ecoflow_twin.state import DeviceState
from ecoflow_twin.timeline import play

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrokerConfig:
    account: str
    password: str
    speed: float = 20.0
    client_id_limit: int = 10


@dataclass
class BrokerStats:
    connects: int = 0
    refused: list[str] = field(default_factory=list[str])
    client_ids: set[str] = field(default_factory=set[str])


class _Session:
    def __init__(self, writer: asyncio.StreamWriter) -> None:
        self.writer = writer
        self.filters: set[str] = set()
        self.playback: asyncio.Task[None] | None = None

    def wants(self, topic: str) -> bool:
        return any(mc.topic_matches(f, topic) for f in self.filters)

    async def send(self, data: bytes) -> None:
        if self.writer.is_closing():
            return
        self.writer.write(data)
        with contextlib.suppress(ConnectionError):
            await self.writer.drain()


class Broker:
    def __init__(
        self, recording: Recording, state: DeviceState, config: BrokerConfig
    ) -> None:
        self._recording = recording
        self._state = state
        self._config = config
        self._active: _Session | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        self.stats = BrokerStats()

    def quota_topic(self, sn: str) -> str:
        return f"/open/{self._config.account}/{sn}/quota"

    def close_all(self) -> None:
        """Drop every connection (server shutdown)."""
        for writer in list(self._writers):
            writer.close()

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._writers.add(writer)
        session: _Session | None = None
        try:
            first = await asyncio.wait_for(mc.read_packet(reader), timeout=10)
            if first.type != mc.CONNECT:
                raise mc.ProtocolError("first packet must be CONNECT")
            connect = mc.parse_connect(first.body)
            code = self._admit(connect)
            writer.write(mc.connack(code))
            await writer.drain()
            if code != mc.CONNACK_ACCEPTED:
                return
            session = self._active = _Session(writer)
            idle = connect.keepalive * 1.5 if connect.keepalive else None
            while True:
                packet = await asyncio.wait_for(mc.read_packet(reader), timeout=idle)
                if packet.type == mc.DISCONNECT:
                    return
                await self._dispatch(session, packet)
        except (
            asyncio.IncompleteReadError,
            ConnectionError,
            TimeoutError,
            mc.ProtocolError,
        ) as exc:
            _log.debug("twin broker: connection closed (%r)", exc)
        finally:
            if session is not None:
                if session.playback is not None:
                    session.playback.cancel()
                if self._active is session:
                    self._active = None
            self._writers.discard(writer)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    def _admit(self, connect: mc.Connect) -> int:
        self.stats.connects += 1
        if connect.protocol_level != 4:
            return self._refuse(mc.CONNACK_BAD_PROTOCOL, "only MQTT 3.1.1 is supported")
        if (
            connect.username != self._config.account
            or connect.password != self._config.password
        ):
            return self._refuse(mc.CONNACK_BAD_CREDENTIALS, "bad username or password")
        if not connect.client_id:
            return self._refuse(mc.CONNACK_NOT_AUTHORIZED, "empty client id (Quirk 3)")
        if self._active is not None:
            return self._refuse(
                mc.CONNACK_NOT_AUTHORIZED, "account already has a session (Quirk 2)"
            )
        if connect.client_id not in self.stats.client_ids:
            if len(self.stats.client_ids) >= self._config.client_id_limit:
                return self._refuse(
                    mc.CONNACK_NOT_AUTHORIZED, "client-ID quota spent (Quirk 1)"
                )
            self.stats.client_ids.add(connect.client_id)
        return mc.CONNACK_ACCEPTED

    def _refuse(self, code: int, reason: str) -> int:
        self.stats.refused.append(reason)
        _log.info("twin broker refused CONNECT: %s", reason)
        return code

    async def _dispatch(self, session: _Session, packet: mc.Packet) -> None:
        if packet.type == mc.SUBSCRIBE:
            packet_id, subs = mc.parse_subscribe(packet.body)
            session.filters.update(topic for topic, _ in subs)
            await session.send(mc.suback(packet_id, [min(qos, 1) for _, qos in subs]))
            if (
                session.playback is None
            ):  # the device timeline starts on first SUBSCRIBE
                session.playback = asyncio.create_task(self._play(session))
        elif packet.type == mc.UNSUBSCRIBE:
            packet_id, topics = mc.parse_unsubscribe(packet.body)
            session.filters.difference_update(topics)
            await session.send(mc.unsuback(packet_id))
        elif packet.type == mc.PUBLISH:
            pub = mc.parse_publish(packet.flags, packet.body)
            if pub.packet_id is not None:
                await session.send(mc.puback(pub.packet_id))
            await self._on_client_publish(session, pub)
        elif packet.type == mc.PINGREQ:
            await session.send(mc.PINGRESP_PACKET)
        elif packet.type != mc.PUBACK:  # we deliver at QoS 0; tolerate stray acks
            raise mc.ProtocolError(f"unexpected packet type {packet.type}")

    async def _play(self, session: _Session) -> None:
        async for sn, payload in play(self._recording, self._config.speed):
            topic = self.quota_topic(sn)
            if session.wants(topic):
                body = json.dumps(self._state.apply_to_push(sn, payload)).encode()
                await session.send(mc.publish(topic, body))

    async def _on_client_publish(self, session: _Session, pub: mc.Publish) -> None:
        parts = pub.topic.split("/")  # "", "open", account, sn, "set"
        if (
            len(parts) != 5
            or parts[1:3] != ["open", self._config.account]
            or parts[4] != "set"
        ):
            return
        sn = parts[3]
        try:
            raw: Any = json.loads(pub.payload)
        except ValueError:
            return
        if not isinstance(raw, dict):
            return
        command = cast(dict[str, Any], raw)
        push = self._state.apply_command(sn, command)
        if push is None:
            return  # a real device ignores it: no reply at all
        reply_topic = f"/open/{self._config.account}/{sn}/set_reply"
        reply = {
            "id": command.get("id"),
            "version": command.get("version", "1.0"),
            "sn": sn,
            "code": "0",
            "message": "Success",
        }
        if session.wants(reply_topic):
            await session.send(mc.publish(reply_topic, json.dumps(reply).encode()))
        if push and session.wants(self.quota_topic(sn)):
            await session.send(
                mc.publish(self.quota_topic(sn), json.dumps(push).encode())
            )
