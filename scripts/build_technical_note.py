"""Build the two-page Lux technical note PDF."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "TECHNICAL_NOTE.pdf"
ROBOT_IMAGE = ROOT / "robot" / "dummy-lamp.png"

PAGE_W, PAGE_H = A4
MARGIN = 42
INK = HexColor("#14202B")
MUTED = HexColor("#526575")
NAVY = HexColor("#102A43")
TEAL = HexColor("#0C8791")
TEAL_DARK = HexColor("#09646C")
AMBER = HexColor("#F2A93B")
PALE_TEAL = HexColor("#EAF6F5")
PALE_BLUE = HexColor("#EEF4F8")
PALE_AMBER = HexColor("#FFF5E4")
LINE = HexColor("#D6E0E7")
SOFT = HexColor("#F7F9FB")
GREEN = HexColor("#23856D")


def wrap_lines(text: str, font: str, size: float, width: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and stringWidth(candidate, font, size) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def paragraph(
    pdf: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    *,
    font: str = "Helvetica",
    size: float = 8.4,
    leading: float = 11.1,
    color=INK,
) -> float:
    pdf.setFont(font, size)
    pdf.setFillColor(color)
    for raw in text.split("\n"):
        lines = wrap_lines(raw, font, size, width) if raw else [""]
        for line in lines:
            pdf.drawString(x, y, line)
            y -= leading
    return y


def label(pdf: canvas.Canvas, text: str, x: float, y: float, color=TEAL) -> None:
    pdf.setFillColor(color)
    pdf.setFont("Helvetica-Bold", 7.2)
    pdf.drawString(x, y, text.upper())


def section_title(pdf: canvas.Canvas, text: str, x: float, y: float) -> float:
    pdf.setFillColor(TEAL)
    pdf.roundRect(x, y - 1, 4, 15, 2, fill=1, stroke=0)
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(x + 11, y + 1, text)
    return y - 17


def bullet(
    pdf: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    *,
    size: float = 8.1,
    leading: float = 10.6,
    color=INK,
) -> float:
    pdf.setFillColor(AMBER)
    pdf.circle(x + 2.5, y + 2.4, 1.9, fill=1, stroke=0)
    return paragraph(
        pdf,
        text,
        x + 11,
        y,
        width - 11,
        size=size,
        leading=leading,
        color=color,
    ) - 3


def rounded_card(pdf: canvas.Canvas, x: float, y: float, w: float, h: float, fill) -> None:
    pdf.setFillColor(fill)
    pdf.setStrokeColor(LINE)
    pdf.setLineWidth(0.55)
    pdf.roundRect(x, y, w, h, 8, fill=1, stroke=1)


def arrow(pdf: canvas.Canvas, x1: float, y1: float, x2: float, y2: float) -> None:
    pdf.setStrokeColor(TEAL_DARK)
    pdf.setFillColor(TEAL_DARK)
    pdf.setLineWidth(1.15)
    pdf.line(x1, y1, x2, y2)
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 > x1 else -1
        pdf.line(x2, y2, x2 - direction * 5, y2 + 3)
        pdf.line(x2, y2, x2 - direction * 5, y2 - 3)
    else:
        direction = 1 if y2 > y1 else -1
        pdf.line(x2, y2, x2 + 3, y2 - direction * 5)
        pdf.line(x2, y2, x2 - 3, y2 - direction * 5)


def node(
    pdf: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    heading: str,
    detail: str,
    fill=white,
) -> None:
    pdf.setFillColor(fill)
    pdf.setStrokeColor(LINE)
    pdf.setLineWidth(0.65)
    pdf.roundRect(x, y, w, h, 6, fill=1, stroke=1)
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 7.4)
    pdf.drawCentredString(x + w / 2, y + h - 13, heading)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 6.4)
    for index, line in enumerate(wrap_lines(detail, "Helvetica", 6.4, w - 10)[:2]):
        pdf.drawCentredString(x + w / 2, y + h - 24 - index * 8, line)


def page_header(pdf: canvas.Canvas, page: int) -> None:
    pdf.setFillColor(NAVY)
    pdf.rect(0, PAGE_H - 104, PAGE_W, 104, fill=1, stroke=0)
    pdf.setFillColor(AMBER)
    pdf.rect(0, PAGE_H - 108, PAGE_W, 4, fill=1, stroke=0)
    if page == 1:
        label(pdf, "Software / CV Character Robot Challenge", MARGIN, PAGE_H - 27, AMBER)
        pdf.setFillColor(white)
        pdf.setFont("Helvetica-Bold", 25)
        pdf.drawString(MARGIN, PAGE_H - 57, "LUX TECHNICAL NOTE")
        pdf.setFillColor(HexColor("#D9E8F1"))
        pdf.setFont("Helvetica", 9.3)
        pdf.drawString(
            MARGIN,
            PAGE_H - 79,
            "CPU-first expressive lamp character | Hybrid local speech + cloud vision-language",
        )
        pdf.setFillColor(HexColor("#244862"))
        pdf.roundRect(PAGE_W - 105, PAGE_H - 88, 63, 56, 8, fill=1, stroke=0)
        if ROBOT_IMAGE.exists():
            pdf.drawImage(
                str(ROBOT_IMAGE),
                PAGE_W - 101,
                PAGE_H - 85,
                width=55,
                height=50,
                preserveAspectRatio=True,
                anchor="c",
                mask="auto",
            )
    else:
        label(pdf, "Lux technical note", MARGIN, PAGE_H - 31, AMBER)
        pdf.setFillColor(white)
        pdf.setFont("Helvetica-Bold", 20)
        pdf.drawString(MARGIN, PAGE_H - 61, "IMPLEMENTATION, EVIDENCE & LIMITS")
        pdf.setFillColor(HexColor("#D9E8F1"))
        pdf.setFont("Helvetica", 8.8)
        pdf.drawString(MARGIN, PAGE_H - 81, "Measured on the development laptop; target-hardware gaps are called out explicitly.")


def footer(pdf: canvas.Canvas, page: int) -> None:
    y = 24
    pdf.setStrokeColor(LINE)
    pdf.line(MARGIN, y + 11, PAGE_W - MARGIN, y + 11)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 6.8)
    pdf.drawString(MARGIN, y, "github.com/33Geniusss/lux-lamp-character")
    pdf.linkURL(
        "https://github.com/33Geniusss/lux-lamp-character",
        (MARGIN, y - 2, MARGIN + 190, y + 8),
        relative=0,
    )
    pdf.drawRightString(PAGE_W - MARGIN, y, f"20 Sep 2026  |  {page} / 2")


def architecture(pdf: canvas.Canvas, y: float) -> float:
    x0 = MARGIN
    gap = 8
    w = (PAGE_W - 2 * MARGIN - 4 * gap) / 5
    h = 50
    items = [
        ("SENSORS", "camera + microphone", PALE_BLUE),
        ("LOCAL PERCEPTION", "MediaPipe + Whisper", PALE_TEAL),
        ("TURN COORDINATOR", "Qt state machine", PALE_AMBER),
        ("GPT RESPONSES", "image + goal + memory", PALE_BLUE),
        ("VALIDATED RESULT", "reply + one action", PALE_TEAL),
    ]
    xs = [x0 + i * (w + gap) for i in range(5)]
    for i, (heading, detail, fill) in enumerate(items):
        node(pdf, xs[i], y, w, h, heading, detail, fill)
        if i < 4:
            arrow(pdf, xs[i] + w + 1, y + h / 2, xs[i + 1] - 1, y + h / 2)

    lower_y = y - 63
    lower_w = 142
    lower_gap = 10
    lower_start = MARGIN + 65
    lower_items = [
        (lower_start, "FIXED MOTION", "PyBullet keyframes"),
        (lower_start + lower_w + lower_gap, "LOCAL VOICE", "Kokoro -> speaker"),
        (lower_start + 2 * (lower_w + lower_gap), "SESSION MEMORY", "atomic JSON replace"),
    ]
    for x, heading, detail in lower_items:
        node(pdf, x, lower_y, lower_w, 40, heading, detail, white)
    result_x = xs[4] + w / 2
    bus_y = y - 13
    centers = [item[0] + lower_w / 2 for item in lower_items]
    pdf.setStrokeColor(TEAL_DARK)
    pdf.setLineWidth(1.15)
    pdf.line(result_x, y, result_x, bus_y)
    pdf.line(centers[0], bus_y, result_x, bus_y)
    for center in centers:
        arrow(pdf, center, bus_y, center, lower_y + 42)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica-Oblique", 6.6)
    pdf.drawString(MARGIN, lower_y - 11, "All model outputs cross a schema and whitelist boundary before execution or storage.")
    return lower_y - 28


def draw_page_one(pdf: canvas.Canvas) -> None:
    page_header(pdf, 1)
    y = PAGE_H - 132
    y = section_title(pdf, "System at a glance", MARGIN, y)
    y = paragraph(
        pdf,
        "Lux is a continuous desktop character built around the supplied five-DOF lamp URDF. "
        "It combines local engagement, speech recognition, speech synthesis, simulation, and audio "
        "with a cloud vision-language planner. The design keeps the generative model above a strict "
        "application-owned action boundary.",
        MARGIN,
        y,
        PAGE_W - 2 * MARGIN,
        size=8.8,
        leading=11.5,
    ) - 8
    label(pdf, "Architecture and data flow", MARGIN, y)
    y = architecture(pdf, y - 62)

    y = section_title(pdf, "Turn protocol", MARGIN, y)
    col_gap = 22
    col_w = (PAGE_W - 2 * MARGIN - col_gap) / 2
    left = MARGIN
    right = MARGIN + col_w + col_gap
    y_left = y
    y_right = y
    steps_left = [
        ("01", "Engage", "MediaPipe combines head pose, iris offset, eye openness, and face size. A 0.7 s enter / 3.0 s exit hysteresis prevents flicker."),
        ("02", "Listen", "An adaptive energy endpoint detector submits after 2.0 s of continuous silence. Audio stays in memory."),
        ("03", "Understand", "Faster-Whisper Small transcribes locally on CPU; the current frame, transcript, and complete session JSON form the GPT request."),
    ]
    steps_right = [
        ("04", "Act and observe", "GPT returns one whitelisted action. Lux executes fixed keyframes; if another view is requested, it captures a newer frame and calls GPT again."),
        ("05", "Answer and commit", "Only the final validated decision is spoken. Kokoro renders voice locally, then memory is atomically replaced and listening reopens after playback."),
    ]

    def step(number: str, title: str, text: str, x: float, y0: float) -> float:
        pdf.setFillColor(TEAL)
        pdf.circle(x + 10, y0 + 2, 10, fill=1, stroke=0)
        pdf.setFillColor(white)
        pdf.setFont("Helvetica-Bold", 6.8)
        pdf.drawCentredString(x + 10, y0 - 0.3, number)
        pdf.setFillColor(NAVY)
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(x + 28, y0 + 1, title)
        return paragraph(pdf, text, x + 28, y0 - 11, col_w - 28, size=7.7, leading=9.8, color=MUTED) - 7

    for item in steps_left:
        y_left = step(*item, left, y_left)
    for item in steps_right:
        y_right = step(*item, right, y_right)
    y = min(y_left, y_right) - 2

    y = section_title(pdf, "Model-to-action contract", MARGIN, y)
    rounded_card(pdf, MARGIN, y - 62, PAGE_W - 2 * MARGIN, 67, PALE_TEAL)
    x = MARGIN + 13
    yy = y - 14
    label(pdf, "Structured decision", x, yy, TEAL_DARK)
    yy = paragraph(
        pdf,
        "reply | motion_labels (0 or 1) | request_another_observation | updated_memory",
        x,
        yy - 13,
        PAGE_W - 2 * MARGIN - 26,
        font="Helvetica-Bold",
        size=7.7,
        leading=10,
    )
    paragraph(
        pdf,
        "Allowed actions: inspect_left, inspect_right, nod_yes, shake_no. The model never emits joint angles. "
        "At most three camera observations are permitted per user turn; planning replies are neither spoken nor committed.",
        x,
        yy - 4,
        PAGE_W - 2 * MARGIN - 26,
        size=7.5,
        leading=9.5,
        color=MUTED,
    )

    behavior_y = 231
    section_title(pdf, "Character behavior across a turn", MARGIN, behavior_y)
    state_y = 164
    state_gap = 7
    state_w = (PAGE_W - 2 * MARGIN - 5 * state_gap) / 6
    states = [
        ("IDLE", "rest + dim amber", PALE_BLUE),
        ("GREET", "rise + theme", PALE_AMBER),
        ("LISTEN", "lean + blue", PALE_TEAL),
        ("THINK", "curious + violet", PALE_BLUE),
        ("ANSWER", "face + green", PALE_TEAL),
        ("DISENGAGE", "return to rest", PALE_AMBER),
    ]
    for index, (heading, detail, fill) in enumerate(states):
        x0 = MARGIN + index * (state_w + state_gap)
        node(pdf, x0, state_y, state_w, 44, heading, detail, fill)
        if index < len(states) - 1:
            arrow(pdf, x0 + state_w + 1, state_y + 22, x0 + state_w + state_gap - 1, state_y + 22)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica-Oblique", 6.8)
    pdf.drawString(
        MARGIN,
        state_y - 14,
        "Turn lock keeps Think/Answer active through every GPT wait and the full voice playback; listening audio remains suspended.",
    )
    footer(pdf, 1)


def metric_row(
    pdf: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    name: str,
    value: str,
    note: str,
    accent=GREEN,
) -> float:
    h = 43
    rounded_card(pdf, x, y - h, w, h - 3, white)
    pdf.setFillColor(accent)
    pdf.rect(x, y - h, 4, h - 3, fill=1, stroke=0)
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 7.4)
    pdf.drawString(x + 12, y - 14, name.upper())
    pdf.setFillColor(accent)
    pdf.setFont("Helvetica-Bold", 9.4)
    pdf.drawRightString(x + w - 11, y - 15, value)
    paragraph(pdf, note, x + 12, y - 28, w - 24, size=6.7, leading=8.2, color=MUTED)
    return y - h - 4


def draw_page_two(pdf: canvas.Canvas) -> None:
    page_header(pdf, 2)
    top = PAGE_H - 132
    gap = 18
    col_w = (PAGE_W - 2 * MARGIN - gap) / 2
    left = MARGIN
    right = MARGIN + col_w + gap

    y = section_title(pdf, "Implementation choices", left, top)
    y = bullet(pdf, "Perception: MediaPipe Face Landmarker runs locally at 640 x 480. The signals are interaction heuristics, not a claim about cognitive attention.", left, y, col_w)
    y = bullet(pdf, "Speech: Faster-Whisper Small uses CPU int8, beam size 5, and VAD. Kokoro-82M (af_heart, 24 kHz) runs locally and is warmed at startup.", left, y, col_w)
    y = bullet(pdf, "Control: PyBullet loads the fixed-base URDF and CPU TinyRenderer. Eleven five-joint keyframe behaviors are checked against URDF hard limits.", left, y, col_w)
    y = bullet(pdf, "Concurrency: camera, microphone, GPT, TTS, and character audio use Qt workers; the GUI thread owns turn state and memory commit.", left, y, col_w)
    y = bullet(pdf, "Memory: compact conversation and scene summaries are schema-validated and atomically stored for the current run; startup resets the file.", left, y, col_w)

    y -= 3
    y = section_title(pdf, "Deployment and data", left, y)
    y = bullet(pdf, "Target: Ubuntu 24.04, four CPU cores, 8 GB RAM, no CUDA. setup.sh creates Python 3.11, installs native libraries, downloads models, and runs tests.", left, y, col_w)
    y = bullet(pdf, "Local only: raw microphone audio, engagement inference, Whisper, Kokoro, motion, light, SFX, and music.", left, y, col_w)
    y = bullet(pdf, "Sent to OpenAI: transcript, low-detail camera frame(s), and session JSON. Requests set store=False; GPT is the only billable runtime component.", left, y, col_w)

    y2 = section_title(pdf, "Evidence and measurements", right, top)
    y2 = metric_row(pdf, right, y2, col_w, "Automated verification", "67 / 67", "Unit and contract tests passed; PyBullet smoke passed with 5 movable joints, 11 actions, and a 320 x 240 frame.")
    y2 = metric_row(pdf, right, y2, col_w, "Engagement contracts", "8 / 8", "Synthetic head/iris, hysteresis, turn-lock, and post-reply cases passed. Real-camera accuracy is not statistically measured.")
    y2 = metric_row(pdf, right, y2, col_w, "Warm local latency", "7.96 s", "Fixed phrase: STT 5.66 s + TTS generation 2.31 s. Add the configured 2.0 s trailing-silence window and live GPT latency.")
    y2 = metric_row(pdf, right, y2, col_w, "Cold local latency", "29.95 s", "Fresh process with cached weights: TTS 22.07 s + STT 7.89 s. Startup preloading moves this cost before the first turn.", AMBER)
    y2 = metric_row(pdf, right, y2, col_w, "Process memory", "1.92 GiB peak", "Speech benchmark working set ended at 1.62 GiB. Cached model files occupy about 0.76 GiB on disk.")
    y2 = metric_row(pdf, right, y2, col_w, "CPU demand", "4.03 cores", "Warm STT+TTS used 32.09 CPU-s over 7.96 wall-s (core-equivalent average). Measured on the Windows development laptop.")

    box_y = min(y, y2) - 2
    box_h = 128
    rounded_card(pdf, MARGIN, box_y - box_h, PAGE_W - 2 * MARGIN, box_h, PALE_AMBER)
    y3 = section_title(pdf, "Tradeoffs and known limitations", MARGIN + 13, box_y - 20)
    inner_w = PAGE_W - 2 * MARGIN - 32
    half = (inner_w - 18) / 2
    ly = y3
    ry = y3
    ly = bullet(pdf, "GPT vision-language reasoning is flexible but needs Wi-Fi, an API key, incurs cost, and adds variable latency.", MARGIN + 14, ly, half, size=7.3, leading=9.2)
    ly = bullet(pdf, "Fixed semantic actions are inspectable and safe, but less expressive than continuous learned control.", MARGIN + 14, ly, half, size=7.3, leading=9.2)
    ly = bullet(pdf, "The base is fixed; there is no real-robot transport, collision planning, torque control, calibration, or emergency stop.", MARGIN + 14, ly, half, size=7.3, leading=9.2)
    rx = MARGIN + 14 + half + 18
    ry = bullet(pdf, "Engagement uses one face and hand-tuned thresholds; lighting, glasses, camera placement, and face geometry can reduce reliability.", rx, ry, half, size=7.3, leading=9.2)
    ry = bullet(pdf, "A turn is capped at three visual observations and one action per model response, limiting long plans.", rx, ry, half, size=7.3, leading=9.2)
    ry = bullet(pdf, "Ubuntu package names and script syntax are checked, but camera, audio, GUI, latency, and memory still require physical Ubuntu validation.", rx, ry, half, size=7.3, leading=9.2)

    section_title(pdf, "Completion boundary", MARGIN, 207)
    card_gap = 14
    card_w = (PAGE_W - 2 * MARGIN - card_gap) / 2
    rounded_card(pdf, MARGIN, 112, card_w, 70, PALE_TEAL)
    rounded_card(pdf, MARGIN + card_w + card_gap, 112, card_w, 70, PALE_BLUE)
    label(pdf, "Completed", MARGIN + 12, 165, GREEN)
    paragraph(
        pdf,
        "Live desktop loop; local STT/TTS; GPT scene reasoning; session memory; iterative observation; simulated motion, light, SFX, and music.",
        MARGIN + 12,
        150,
        card_w - 24,
        size=7.4,
        leading=9.4,
        color=INK,
    )
    label(pdf, "Intentionally left out", MARGIN + card_w + card_gap + 12, 165, AMBER)
    paragraph(
        pdf,
        "Real hardware transport and safety stack; continuous VLA joint control; cross-session identity; statistical user study; target-laptop hardware certification.",
        MARGIN + card_w + card_gap + 12,
        150,
        card_w - 24,
        size=7.4,
        leading=9.4,
        color=INK,
    )

    label(pdf, "Reproduce", MARGIN, 65)
    pdf.setFillColor(SOFT)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(MARGIN, 43, PAGE_W - 2 * MARGIN, 18, 4, fill=1, stroke=1)
    pdf.setFillColor(INK)
    pdf.setFont("Courier", 6.8)
    pdf.drawString(MARGIN + 8, 49, ".conda-env/python -m unittest discover -s tests -q   |   python scripts/benchmark_local_models.py")
    footer(pdf, 2)


def build() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(OUTPUT), pagesize=A4, pageCompression=1)
    pdf.setTitle("Lux Technical Note")
    pdf.setAuthor("Lux Lamp Character Project")
    pdf.setSubject("Software/CV Character Robot Challenge technical note")
    draw_page_one(pdf)
    pdf.showPage()
    draw_page_two(pdf)
    pdf.showPage()
    pdf.save()
    return OUTPUT


if __name__ == "__main__":
    print(build())
