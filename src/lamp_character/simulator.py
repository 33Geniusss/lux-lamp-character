"""Headless PyBullet simulation and RGB rendering for the lamp character."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math

import numpy as np
import pybullet as p
import pybullet_data

from .actions import ACTIONS, HOME_POSE, JOINT_ORDER, Action, Color, Pose, WARM_DIM
from .model_adapter import prepare_pybullet_urdf


@dataclass
class PlaybackState:
    action_name: str
    action: Action
    segment: int
    elapsed: float
    source_pose: Pose
    source_light: Color


class LampSimulator:
    """Owns one isolated PyBullet client and the animated lamp body."""

    def __init__(self, urdf_path: str | Path) -> None:
        self.urdf_path = Path(urdf_path).resolve()
        if not self.urdf_path.is_file():
            raise FileNotFoundError(f"Robot URDF not found: {self.urdf_path}")

        self.client_id = p.connect(p.DIRECT)
        if self.client_id < 0:
            raise RuntimeError("Could not start the PyBullet physics client")

        self._closed = False
        self._sim_accumulator = 0.0
        self._idle_time = 0.0
        self._listen_time = 0.0
        self._physics_step = 1.0 / 120.0
        self.commanded_pose: Pose = dict(HOME_POSE)
        self.light_color: Color = WARM_DIM

        p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=self.client_id)
        p.setPhysicsEngineParameter(
            fixedTimeStep=self._physics_step,
            numSolverIterations=80,
            enableFileCaching=0,
            physicsClientId=self.client_id,
        )
        p.setGravity(0.0, 0.0, -9.81, physicsClientId=self.client_id)

        plane_id = p.loadURDF("plane.urdf", physicsClientId=self.client_id)
        p.changeVisualShape(
            plane_id,
            -1,
            rgbaColor=(0.18, 0.20, 0.24, 1.0),
            specularColor=(0.08, 0.08, 0.08),
            physicsClientId=self.client_id,
        )

        # TinyRenderer has a fixed clear color.  A lightweight visual-only wall
        # gives the character a consistent studio backdrop instead of a bright
        # horizon, without adding collision work to the simulation.
        backdrop_shape = p.createVisualShape(
            p.GEOM_BOX,
            halfExtents=(4.0, 0.035, 2.0),
            rgbaColor=(0.09, 0.11, 0.15, 1.0),
            physicsClientId=self.client_id,
        )
        p.createMultiBody(
            baseMass=0.0,
            baseVisualShapeIndex=backdrop_shape,
            basePosition=(1.10, -1.10, 1.65),
            baseOrientation=p.getQuaternionFromEuler((0.0, 0.0, math.pi / 4.0)),
            physicsClientId=self.client_id,
        )

        self.runtime_urdf_path = prepare_pybullet_urdf(self.urdf_path)
        flags = p.URDF_USE_INERTIA_FROM_FILE | p.URDF_MAINTAIN_LINK_ORDER
        self.robot_id = p.loadURDF(
            str(self.runtime_urdf_path),
            basePosition=(0.0, 0.0, 0.0),
            useFixedBase=True,
            flags=flags,
            physicsClientId=self.client_id,
        )

        self.joint_indices: dict[str, int] = {}
        self.link_indices: dict[str, int] = {}
        self.joint_forces: dict[str, float] = {}
        for joint_index in range(p.getNumJoints(self.robot_id, physicsClientId=self.client_id)):
            info = p.getJointInfo(self.robot_id, joint_index, physicsClientId=self.client_id)
            joint_name = info[1].decode("utf-8")
            link_name = info[12].decode("utf-8")
            self.link_indices[link_name] = joint_index
            if joint_name in JOINT_ORDER:
                self.joint_indices[joint_name] = joint_index
                self.joint_forces[joint_name] = float(info[10])

        missing = set(JOINT_ORDER) - set(self.joint_indices)
        if missing:
            self.close()
            raise ValueError(f"URDF is missing required movable joints: {sorted(missing)}")
        if "light_emitter_link" not in self.link_indices:
            self.close()
            raise ValueError("URDF is missing semantic light_emitter_link")

        for joint_name, target in HOME_POSE.items():
            p.resetJointState(
                self.robot_id,
                self.joint_indices[joint_name],
                targetValue=target,
                physicsClientId=self.client_id,
            )

        self.playback = PlaybackState(
            "idle", ACTIONS["idle"], 0, 0.0, dict(HOME_POSE), WARM_DIM
        )
        self._apply_light(WARM_DIM)
        self._command_pose(HOME_POSE)
        for _ in range(24):
            p.stepSimulation(physicsClientId=self.client_id)

    @property
    def action_name(self) -> str:
        return self.playback.action_name

    @property
    def action_description(self) -> str:
        return self.playback.action.description

    @property
    def joint_count(self) -> int:
        return len(self.joint_indices)

    def play_action(self, action_name: str) -> None:
        if action_name not in ACTIONS:
            raise KeyError(f"Unknown action: {action_name}")
        action = ACTIONS[action_name]
        self.playback = PlaybackState(
            action_name=action_name,
            action=action,
            segment=0,
            elapsed=0.0,
            source_pose=dict(self.commanded_pose),
            source_light=self.light_color,
        )
        if action.idle_motion:
            self._idle_time = 0.0
        if action_name == "listen":
            self._listen_time = 0.0

    def step(self, dt: float) -> None:
        dt = min(max(float(dt), 0.0), 0.1)
        if self.playback.action.idle_motion:
            self._update_idle(dt)
        else:
            self._update_keyframes(dt)

        self._command_pose(self.commanded_pose)
        self._sim_accumulator += dt
        while self._sim_accumulator >= self._physics_step:
            p.stepSimulation(physicsClientId=self.client_id)
            self._sim_accumulator -= self._physics_step

    def _update_idle(self, dt: float) -> None:
        self._idle_time += dt
        breath = math.sin(self._idle_time * 1.55)
        glance = math.sin(self._idle_time * 0.48)
        self.commanded_pose = dict(HOME_POSE)
        self.commanded_pose["shoulder_pitch_joint"] += 0.018 * breath
        self.commanded_pose["elbow_pitch_joint"] -= 0.022 * breath
        self.commanded_pose["neck_yaw_joint"] += 0.045 * glance
        self.commanded_pose["head_pitch_joint"] += 0.018 * breath
        pulse = 0.43 + 0.08 * (0.5 + 0.5 * breath)
        self._apply_light((1.0, 0.72, 0.24, pulse))

    def _update_keyframes(self, dt: float) -> None:
        state = self.playback
        if (
            state.action_name == "listen"
            and state.segment >= len(state.action.keyframes)
        ):
            self._update_listen_sway(dt)
            return
        state.elapsed += dt
        while state.segment < len(state.action.keyframes):
            frame = state.action.keyframes[state.segment]
            if state.elapsed <= frame.duration:
                t = state.elapsed / frame.duration
                eased = t * t * (3.0 - 2.0 * t)
                self.commanded_pose = {
                    name: state.source_pose[name]
                    + (frame.pose[name] - state.source_pose[name]) * eased
                    for name in JOINT_ORDER
                }
                color = tuple(
                    state.source_light[i] + (frame.light[i] - state.source_light[i]) * eased
                    for i in range(4)
                )
                self._apply_light(color)  # type: ignore[arg-type]
                return

            state.elapsed -= frame.duration
            self.commanded_pose = dict(frame.pose)
            self._apply_light(frame.light)
            state.source_pose = dict(frame.pose)
            state.source_light = frame.light
            state.segment += 1

        # Hold the final pose until the next behavior decision.
        state.segment = len(state.action.keyframes)

    def _update_listen_sway(self, dt: float) -> None:
        """Keep the attentive pose alive with a subtle, silent sway."""

        self._listen_time += dt
        sway = math.sin(self._listen_time * 1.35)
        breath = math.sin(self._listen_time * 1.9)
        base_pose = ACTIONS["listen"].keyframes[-1].pose
        self.commanded_pose = dict(base_pose)
        self.commanded_pose["base_yaw_joint"] += 0.025 * sway
        self.commanded_pose["neck_yaw_joint"] -= 0.045 * sway
        self.commanded_pose["shoulder_pitch_joint"] += 0.010 * breath
        self.commanded_pose["head_pitch_joint"] += 0.010 * breath
        blue = ACTIONS["listen"].keyframes[-1].light
        pulse = 0.94 + 0.06 * (0.5 + 0.5 * breath)
        self._apply_light((blue[0], blue[1], blue[2], pulse))

    def _command_pose(self, pose: Pose) -> None:
        for joint_name in JOINT_ORDER:
            p.setJointMotorControl2(
                self.robot_id,
                self.joint_indices[joint_name],
                p.POSITION_CONTROL,
                targetPosition=pose[joint_name],
                force=max(self.joint_forces[joint_name], 0.1),
                positionGain=0.18,
                velocityGain=0.85,
                physicsClientId=self.client_id,
            )

    def _apply_light(self, color: Color) -> None:
        self.light_color = color
        p.changeVisualShape(
            self.robot_id,
            self.link_indices["light_emitter_link"],
            rgbaColor=color,
            specularColor=(1.0, 0.88, 0.48),
            physicsClientId=self.client_id,
        )

    def joint_positions(self) -> dict[str, float]:
        return {
            name: float(
                p.getJointState(
                    self.robot_id, index, physicsClientId=self.client_id
                )[0]
            )
            for name, index in self.joint_indices.items()
        }

    def render(
        self,
        width: int = 800,
        height: int = 640,
        camera_yaw: float = -135.0,
        shadows: bool = True,
    ) -> np.ndarray:
        """Return an RGBA uint8 frame rendered fully on the CPU."""

        width = max(160, int(width))
        height = max(120, int(height))
        view = p.computeViewMatrixFromYawPitchRoll(
            cameraTargetPosition=(0.02, 0.0, 0.34),
            distance=1.08,
            yaw=float(camera_yaw),
            pitch=-13.0,
            roll=0.0,
            upAxisIndex=2,
        )
        projection = p.computeProjectionMatrixFOV(
            fov=46.0,
            aspect=width / height,
            nearVal=0.05,
            farVal=5.0,
        )
        _, _, rgba, _, _ = p.getCameraImage(
            width,
            height,
            viewMatrix=view,
            projectionMatrix=projection,
            renderer=p.ER_TINY_RENDERER,
            shadow=int(shadows),
            lightDirection=(-1.2, -1.0, -2.4),
            lightColor=(1.0, 0.96, 0.88),
            lightDistance=2.0,
            lightAmbientCoeff=0.42,
            lightDiffuseCoeff=0.72,
            lightSpecularCoeff=0.28,
            physicsClientId=self.client_id,
        )
        return np.asarray(rgba, dtype=np.uint8).reshape((height, width, 4)).copy()

    def close(self) -> None:
        if not self._closed and self.client_id >= 0:
            p.disconnect(physicsClientId=self.client_id)
            self._closed = True

    def __enter__(self) -> "LampSimulator":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
