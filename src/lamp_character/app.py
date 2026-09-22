"""PySide6 desktop UI for the PyBullet lamp character."""

from __future__ import annotations

from pathlib import Path
import argparse
from getpass import getpass
import os
import sys
import time
from typing import Callable
from uuid import uuid4

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .audio import CharacterAudioWorker, audio_contract, audio_output_smoke_test
from .actions import (
    ACTIONS,
    JOINT_ORDER,
    action_duration,
    validate_model_motion_sequence,
)
from .camera import CameraWorker, camera_smoke_test
from .engagement import EngagementDecision
from .language import (
    DEFAULT_LANGUAGE_MODEL,
    FALLBACK_REPLY,
    FollowUpObservationRequest,
    FollowUpObservationWorker,
    LanguageModelWorker,
    api_key_configured,
)
from .memory import MemoryStore, SessionMemory, utc_now
from .simulator import LampSimulator
from .speech import (
    DEFAULT_TRANSCRIPTION_MODEL,
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_VOICE,
    SpeechModelWarmupWorker,
    SpeechWorker,
    VoiceReplyWorker,
    speech_input_smoke_test,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_URDF = PROJECT_ROOT / "robot" / "dummy_lamp_5dof.urdf"
DEFAULT_MODEL = PROJECT_ROOT / "models" / "face_landmarker.task"
DEFAULT_MEMORY_FILE = PROJECT_ROOT / "data" / "session_memory.json"
GREETING_STAGE_SECONDS = max(
    action_duration("greet"),
    audio_contract()["greet"],
) + 0.15

ACTION_KEYS = {
    "1": "idle",
    "2": "engage",
    "3": "greet",
    "4": "listen",
    "5": "think",
    "6": "answer",
    "7": "disengage",
}


class LampWindow(QMainWindow):
    def __init__(
        self,
        urdf_path: Path = DEFAULT_URDF,
        render_size: tuple[int, int] = (320, 256),
        render_shadows: bool = False,
        camera_enabled: bool = True,
        camera_index: int = 0,
        model_path: Path = DEFAULT_MODEL,
        speech_enabled: bool = True,
        transcription_model: str = DEFAULT_TRANSCRIPTION_MODEL,
        audio_device: int | None = None,
        language_enabled: bool = True,
        language_model: str = DEFAULT_LANGUAGE_MODEL,
        memory_path: Path = DEFAULT_MEMORY_FILE,
        neural_voice_enabled: bool = True,
        tts_model: str = DEFAULT_TTS_MODEL,
        tts_voice: str = DEFAULT_TTS_VOICE,
        character_audio_enabled: bool = True,
        audio_output_device: int | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Lamp Character - Motion Studio")
        self.resize(1480, 780)
        self.setMinimumSize(1080, 640)

        self.simulator = LampSimulator(urdf_path)
        self.render_size = render_size
        self.render_shadows = render_shadows
        self._last_tick = time.perf_counter()
        self._demo_actions = [name for name in ACTIONS if name != "idle"]
        self._demo_index = 0
        self._demo_active = False
        self._model_action_queue: list[str] = []
        self._model_actions_active = False
        self._model_action_completion: Callable[[], None] | None = None
        self._engaged = False
        self._engagement_locked = False
        self._deferred_engagement_decision: EngagementDecision | None = None
        self.camera_worker: CameraWorker | None = None
        self.speech_enabled = speech_enabled
        self.transcription_model = transcription_model
        self.audio_device = audio_device
        self.speech_worker: SpeechWorker | None = None
        self.reply_worker: VoiceReplyWorker | None = None
        self.speech_model_warmup_worker: SpeechModelWarmupWorker | None = None
        self._local_speech_models_ready = not speech_enabled
        self._reply_audio_completed = False
        self.language_worker: LanguageModelWorker | None = None
        self.follow_up_observation_worker: FollowUpObservationWorker | None = None
        self._speech_handled = False
        self._closing = False
        self.language_enabled = language_enabled
        self.language_model = language_model
        self.neural_voice_enabled = neural_voice_enabled
        self.tts_model = tts_model
        self.tts_voice = tts_voice
        self.character_audio_enabled = character_audio_enabled
        self.audio_output_device = audio_output_device
        self.character_audio_worker: CharacterAudioWorker | None = None
        self._reply_cue = "success"
        self.memory_path = Path(memory_path)
        self.session_memory: SessionMemory | None = None
        self._memory_load_error = ""
        try:
            self.session_memory = MemoryStore(self.memory_path).reset()
        except Exception as error:
            self._memory_load_error = " ".join(str(error).split())[:120]
        self._latest_camera_image: QImage | None = None
        self._camera_frame_serial = 0
        self._follow_up_observation_frame_floor = 0
        self._pending_observation_request: FollowUpObservationRequest | None = None
        self._pending_transcript = ""
        self._pending_reply = FALLBACK_REPLY
        self._stt_started_at: float | None = None
        self._gpt_started_at: float | None = None
        self._tts_started_at: float | None = None
        self._turn_stage_seconds: dict[str, float | None] = {
            "stt": None,
            "gpt": None,
            "tts": None,
        }

        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(18)

        render_frame = QFrame()
        render_frame.setObjectName("renderFrame")
        render_layout = QVBoxLayout(render_frame)
        render_layout.setContentsMargins(0, 0, 0, 0)
        self.render_label = QLabel("Starting PyBullet renderer...")
        self.render_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.render_label.setMinimumSize(560, 480)
        render_layout.addWidget(self.render_label)
        outer.addWidget(render_frame, 1)

        # The camera is an intentionally small picture-in-picture view. It is a
        # child of the simulation frame so the robot remains the central visual.
        camera_frame = QFrame(render_frame)
        camera_frame.setObjectName("cameraFrame")
        camera_frame.setFixedSize(310, 245)
        camera_frame.move(18, 18)
        camera_frame.raise_()
        camera_layout = QVBoxLayout(camera_frame)
        camera_layout.setContentsMargins(8, 8, 8, 8)
        camera_layout.setSpacing(5)
        camera_heading = QLabel("CAMERA · MEDIAPIPE")
        camera_heading.setObjectName("visualTitle")
        camera_layout.addWidget(camera_heading)
        self.camera_label = QLabel("Camera disabled" if not camera_enabled else "Starting camera...")
        self.camera_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera_label.setWordWrap(True)
        camera_layout.addWidget(self.camera_label)

        speech_frame = QFrame(render_frame)
        speech_frame.setObjectName("speechFrame")
        speech_frame.setFixedSize(310, 202)
        speech_frame.move(18, 280)
        speech_frame.raise_()
        speech_layout = QVBoxLayout(speech_frame)
        speech_layout.setContentsMargins(10, 8, 10, 9)
        speech_layout.setSpacing(5)
        speech_heading = QLabel("SPEECH · WHISPER + GPT + KOKORO")
        speech_heading.setObjectName("visualTitle")
        speech_layout.addWidget(speech_heading)
        if not speech_enabled:
            initial_speech_status = "DISABLED"
        else:
            initial_speech_status = "LOADING · LOCAL SPEECH MODELS"
        self.speech_status_label = QLabel(initial_speech_status)
        self.speech_status_label.setObjectName("speechStatus")
        speech_layout.addWidget(self.speech_status_label)
        self.transcript_label = QLabel("Transcript will appear here")
        self.transcript_label.setObjectName("transcript")
        self.transcript_label.setWordWrap(True)
        speech_layout.addWidget(self.transcript_label)
        if self.session_memory is not None:
            initial_memory_status = self._memory_status(self.session_memory)
        else:
            initial_memory_status = "MEMORY ERROR · JSON NOT MODIFIED"
        self.memory_label = QLabel(initial_memory_status)
        self.memory_label.setObjectName("memoryStatus")
        self.memory_label.setToolTip(self._memory_load_error)
        speech_layout.addWidget(self.memory_label)
        self.turn_timing_label = QLabel("TIMING · STT -- · GPT -- · TTS --")
        self.turn_timing_label.setObjectName("timingStatus")
        self.turn_timing_label.setToolTip(
            "STT: transcription · GPT: final text · TTS: time until speech starts"
        )
        speech_layout.addWidget(self.turn_timing_label)
        self.listen_button = QPushButton("Start listening")
        self.listen_button.setObjectName("listenButton")
        self.listen_button.setEnabled(False)
        self.listen_button.clicked.connect(self.toggle_listening)
        speech_layout.addWidget(self.listen_button)

        panel = QFrame()
        panel.setObjectName("controlPanel")
        panel.setFixedWidth(320)
        controls = QVBoxLayout(panel)
        controls.setContentsMargins(20, 20, 20, 20)
        controls.setSpacing(13)

        title = QLabel("LAMP CHARACTER")
        title.setObjectName("title")
        subtitle = QLabel("5-DOF motion studio")
        subtitle.setObjectName("subtitle")
        controls.addWidget(title)
        controls.addWidget(subtitle)

        self.status_label = QLabel("IDLE")
        self.status_label.setObjectName("status")
        controls.addWidget(self.status_label)

        self.description_label = QLabel(ACTIONS["idle"].description)
        self.description_label.setWordWrap(True)
        self.description_label.setObjectName("description")
        controls.addWidget(self.description_label)

        audio_heading = QLabel("CHARACTER AUDIO")
        audio_heading.setObjectName("sectionTitle")
        controls.addWidget(audio_heading)
        self.audio_status_label = QLabel(
            "STARTING LOCAL MUSIC + SFX"
            if character_audio_enabled
            else "MUSIC + SFX DISABLED"
        )
        self.audio_status_label.setObjectName("audioStatus")
        controls.addWidget(self.audio_status_label)

        engagement_heading = QLabel("ENGAGEMENT DETECTION")
        engagement_heading.setObjectName("sectionTitle")
        controls.addWidget(engagement_heading)
        self.engagement_label = QLabel("CAMERA OFF" if not camera_enabled else "STARTING")
        self.engagement_label.setObjectName("engagementStatus")
        controls.addWidget(self.engagement_label)
        self.metrics_label = QLabel("Head -- / --  ·  gaze --  ·  eyes --")
        self.metrics_label.setObjectName("metrics")
        self.metrics_label.setWordWrap(True)
        controls.addWidget(self.metrics_label)
        self.auto_actions = QCheckBox("Automatic engagement actions")
        self.auto_actions.setChecked(True)
        self.auto_actions.setEnabled(camera_enabled)
        controls.addWidget(self.auto_actions)

        button_grid = QGridLayout()
        button_grid.setHorizontalSpacing(8)
        button_grid.setVerticalSpacing(8)
        for index, (key, action_name) in enumerate(ACTION_KEYS.items()):
            action = ACTIONS[action_name]
            button = QPushButton(f"{key}  {action.label}")
            button.clicked.connect(lambda _checked=False, name=action_name: self.play_action(name))
            button_grid.addWidget(button, index // 2, index % 2)
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(lambda name=action_name: self.play_action(name))
        controls.addLayout(button_grid)

        self.demo_button = QPushButton("Run motion demo")
        self.demo_button.setObjectName("demoButton")
        self.demo_button.clicked.connect(self.toggle_demo)
        controls.addWidget(self.demo_button)

        joint_heading = QLabel("LIVE JOINT ANGLES")
        joint_heading.setObjectName("sectionTitle")
        controls.addWidget(joint_heading)
        self.joints_label = QLabel()
        self.joints_label.setObjectName("joints")
        self.joints_label.setMinimumHeight(118)
        self.joints_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        controls.addWidget(self.joints_label)
        controls.addStretch(1)

        footer = QLabel(
            "Every language-model request includes one current camera frame"
        )
        footer.setObjectName("footer")
        footer.setWordWrap(True)
        controls.addWidget(footer)
        outer.addWidget(panel)

        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #11151b; color: #e9edf3; }
            QLabel { background: transparent; }
            #renderFrame, #cameraFrame, #speechFrame { background: #1a2029; border: 1px solid #303947; border-radius: 12px; }
            #controlPanel { background: #181e27; border: 1px solid #303947; border-radius: 12px; }
            #visualTitle { color: #8e99aa; font-size: 11px; font-weight: 700; padding: 3px; }
            #title { color: #f7c862; font-size: 20px; font-weight: 700; letter-spacing: 2px; }
            #subtitle, #footer { color: #8e99aa; font-size: 12px; }
            #status { background: #2b2417; color: #ffd779; border: 1px solid #67552d;
                      border-radius: 7px; padding: 8px 10px; font-weight: 700; }
            #description { color: #c5ceda; min-height: 52px; }
            #sectionTitle { color: #8e99aa; font-size: 11px; font-weight: 700; margin-top: 5px; }
            #engagementStatus { background: #15231e; color: #8ce4b5; border: 1px solid #315a46;
                                border-radius: 7px; padding: 7px 10px; font-weight: 700; }
            #metrics { color: #9da9b8; font-size: 11px; }
            #speechStatus { color: #8ce4b5; font-size: 11px; font-weight: 700; }
            #audioStatus { color: #f0c56b; font-size: 10px; font-weight: 700; }
            #memoryStatus { color: #9da9b8; font-size: 10px; }
            #timingStatus { color: #7fc7dd; font-size: 10px; font-weight: 700; }
            #transcript { color: #d5dce6; font-size: 12px; min-height: 28px; }
            #joints { background: #11151b; border-radius: 7px; color: #bac5d3;
                      padding: 10px; font-family: Consolas, monospace; }
            QPushButton { background: #252d38; border: 1px solid #3a4554; border-radius: 7px;
                          min-height: 28px; padding: 5px 7px; color: #e9edf3; }
            QPushButton:hover { background: #303a48; border-color: #667487; }
            QPushButton:pressed { background: #1d232c; }
            #demoButton { background: #e5ad43; color: #16130d; border: none; font-weight: 700; }
            #listenButton { background: #426da8; border: none; font-weight: 700; }
            """
        )

        self.timer = QTimer(self)
        self.timer.setInterval(66)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

        self.demo_timer = QTimer(self)
        self.demo_timer.setInterval(2300)
        self.demo_timer.timeout.connect(self._advance_demo)
        if self.character_audio_enabled:
            self.character_audio_worker = CharacterAudioWorker(
                output_device=self.audio_output_device,
                parent=self,
            )
            self.character_audio_worker.status_changed.connect(
                self._on_character_audio_status
            )
            self.character_audio_worker.failure.connect(
                self._on_character_audio_failure
            )
            self.character_audio_worker.start()
        self.play_action("idle")

        if camera_enabled:
            self.camera_worker = CameraWorker(camera_index, model_path, self)
            self.camera_worker.frame_ready.connect(self._on_camera_frame)
            self.camera_worker.decision_ready.connect(self._on_engagement_decision)
            self.camera_worker.failure.connect(self._on_camera_failure)
            self.camera_worker.start()

        if self.speech_enabled:
            self._start_speech_model_warmup()

    def _start_speech_model_warmup(self) -> None:
        """Prepare every enabled local speech model without blocking the UI."""

        self._local_speech_models_ready = False
        self.listen_button.setEnabled(False)
        self.listen_button.setText("Loading speech models...")
        self.transcript_label.setText(
            "Loading local Whisper and warming the selected voice..."
        )
        self.speech_model_warmup_worker = SpeechModelWarmupWorker(
            transcription_model=self.transcription_model,
            neural_voice_enabled=self.neural_voice_enabled,
            tts_model=self.tts_model,
            tts_voice=self.tts_voice,
            parent=self,
        )
        self.speech_model_warmup_worker.status_changed.connect(
            self._on_speech_model_warmup_status
        )
        self.speech_model_warmup_worker.ready.connect(
            self._on_speech_model_warmup_ready
        )
        self.speech_model_warmup_worker.failure.connect(
            self._on_speech_model_warmup_failure
        )
        self.speech_model_warmup_worker.start()

    def _on_speech_model_warmup_status(self, status: str) -> None:
        if not self._closing:
            self.speech_status_label.setText(status)

    def _on_speech_model_warmup_ready(self) -> None:
        if self._closing:
            return
        self._local_speech_models_ready = True
        if not api_key_configured():
            status = "READY · LOCAL MODELS · API KEY MISSING"
        elif self.language_enabled:
            status = f"READY · LOCAL MODELS · {self.language_model}"
        else:
            status = "READY · LOCAL MODELS · FIXED REPLY"
        self.speech_status_label.setText(status)
        self.transcript_label.setText("Local speech models are ready")
        self.listen_button.setText("Start listening")
        self.listen_button.setEnabled(True)
        if self._engaged and self.auto_actions.isChecked():
            QTimer.singleShot(100, self._listen_if_engaged)

    def _on_speech_model_warmup_failure(self, message: str) -> None:
        if self._closing:
            return
        self._local_speech_models_ready = False
        self.speech_status_label.setText("LOCAL SPEECH MODEL ERROR")
        self.transcript_label.setText(" ".join(message.split())[:180])
        self.listen_button.setText("Speech unavailable")
        self.listen_button.setEnabled(False)

    def play_action(self, action_name: str) -> None:
        if self._demo_active and action_name not in self._demo_actions:
            self.toggle_demo()
        self.simulator.play_action(action_name)
        action = ACTIONS[action_name]
        self.status_label.setText(action.label.upper())
        self.description_label.setText(action.description)
        self._play_character_audio_for_action(action_name)

    def _play_character_audio_for_action(self, action_name: str) -> None:
        worker = self.character_audio_worker
        if worker is None:
            return
        if action_name == "engage":
            worker.set_suspended(False)
            worker.set_music_active(True)
            worker.play_cue("engage")
        elif action_name == "greet":
            worker.set_suspended(False)
            worker.set_music_active(False)
            worker.play_cue("greet")
        elif action_name == "listen":
            worker.set_music_active(False)
            worker.set_suspended(True)
        elif action_name in {"answer", "nod_yes"}:
            worker.play_cue("success")
        elif action_name == "shake_no":
            worker.play_cue("error")
        elif action_name == "disengage":
            worker.set_music_active(False)
            worker.set_suspended(False)
            worker.play_cue("disengage")
        elif action_name == "idle":
            worker.set_music_active(False)

    def _on_character_audio_status(self, status: str) -> None:
        self.audio_status_label.setText(status)
        self.audio_status_label.setToolTip("")

    def _on_character_audio_failure(self, message: str) -> None:
        summary = " ".join(message.split())[:160]
        self.audio_status_label.setText("LOCAL AUDIO UNAVAILABLE")
        self.audio_status_label.setToolTip(summary)

    def _silence_character_audio(self) -> None:
        if self.character_audio_worker is not None:
            self.character_audio_worker.set_music_active(False)
            self.character_audio_worker.set_suspended(True)

    def _resume_character_audio(self, cue_name: str | None = None) -> None:
        if self.character_audio_worker is not None:
            self.character_audio_worker.set_suspended(False)
            if cue_name is not None:
                self.character_audio_worker.play_cue(cue_name)

    def toggle_demo(self) -> None:
        self._demo_active = not self._demo_active
        if self._demo_active:
            self.demo_button.setText("Stop motion demo")
            self._demo_index = 0
            self.play_action(self._demo_actions[self._demo_index])
            self.demo_timer.start()
        else:
            self.demo_timer.stop()
            self.demo_button.setText("Run motion demo")
            self.play_action("idle")

    def _advance_demo(self) -> None:
        self._demo_index = (self._demo_index + 1) % len(self._demo_actions)
        self.play_action(self._demo_actions[self._demo_index])

    def _on_camera_frame(self, image: QImage) -> None:
        self._latest_camera_image = image.copy()
        self._camera_frame_serial += 1
        self.camera_label.setPixmap(
            QPixmap.fromImage(image).scaled(
                self.camera_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _on_engagement_decision(self, decision: EngagementDecision) -> None:
        observation = decision.observation
        self.metrics_label.setText(
            f"Head {observation.head_yaw_deg:+.0f}° / {observation.head_pitch_deg:+.0f}°  ·  "
            f"gaze {observation.iris_offset:+.2f}  ·  eyes {observation.eye_openness:.2f}"
        )
        if self._engagement_locked:
            self._deferred_engagement_decision = decision
            self.engagement_label.setText(
                f"TURN LOCK · camera {decision.phase} · {observation.reason}"
            )
            return
        self._apply_engagement_decision(decision)

    def _apply_engagement_decision(self, decision: EngagementDecision) -> None:
        """Apply a live or deferred decision to the character state."""

        previous_engaged = self._engaged
        self._engaged = decision.engaged
        self.engagement_label.setText(
            f"{decision.phase} · {decision.observation.reason}"
        )
        if not self.auto_actions.isChecked() or self._model_actions_active:
            return
        transition = decision.transition
        if decision.engaged != previous_engaged:
            transition = "engaged" if decision.engaged else "disengaged"
        if transition == "engaged":
            self._stop_demo()
            self.play_action("engage")
            QTimer.singleShot(1050, self._greet_if_engaged)
        elif transition == "disengaged":
            self._stop_demo()
            if self._speech_is_running():
                self.speech_worker.requestInterruption()
            self.play_action("disengage")
            QTimer.singleShot(1550, self._idle_if_disengaged)

    def _release_engagement_lock(self) -> None:
        """Apply the newest camera state after the spoken reply is complete."""

        self._engagement_locked = False
        deferred = self._deferred_engagement_decision
        self._deferred_engagement_decision = None
        if deferred is not None:
            self._apply_engagement_decision(deferred)

    def _greet_if_engaged(self) -> None:
        if self._engaged and self.auto_actions.isChecked():
            self.play_action("greet")
            QTimer.singleShot(
                round(GREETING_STAGE_SECONDS * 1000),
                self._listen_if_engaged,
            )

    def _listen_if_engaged(self) -> None:
        if (
            self._engaged
            and self.auto_actions.isChecked()
            and self.speech_enabled
            and getattr(self, "_local_speech_models_ready", True)
            and not self._speech_is_running()
            and not self._reply_is_running()
        ):
            self.start_listening()

    def _idle_if_disengaged(self) -> None:
        if not self._engaged and self.auto_actions.isChecked():
            self.play_action("idle")

    def _speech_is_running(self) -> bool:
        return self.speech_worker is not None and self.speech_worker.isRunning()

    def _reply_is_running(self) -> bool:
        return self.reply_worker is not None and self.reply_worker.isRunning()

    def _language_is_running(self) -> bool:
        initial_running = (
            self.language_worker is not None and self.language_worker.isRunning()
        )
        follow_up_observation_running = (
            self.follow_up_observation_worker is not None
            and self.follow_up_observation_worker.isRunning()
        )
        return (
            initial_running
            or follow_up_observation_running
            or self._pending_observation_request is not None
        )

    def toggle_listening(self) -> None:
        if self._speech_is_running():
            self.speech_worker.requestInterruption()
            self.listen_button.setEnabled(False)
            self.listen_button.setText("Stopping...")
            return
        self.start_listening()

    def start_listening(self) -> None:
        if (
            not self.speech_enabled
            or not getattr(self, "_local_speech_models_ready", True)
            or self._speech_is_running()
            or self._reply_is_running()
            or self._language_is_running()
        ):
            return
        self._stop_demo()
        self._silence_character_audio()
        self._speech_handled = False
        self.speech_status_label.setText("PREPARING MICROPHONE")
        self.transcript_label.setText("Preparing microphone...")
        self.listen_button.setText("Stop listening")
        self.speech_worker = SpeechWorker(
            self.transcription_model,
            self.audio_device,
            parent=self,
        )
        self.speech_worker.calibrating.connect(self._on_speech_calibrating)
        self.speech_worker.listening.connect(self._on_speech_listening)
        self.speech_worker.transcribing.connect(self._on_speech_transcribing)
        self.speech_worker.recognized_text.connect(self._on_speech_recognized)
        self.speech_worker.no_speech.connect(self._on_speech_no_speech)
        self.speech_worker.failure.connect(self._on_speech_failure)
        self.speech_worker.finished.connect(self._on_speech_worker_finished)
        self.speech_worker.start()

    def _on_speech_calibrating(self, sample_rate: int) -> None:
        self._silence_character_audio()
        self.play_action("listen")
        self.speech_status_label.setText(
            f"CALIBRATING MICROPHONE · {sample_rate // 1000} kHz"
        )
        self.transcript_label.setText("Measuring room noise. Please wait...")

    def _on_speech_listening(self, sample_rate: int) -> None:
        self._silence_character_audio()
        if self.simulator.action_name != "listen":
            self.play_action("listen")
        self.speech_status_label.setText(f"LISTENING · {sample_rate // 1000} kHz")
        self.transcript_label.setText("Say something...")

    def _on_speech_transcribing(self, model: str) -> None:
        self._turn_stage_seconds = {"stt": None, "gpt": None, "tts": None}
        self._stt_started_at = time.perf_counter()
        self._gpt_started_at = None
        self._tts_started_at = None
        self._update_turn_timing_display()
        self.speech_status_label.setText(f"TRANSCRIBING · {model}")
        self.transcript_label.setText("Processing the recorded utterance...")

    def _on_speech_recognized(self, text: str) -> None:
        now = time.perf_counter()
        if self._stt_started_at is not None:
            self._turn_stage_seconds["stt"] = now - self._stt_started_at
        self._stt_started_at = None
        self._gpt_started_at = now if self.language_enabled else None
        self._update_turn_timing_display()
        self._speech_handled = True
        self._engagement_locked = True
        self._deferred_engagement_decision = None
        self._pending_transcript = text
        self.speech_status_label.setText(
            f"THINKING · {self.language_model} · SCENE CHECK"
        )
        self.transcript_label.setText(f'You: "{text}"')
        self.listen_button.setEnabled(False)
        self.listen_button.setText("Thinking...")
        self.play_action("think")
        if self.language_enabled:
            if self._latest_camera_image is None:
                self._on_language_failure(
                    "No current camera frame; API call was skipped"
                )
                return
            try:
                image_data_url = self._camera_image_data_url(
                    self._latest_camera_image
                )
            except RuntimeError as error:
                self._on_language_failure(f"{error}; API call was skipped")
                return
            observation_id = f"obs-{uuid4().hex[:12]}"
            captured_at = utc_now()
            self.language_worker = LanguageModelWorker(
                text,
                self.memory_path,
                self.language_model,
                image_data_url,
                observation_id,
                captured_at,
                parent=self,
            )
            self.language_worker.reply_ready.connect(self._on_language_reply)
            self.language_worker.follow_up_observation_required.connect(
                self._on_follow_up_observation_required
            )
            self.language_worker.failure.connect(self._on_language_failure)
            self.language_worker.start()
        else:
            self._pending_reply = FALLBACK_REPLY
            self._reply_cue = "success"
            QTimer.singleShot(350, self._begin_voice_reply)

    def _on_follow_up_observation_required(
        self,
        request: FollowUpObservationRequest,
        latency_seconds: float,
    ) -> None:
        self._pending_observation_request = request
        pending_motion_labels = request.pending_motion_labels
        motion_summary = (
            " → ".join(pending_motion_labels)
            if pending_motion_labels
            else "none"
        )
        self.speech_status_label.setText(
            f"PLAN READY · {latency_seconds:.1f}s · MOTION {motion_summary}"
        )
        self.transcript_label.setText(
            f'You: "{self._pending_transcript}"\n'
            f'Plan: {motion_summary}\n'
            f"Camera observation {request.next_observation_number} requested"
        )
        self._start_model_motion_sequence(
            list(pending_motion_labels),
            on_complete=self._capture_follow_up_observation_frame,
        )

    def _on_language_reply(
        self,
        reply: str,
        latency_seconds: float,
        updated_memory: SessionMemory,
        motion_labels: list[str],
    ) -> None:
        self._finish_gpt_timing()
        completed_observation_request = self._pending_observation_request
        self._pending_observation_request = None
        self._pending_reply = reply
        self._reply_cue = "success"
        self.session_memory = updated_memory
        self.memory_label.setText(self._memory_status(updated_memory))
        self.memory_label.setToolTip(updated_memory.conversation_summary)
        display_labels = list(motion_labels)
        if completed_observation_request is not None:
            prior_labels = [
                label
                for decision in completed_observation_request.decision_history
                for label in decision.motion_labels
            ]
            display_labels = [*prior_labels, *display_labels]
        motion_summary = " → ".join(display_labels) if display_labels else "none"
        self.speech_status_label.setText(
            f"REPLY READY · {latency_seconds:.1f}s · MOTION {motion_summary}"
        )
        self.transcript_label.setText(
            f'You: "{self._pending_transcript}"\n'
            f'Motion: {motion_summary}\nLamp: “{reply}”'
        )
        self._start_model_motion_sequence(motion_labels)

    def _start_model_motion_sequence(
        self,
        motion_labels: list[str],
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """Validate and execute model-selected fixed actions before speaking."""

        self._model_action_completion = on_complete or self._begin_voice_reply
        try:
            sequence = validate_model_motion_sequence(motion_labels)
        except ValueError as error:
            self._model_action_queue.clear()
            self._model_actions_active = False
            self.speech_status_label.setText("MOTION REJECTED · SAFE VOICE ONLY")
            self.transcript_label.setToolTip(str(error))
            self._model_action_completion = None
            QTimer.singleShot(100, self._begin_voice_reply)
            return

        self._model_action_queue = list(sequence)
        self._model_actions_active = bool(self._model_action_queue)
        if self._model_actions_active:
            self._play_next_model_motion()
        else:
            self._finish_model_motion_sequence()

    def _play_next_model_motion(self) -> None:
        if self._closing:
            return
        if not self._model_action_queue:
            self._model_actions_active = False
            self._finish_model_motion_sequence()
            return

        action_name = self._model_action_queue.pop(0)
        self.play_action(action_name)
        self.speech_status_label.setText(f"MOVING · {action_name}")
        delay_ms = round((action_duration(action_name) + 0.12) * 1000)
        QTimer.singleShot(delay_ms, self._play_next_model_motion)

    def _finish_model_motion_sequence(self) -> None:
        callback = self._model_action_completion
        self._model_action_completion = None
        if callback is not None and not self._closing:
            QTimer.singleShot(100, callback)

    def _capture_follow_up_observation_frame(self, attempt: int = 0) -> None:
        request = self._pending_observation_request
        if request is None or self._closing:
            return
        if attempt == 0:
            # Mark the first frame boundary only after all first-stage motions
            # finish, then require a later camera delivery.
            self._follow_up_observation_frame_floor = self._camera_frame_serial
            QTimer.singleShot(
                100,
                lambda: self._capture_follow_up_observation_frame(1),
            )
            return
        if self._camera_frame_serial <= self._follow_up_observation_frame_floor:
            if attempt < 20:
                QTimer.singleShot(
                    100,
                    lambda: self._capture_follow_up_observation_frame(attempt + 1),
                )
                return
            self._on_follow_up_observation_failure(
                "No fresh camera frame after movement"
            )
            return
        if self._latest_camera_image is None:
            self._on_follow_up_observation_failure(
                "No camera frame available for the follow-up observation"
            )
            return

        try:
            image_data_url = self._camera_image_data_url(self._latest_camera_image)
        except RuntimeError as error:
            self._on_follow_up_observation_failure(str(error))
            return

        observation_id = f"obs-{uuid4().hex[:12]}"
        captured_at = utc_now()
        self.play_action("think")
        self.speech_status_label.setText(
            f"THINKING · CAMERA OBSERVATION {request.next_observation_number}"
        )
        self.follow_up_observation_worker = FollowUpObservationWorker(
            request,
            self.memory_path,
            self.language_model,
            image_data_url,
            observation_id,
            captured_at,
            parent=self,
        )
        self.follow_up_observation_worker.reply_ready.connect(
            self._on_language_reply
        )
        self.follow_up_observation_worker.follow_up_observation_required.connect(
            self._on_follow_up_observation_required
        )
        self.follow_up_observation_worker.failure.connect(
            self._on_follow_up_observation_failure
        )
        self.follow_up_observation_worker.start()

    def _on_follow_up_observation_failure(self, message: str) -> None:
        self._pending_observation_request = None
        self._pending_reply = FALLBACK_REPLY
        self._reply_cue = "error"
        error_summary = " ".join(message.split())[:140]
        self.speech_status_label.setText("FOLLOW-UP OBSERVATION ERROR · FALLBACK")
        self.transcript_label.setText(
            f'You: "{self._pending_transcript}"\n'
            f'{error_summary}; fallback: “{FALLBACK_REPLY}”'
        )
        self._start_model_motion_sequence([])

    @staticmethod
    def _memory_status(memory: SessionMemory) -> str:
        scene_count = len(memory.scene_memories)
        noun = "scene" if scene_count == 1 else "scenes"
        return f"MEMORY · turn {memory.turn_count} · {scene_count} {noun}"

    @staticmethod
    def _camera_image_data_url(image: QImage) -> str:
        upload_image = image.scaled(
            512,
            512,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        data = QByteArray()
        buffer = QBuffer(data)
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            raise RuntimeError("Could not prepare camera image")
        if not upload_image.save(buffer, "PNG"):
            buffer.close()
            raise RuntimeError("Could not encode camera image")
        buffer.close()
        encoded = bytes(data.toBase64()).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def _on_language_failure(self, message: str) -> None:
        self._finish_gpt_timing()
        self._pending_observation_request = None
        self._model_action_queue.clear()
        self._model_actions_active = False
        self._model_action_completion = None
        self._pending_reply = FALLBACK_REPLY
        self._reply_cue = "error"
        error_summary = " ".join(message.split())[:140]
        self.speech_status_label.setText("LLM ERROR · USING FALLBACK")
        self.transcript_label.setText(
            f'You: "{self._pending_transcript}"\n'
            f"{error_summary}; fallback: “{FALLBACK_REPLY}”"
        )
        QTimer.singleShot(250, self._begin_voice_reply)

    def _begin_voice_reply(self) -> None:
        if self._reply_is_running():
            return
        self._silence_character_audio()
        self.play_action("answer")
        if self.neural_voice_enabled:
            self.speech_status_label.setText("GENERATING · NATURAL VOICE")
        else:
            self.speech_status_label.setText("SPEAKING · LOCAL VOICE")
        self.reply_worker = VoiceReplyWorker(
            self._pending_reply,
            parent=self,
            neural_enabled=self.neural_voice_enabled,
            tts_model=self.tts_model,
            tts_voice=self.tts_voice,
        )
        self._tts_started_at = time.perf_counter()
        self._reply_audio_completed = False
        self.reply_worker.voice_status.connect(self._on_voice_status)
        self.reply_worker.reply_started.connect(self._on_reply_audio_started)
        self.reply_worker.reply_finished.connect(self._on_reply_audio_completed)
        self.reply_worker.failure.connect(self._on_reply_failure)
        self.reply_worker.finished.connect(self._on_reply_worker_exited)
        self.reply_worker.start()

    def _on_voice_status(self, status: str) -> None:
        self.speech_status_label.setText(status)

    def _on_reply_audio_started(self) -> None:
        if self._tts_started_at is not None:
            self._turn_stage_seconds["tts"] = (
                time.perf_counter() - self._tts_started_at
            )
            self._tts_started_at = None
            self._update_turn_timing_display()

    def _finish_gpt_timing(self) -> None:
        if self._gpt_started_at is not None:
            self._turn_stage_seconds["gpt"] = (
                time.perf_counter() - self._gpt_started_at
            )
            self._gpt_started_at = None
            self._update_turn_timing_display()

    def _update_turn_timing_display(self) -> None:
        def formatted(stage: str) -> str:
            seconds = self._turn_stage_seconds[stage]
            return "--" if seconds is None else f"{seconds:.2f}s"

        self.turn_timing_label.setText(
            "TIMING · "
            f"STT {formatted('stt')} · "
            f"GPT {formatted('gpt')} · "
            f"TTS {formatted('tts')}"
        )

    def _on_reply_audio_completed(self) -> None:
        """Record that every TTS chunk reached the end of playback."""

        self._reply_audio_completed = True

    def _on_reply_worker_exited(self) -> None:
        """Resume only after playback succeeded and the audio thread exited."""

        worker_confirmed = (
            self.reply_worker is not None
            and self.reply_worker.playback_completed
        )
        if (
            self._closing
            or not self._reply_audio_completed
            or not worker_confirmed
        ):
            return
        self._on_reply_finished()

    def _on_reply_finished(self) -> None:
        if getattr(self, "_tts_started_at", None) is not None:
            self._on_reply_audio_started()
        elif hasattr(self, "_update_turn_timing_display"):
            self._update_turn_timing_display()
        if "Lamp:" not in self.transcript_label.text():
            self.transcript_label.setText(
                f"{self.transcript_label.text()}\nLamp: “{self._pending_reply}”"
            )
        self._release_engagement_lock()
        if self.auto_actions.isChecked() and not self._engaged:
            self.speech_status_label.setText("READY · WAITING FOR ENGAGEMENT")
            self.listen_button.setText("Start listening")
            self.listen_button.setEnabled(
                self.speech_enabled
                and getattr(self, "_local_speech_models_ready", True)
            )
            return
        self.speech_status_label.setText("RESUMING LISTENING")
        self.listen_button.setText("Preparing microphone...")
        self.listen_button.setEnabled(False)
        self.play_action("idle")
        self._resume_character_audio(self._reply_cue)
        # Wait briefly for the speaker's audio tail to clear before reopening
        # the microphone, preventing the character from recognizing itself.
        QTimer.singleShot(900, self._resume_listening_after_reply)

    def _resume_listening_after_reply(self) -> None:
        if self._closing or not self.speech_enabled:
            return
        if (
            self._speech_is_running()
            or self._reply_is_running()
            or self._language_is_running()
        ):
            QTimer.singleShot(150, self._resume_listening_after_reply)
            return
        self.listen_button.setEnabled(
            self.speech_enabled
            and getattr(self, "_local_speech_models_ready", True)
        )
        self.start_listening()

    def _on_reply_failure(self, message: str) -> None:
        self._reply_audio_completed = False
        self._release_engagement_lock()
        self._resume_character_audio("error")
        self.speech_status_label.setText("VOICE ERROR")
        self.transcript_label.setText(message)
        self.listen_button.setText("Start listening")
        self.listen_button.setEnabled(
            self.speech_enabled
            and getattr(self, "_local_speech_models_ready", True)
        )

    def _on_speech_failure(self, message: str) -> None:
        self._speech_handled = True
        self._resume_character_audio("error")
        self.speech_status_label.setText("MIC ERROR")
        self.transcript_label.setText(message)
        self.listen_button.setText("Start listening")
        self.listen_button.setEnabled(
            self.speech_enabled
            and getattr(self, "_local_speech_models_ready", True)
        )

    def _on_speech_no_speech(self, _message: str) -> None:
        """Treat silence or non-speech as a normal retry, not a mic failure."""

        self._speech_handled = True
        if self._engaged and self.auto_actions.isChecked():
            self.speech_status_label.setText("LISTENING · NO SPEECH, RETRYING")
            self.transcript_label.setText("No speech detected. Listening again...")
            self.listen_button.setText("Preparing microphone...")
            self.listen_button.setEnabled(False)
            QTimer.singleShot(350, self._retry_listening_after_no_speech)
            return
        self._resume_character_audio()
        self.speech_status_label.setText("READY · NO SPEECH DETECTED")
        self.transcript_label.setText("No speech detected")
        self.listen_button.setText("Start listening")
        self.listen_button.setEnabled(
            self.speech_enabled
            and getattr(self, "_local_speech_models_ready", True)
        )

    def _retry_listening_after_no_speech(self) -> None:
        if self._closing or not self.speech_enabled:
            return
        if self._speech_is_running():
            QTimer.singleShot(100, self._retry_listening_after_no_speech)
            return
        if self._engaged and self.auto_actions.isChecked():
            self.listen_button.setEnabled(
                self.speech_enabled
                and getattr(self, "_local_speech_models_ready", True)
            )
            self.start_listening()
            return
        self._resume_character_audio()
        self.speech_status_label.setText("READY")
        self.listen_button.setText("Start listening")
        self.listen_button.setEnabled(
            self.speech_enabled
            and getattr(self, "_local_speech_models_ready", True)
        )

    def _on_speech_worker_finished(self) -> None:
        if not self._speech_handled:
            self._resume_character_audio()
            if self._engaged and self.character_audio_worker is not None:
                self.character_audio_worker.set_music_active(True)
            self.speech_status_label.setText("READY")
            self.transcript_label.setText("Listening stopped")
            self.listen_button.setText("Start listening")
            self.listen_button.setEnabled(
                self.speech_enabled
                and getattr(self, "_local_speech_models_ready", True)
            )

    def _stop_demo(self) -> None:
        if self._demo_active:
            self._demo_active = False
            self.demo_timer.stop()
            self.demo_button.setText("Run motion demo")
            if self.character_audio_worker is not None:
                self.character_audio_worker.set_music_active(False)

    def _on_camera_failure(self, message: str) -> None:
        self.camera_label.setText(f"CAMERA UNAVAILABLE\n\n{message}")
        self.engagement_label.setText("CAMERA ERROR")
        self.metrics_label.setText("Choose another --camera-index or use --no-camera")
        self.auto_actions.setEnabled(False)

    def tick(self) -> None:
        now = time.perf_counter()
        dt = now - self._last_tick
        self._last_tick = now
        self.simulator.step(dt)

        # Match the renderer's aspect ratio to the available main view so the
        # robot scene fills it instead of being letterboxed in the center.
        render_height = self.render_size[1]
        label_height = max(1, self.render_label.height())
        render_width = max(
            64,
            round(render_height * self.render_label.width() / label_height),
        )
        frame = self.simulator.render(
            render_width, render_height, shadows=self.render_shadows
        )
        height, width, _ = frame.shape
        image = QImage(
            frame.data,
            width,
            height,
            frame.strides[0],
            QImage.Format.Format_RGBA8888,
        ).copy()
        pixmap = QPixmap.fromImage(image)
        self.render_label.setPixmap(
            pixmap.scaled(
                self.render_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

        positions = self.simulator.joint_positions()
        lines = []
        short_names = {
            "base_yaw_joint": "base yaw",
            "shoulder_pitch_joint": "shoulder",
            "elbow_pitch_joint": "elbow",
            "neck_yaw_joint": "neck yaw",
            "head_pitch_joint": "head pitch",
        }
        for name in JOINT_ORDER:
            lines.append(f"{short_names[name]:<10} {positions[name]:>+6.2f} rad")
        self.joints_label.setText("\n".join(lines))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API name
        self._closing = True
        self.timer.stop()
        self.demo_timer.stop()
        if (
            self.speech_model_warmup_worker is not None
            and self.speech_model_warmup_worker.isRunning()
        ):
            self.speech_model_warmup_worker.requestInterruption()
            if not self.speech_model_warmup_worker.wait(2500):
                self.speech_model_warmup_worker.finished.connect(self.close)
                event.ignore()
                return
        if self.camera_worker is not None and self.camera_worker.isRunning():
            self.camera_worker.requestInterruption()
            if not self.camera_worker.wait(2500):
                event.ignore()
                return
        if self._speech_is_running():
            self.speech_worker.requestInterruption()
            if not self.speech_worker.wait(2500):
                event.ignore()
                return
        if self._reply_is_running():
            self.reply_worker.requestInterruption()
            if not self.reply_worker.wait(12000):
                event.ignore()
                return
        if (
            self.language_worker is not None
            and self.language_worker.isRunning()
            and not self.language_worker.wait(12000)
        ):
            event.ignore()
            return
        if (
            self.follow_up_observation_worker is not None
            and self.follow_up_observation_worker.isRunning()
            and not self.follow_up_observation_worker.wait(12000)
        ):
            event.ignore()
            return
        if self.character_audio_worker is not None:
            self.character_audio_worker.shutdown()
            if (
                self.character_audio_worker.isRunning()
                and not self.character_audio_worker.wait(2500)
            ):
                event.ignore()
                return
        self.simulator.close()
        event.accept()


def smoke_test(urdf_path: Path) -> int:
    """Exercise loading, all motions, physics stepping, and CPU rendering."""

    with LampSimulator(urdf_path) as simulator:
        for action_name in ACTIONS:
            simulator.play_action(action_name)
            for _ in range(120):
                simulator.step(1.0 / 60.0)
        frame = simulator.render(320, 240)
        if frame.shape != (240, 320, 4) or float(frame[..., :3].std()) < 2.0:
            raise RuntimeError("PyBullet returned an invalid or empty render")
        print(
            f"Smoke test passed: {simulator.joint_count} movable joints, "
            f"{len(ACTIONS)} actions, frame={frame.shape[1]}x{frame.shape[0]}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lamp character PyBullet motion studio")
    parser.add_argument("--urdf", type=Path, default=DEFAULT_URDF)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--no-camera", action="store_true")
    parser.add_argument("--no-speech", action="store_true")
    parser.add_argument("--audio-device", type=int, default=None)
    parser.add_argument(
        "--audio-output-device",
        type=int,
        default=None,
        help="sounddevice output index for local music and sound effects.",
    )
    parser.add_argument(
        "--no-character-audio",
        action="store_true",
        help="Disable local background music and character sound effects.",
    )
    parser.add_argument(
        "--transcription-model",
        default=DEFAULT_TRANSCRIPTION_MODEL,
        help="Local faster-whisper model name or path (default: small).",
    )
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--llm-model", default=DEFAULT_LANGUAGE_MODEL)
    parser.add_argument("--tts-model", default=DEFAULT_TTS_MODEL)
    parser.add_argument("--tts-voice", default=DEFAULT_TTS_VOICE)
    parser.add_argument(
        "--local-voice",
        action="store_true",
        help="Use the operating-system voice instead of local Kokoro speech.",
    )
    parser.add_argument("--memory-file", type=Path, default=DEFAULT_MEMORY_FILE)
    parser.add_argument(
        "--camera-smoke-test",
        action="store_true",
        help="Run three seconds of local webcam inference without opening the GUI.",
    )
    parser.add_argument(
        "--speech-smoke-test",
        action="store_true",
        help="Verify microphone capture without uploading audio.",
    )
    parser.add_argument(
        "--audio-output-smoke-test",
        action="store_true",
        help="Play a short local cue to verify speaker access.",
    )
    parser.add_argument(
        "--screenshot",
        type=Path,
        help="Capture the rendered application window to a PNG and exit.",
    )
    return parser


def configure_api_key_for_gui(*, language_enabled: bool) -> None:
    """Prompt securely for an API key only when the interactive GUI needs one."""

    if not language_enabled or api_key_configured():
        return
    if not sys.stdin.isatty():
        raise RuntimeError(
            "OPENAI_API_KEY is not configured. Set it in the environment or use --no-llm."
        )
    api_key = getpass("OpenAI API key: ").strip()
    if not api_key:
        raise RuntimeError("An OpenAI API key is required unless --no-llm is used.")
    os.environ["OPENAI_API_KEY"] = api_key


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.smoke_test:
        return smoke_test(args.urdf)
    if args.camera_smoke_test:
        return camera_smoke_test(args.camera_index, args.model)
    if args.speech_smoke_test:
        return speech_input_smoke_test(args.audio_device)
    if args.audio_output_smoke_test:
        return audio_output_smoke_test(args.audio_output_device)
    configure_api_key_for_gui(
        language_enabled=not args.no_llm and not bool(args.screenshot)
    )
    app = QApplication(sys.argv if argv is None else [sys.argv[0], *argv])
    app.setApplicationName("Lamp Character Motion Studio")
    window = LampWindow(
        args.urdf,
        render_size=(800, 640) if args.screenshot else (320, 256),
        render_shadows=bool(args.screenshot),
        camera_enabled=not args.no_camera and not bool(args.screenshot),
        camera_index=args.camera_index,
        model_path=args.model,
        speech_enabled=not args.no_speech and not bool(args.screenshot),
        transcription_model=args.transcription_model,
        audio_device=args.audio_device,
        language_enabled=not args.no_llm,
        language_model=args.llm_model,
        memory_path=args.memory_file,
        neural_voice_enabled=not args.local_voice,
        tts_model=args.tts_model,
        tts_voice=args.tts_voice,
        character_audio_enabled=(
            not args.no_character_audio and not bool(args.screenshot)
        ),
        audio_output_device=args.audio_output_device,
    )
    window.show()
    if args.screenshot:
        destination = args.screenshot.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        window.play_action("greet")

        def capture() -> None:
            if not window.grab().save(str(destination), "PNG"):
                print(f"Could not save screenshot: {destination}", file=sys.stderr)
                app.exit(1)
                return
            print(f"Screenshot saved: {destination}")
            window.close()
            app.quit()

        QTimer.singleShot(1100, capture)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
