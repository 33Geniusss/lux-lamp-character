"""Persistent, validated memory for the current robot conversation."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .actions import MotionLabel


def utc_now() -> str:
    """Return a stable ISO-8601 UTC timestamp."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SceneMemory(BaseModel):
    """One visual observation retained as compact text, never as an image."""

    model_config = ConfigDict(extra="forbid")

    observation_id: str = Field(min_length=1, max_length=80)
    observed_at: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=600)
    objects: list[str] = Field(default_factory=list, max_length=20)


class SessionMemory(BaseModel):
    """Complete application-owned memory sent with every model request."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    session_id: str = Field(min_length=1, max_length=80)
    conversation_summary: str = Field(min_length=1, max_length=3000)
    scene_memories: list[SceneMemory] = Field(default_factory=list, max_length=20)
    turn_count: int = Field(default=0, ge=0)
    updated_at: str = Field(min_length=1, max_length=64)

    @classmethod
    def empty(cls) -> "SessionMemory":
        return cls(
            session_id=f"session-{uuid4().hex}",
            conversation_summary="No conversation yet.",
            updated_at=utc_now(),
        )


class ModelTurn(BaseModel):
    """Initial reply and motion plan with an optional follow-up camera request."""

    model_config = ConfigDict(extra="forbid")

    reply: str = Field(min_length=1)
    motion_labels: list[MotionLabel] = Field(default_factory=list, max_length=1)
    request_another_observation: bool = False
    updated_memory: SessionMemory


class FollowUpObservationTurn(BaseModel):
    """Reply and motions chosen from a fresh post-movement camera frame."""

    model_config = ConfigDict(extra="forbid")

    reply: str = Field(min_length=1)
    motion_labels: list[MotionLabel] = Field(default_factory=list, max_length=1)
    request_another_observation: bool = False
    updated_memory: SessionMemory


class MemoryStore:
    """Load and atomically replace the on-disk session-memory document."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> SessionMemory:
        if not self.path.exists():
            memory = SessionMemory.empty()
            self.replace(memory)
            return memory
        with self.path.open("r", encoding="utf-8") as handle:
            return SessionMemory.model_validate(json.load(handle))

    def reset(self) -> SessionMemory:
        """Start a new session and atomically discard any prior memory."""

        memory = SessionMemory.empty()
        self.replace(memory)
        return memory

    def replace(self, memory: SessionMemory) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.tmp")
        payload = memory.model_dump_json(indent=2)
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)


def normalize_memory_update(
    previous: SessionMemory,
    proposed: SessionMemory,
    visual_observation_provided: bool,
    observation_id: str | None = None,
    captured_at: str | None = None,
) -> SessionMemory:
    """Keep application metadata authoritative and prevent invented vision."""

    if visual_observation_provided:
        by_id = {item.observation_id: item for item in previous.scene_memories}
        for item in proposed.scene_memories:
            if observation_id is not None and item.observation_id != observation_id:
                continue
            if observation_id is not None and captured_at is not None:
                item = item.model_copy(update={"observed_at": captured_at})
            by_id[item.observation_id] = item
        scenes = list(by_id.values())[-20:]
    else:
        scenes = previous.scene_memories

    return SessionMemory(
        version=previous.version,
        session_id=previous.session_id,
        conversation_summary=proposed.conversation_summary,
        scene_memories=scenes,
        turn_count=previous.turn_count + 1,
        updated_at=utc_now(),
    )
