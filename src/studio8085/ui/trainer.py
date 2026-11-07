"""The "Virtual 8085 Trainer Kit" dock: 8 switches, 8 LEDs and a seven-segment digit (Phase 1).

The hardware model lives in ``core/peripherals.py`` (no Qt). This module only draws it and lets the user
operate it. Everything is painted with QPainter vectors, so it stays sharp at any display scale, and every
size is derived from the font metrics, so it follows the "Interface font size" preference.

Refreshing is pull-based: the main window calls :meth:`TrainerPanel.refresh` from its normal refresh path
(after every step, and at most every 80 ms while a program runs), never once per instruction.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF, QRadialGradient
from PySide6.QtWidgets import (QAbstractButton, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..core.peripherals import HEX, RAW, PeripheralConfigError, PortMap, TrainerKit
from .docks import mono, parse_hex
from .themes import DARK, Theme

TITLE = "Virtual 8085 Trainer Kit"


def _c(theme: Theme | None, key: str) -> QColor:
    if theme is not None and key in theme.colors:
        return QColor(theme.colors[key])
    return QColor(DARK.get(key, "#888888"))


def bits(v: int) -> str:
    return f"{v >> 4:04b} {v & 15:04b}"


# ------------------------------------------------------------------ switches
class ToggleSwitch(QAbstractButton):
    """One slide switch. Up (knob at the top) = 1. Space or Enter toggles; Left/Right move to the neighbour."""

    def __init__(self, bit: int, parent=None):
        super().__init__(parent)
        self.bit = bit
        self.theme: Theme | None = None
        self.neighbours: list[ToggleSwitch] = []
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(mono(10))
        self.setText(f"SW{bit}")
        self.setAccessibleName(f"SW{bit}")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.toggled.connect(self._describe)
        self._describe(False)

    def set_port(self, port: int):
        self.setToolTip(f"SW{self.bit}: switch for bit {self.bit} of IN {port:02X}H\n"
                        f"Up = 1, down = 0. Click, or press Space, to flip it.\n"
                        "(A virtual teaching port, not a real kit address.)")
        self._describe(self.isChecked())

    def _describe(self, on: bool):
        self.setAccessibleDescription(f"Switch {self.bit}, bit {self.bit} of the input byte: {'on, 1' if on else 'off, 0'}")

    def sizeHint(self) -> QSize:
        h = self.fontMetrics().height()
        return QSize(round(h * 1.8), round(h * 2.7))

    minimumSizeHint = sizeHint

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
            return
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Right) and self.neighbours:
            i = self.neighbours.index(self) + (1 if k == Qt.Key.Key_Right else -1)
            if 0 <= i < len(self.neighbours):
                self.neighbours[i].setFocus(Qt.FocusReason.TabFocusReason)
            return
        super().keyPressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.theme
        on = self.isChecked()
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        radius = r.width() * 0.28
        track = _c(t, "alt_base")
        p.setPen(QPen(_c(t, "accent") if on else _c(t, "border"), 1.4))
        p.setBrush(track)
        p.drawRoundedRect(r, radius, radius)
        knob = QRectF(r.x() + 3, r.y() + 3, r.width() - 6, r.height() / 2 - 3)
        if not on:
            knob.moveTop(r.center().y())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_c(t, "accent") if on else _c(t, "text_dim"))
        p.drawRoundedRect(knob, radius * 0.7, radius * 0.7)
        p.setPen(_c(t, "accent_text") if on else _c(t, "base"))
        f = self.font()
        f.setBold(True)
        p.setFont(f)
        p.drawText(knob, Qt.AlignmentFlag.AlignCenter, "1" if on else "0")
        if self.hasFocus():
            p.setPen(QPen(_c(t, "accent"), 2, Qt.PenStyle.DotLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), radius + 2, radius + 2)
        p.end()


# ---------------------------------------------------------------------- LEDs
class LedLamp(QWidget):
    """One LED. Lit = filled with a restrained glow; dark = outline only (so on/off never relies on colour)."""

    def __init__(self, bit: int, parent=None):
        super().__init__(parent)
        self.bit = bit
        self.on = False
        self.theme: Theme | None = None
        self.setFont(mono(10))
        self.setAccessibleName(f"LED{bit}")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set_on(False)

    def set_port(self, port: int):
        self.setToolTip(f"LED{self.bit}: lit when bit {self.bit} of the byte sent by OUT {port:02X}H is 1 "
                        "(active-high).\nOnly OUT to this port changes it; it never changes registers or flags.")

    def set_on(self, on: bool):
        self.on = bool(on)
        self.setAccessibleDescription(f"LED {self.bit}: {'on, 1' if self.on else 'off, 0'}")
        self.update()

    def sizeHint(self) -> QSize:
        h = self.fontMetrics().height()
        return QSize(round(h * 1.5), round(h * 1.5))

    minimumSizeHint = sizeHint

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.theme
        side = min(self.width(), self.height())
        c = QPointF(self.width() / 2, self.height() / 2)
        rad = side * 0.32
        on_col, off_col = _c(t, "led_on"), _c(t, "led_off")
        if self.on:
            glow = QRadialGradient(c, side * 0.5)
            g = QColor(on_col)
            g.setAlpha(110)
            glow.setColorAt(0.55, g)
            g.setAlpha(0)
            glow.setColorAt(1.0, g)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(glow))
            p.drawEllipse(c, side * 0.5, side * 0.5)
        p.setPen(QPen(on_col.darker(130) if self.on else _c(t, "border"), 1.4))
        p.setBrush(on_col if self.on else off_col)
        p.drawEllipse(c, rad, rad)
        if self.on:  # small highlight
            hl = QColor(255, 255, 255, 120)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(hl)
            p.drawEllipse(QPointF(c.x() - rad * 0.35, c.y() - rad * 0.35), rad * 0.28, rad * 0.22)
        p.end()


# ------------------------------------------------------------- seven-segment
class SevenSegmentWidget(QWidget):
    """A single digit: segments a-g as slanted bars plus the decimal point, drawn as vectors."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lit: set[str] = set()
        self.theme: Theme | None = None
        self.setFont(mono(10))
        self.setAccessibleName("Seven-segment display")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_segments(self, lit: set[str], text: str):
        if lit != self.lit:
            self.lit = set(lit)
            self.update()
        self.setAccessibleDescription(text)

    def sizeHint(self) -> QSize:
        h = self.fontMetrics().height()
        return QSize(round(h * 3.4), round(h * 4.6))

    minimumSizeHint = sizeHint

    def _segment_paths(self, box: QRectF) -> dict[str, QPolygonF]:
        w, h = box.width(), box.height()
        th = w * 0.17  # bar thickness
        x0, y0 = box.x(), box.y()
        slant = w * 0.08

        def sx(x, y):  # slant to the right going up
            return QPointF(x0 + x + slant * (1 - y / h), y0 + y)

        def hbar(y):
            g = th * 0.15
            return QPolygonF([sx(th * 0.5 + g, y), sx(th + g, y - th / 2), sx(w - th - g, y - th / 2),
                              sx(w - th * 0.5 - g, y), sx(w - th - g, y + th / 2), sx(th + g, y + th / 2)])

        def vbar(x, ya, yb):
            g = th * 0.15
            return QPolygonF([sx(x, ya + g), sx(x + th / 2, ya + th / 2 + g), sx(x + th / 2, yb - th / 2 - g),
                              sx(x, yb - g), sx(x - th / 2, yb - th / 2 - g), sx(x - th / 2, ya + th / 2 + g)])

        top, mid, bot = th / 2, h / 2, h - th / 2
        left, right = th / 2, w - th / 2
        return {"a": hbar(top), "g": hbar(mid), "d": hbar(bot),
                "f": vbar(left, top, mid), "b": vbar(right, top, mid),
                "e": vbar(left, mid, bot), "c": vbar(right, mid, bot)}

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.theme
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(_c(t, "border"), 1))
        p.setBrush(_c(t, "seg_bg"))
        p.drawRoundedRect(r, 6, 6)
        pad = r.width() * 0.16
        box = QRectF(r.x() + pad, r.y() + pad, r.width() - 2.6 * pad, r.height() - 2 * pad)
        on, off = _c(t, "seg_on"), _c(t, "seg_off")
        glow = QColor(on)
        glow.setAlpha(70)
        p.setPen(Qt.PenStyle.NoPen)
        for name, poly in self._segment_paths(box).items():
            if name in self.lit:
                path = QPainterPath()
                path.addPolygon(poly)
                p.strokePath(path, QPen(glow, box.width() * 0.06, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                        Qt.PenJoinStyle.RoundJoin))
            p.setBrush(on if name in self.lit else off)
            p.drawPolygon(poly)
        dr = box.width() * 0.095
        dp = QPointF(box.right() + pad * 0.75, box.bottom() - dr)
        p.setBrush(on if "p" in self.lit else off)
        p.drawEllipse(dp, dr, dr)
        p.end()


# --------------------------------------------------------- port map dialog
class PortMapDialog(QDialog):
    """Change the virtual port numbers. OK is only enabled for a valid, conflict-free map."""

    def __init__(self, ports: PortMap, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Trainer Kit Port Mapping")
        self.edits: dict[str, QLineEdit] = {}
        form = QFormLayout()
        for key, label, value in (("switches_in", "Switches (IN port, hex)", ports.switches_in),
                                  ("leds_out", "LEDs (OUT port, hex)", ports.leds_out),
                                  ("seven_segment_out", "Seven-segment (OUT port, hex)", ports.seven_segment_out)):
            e = QLineEdit(f"{value:02X}")
            e.setMaxLength(4)
            e.setAccessibleName(label)
            e.textChanged.connect(self._validate)
            form.addRow(label, e)
            self.edits[key] = e
        note = QLabel("These are virtual teaching assignments, not the addresses of a real 8085 kit. "
                      "An IN port and an OUT port may share a number (they are different bus cycles); "
                      "the two output devices need different ports.")
        note.setWordWrap(True)
        note.setObjectName("Dim")
        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setObjectName("PortError")
        self.error.setAccessibleName("Port mapping problem")
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
                                        | QDialogButtonBox.StandardButton.RestoreDefaults)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self._defaults)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(note)
        lay.addWidget(self.error)
        lay.addWidget(self.buttons)
        self.setMinimumWidth(min(420, max(300, self.sizeHint().width())))
        self._validate()

    def _defaults(self):
        d = PortMap()
        for key, e in self.edits.items():
            e.setText(f"{getattr(d, key):02X}")

    def ports(self) -> PortMap | None:
        vals = {}
        for key, e in self.edits.items():
            v = parse_hex(e.text(), 8)
            if v is None:
                return None
            vals[key] = v
        return PortMap(**vals)

    def problem(self) -> str:
        for key, e in self.edits.items():
            if parse_hex(e.text(), 8) is None:
                return f"'{e.text()}' is not a port: type 00 to FF (hex)."
        try:
            self.ports().validate()
        except PeripheralConfigError as err:
            return str(err)
        return ""

    def _validate(self, *_):
        msg = self.problem()
        self.error.setText(msg)
        self.error.setVisible(bool(msg))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not msg)


# ---------------------------------------------------------- Experiment 1 guide
class ExperimentGuide(QGroupBox):
    """Experiment 1, "Read Switches and Control LEDs": a guided predict-run-compare flow.

    The expected LED pattern is never shown before the student locks in a prediction, unless they press
    "Help me". The comparison uses the real CPU state (A after IN) and the real LED latch (after OUT).
    """

    load_requested = Signal()  # "load and assemble the program"
    conceal_changed = Signal(bool)  # hide the switch value readout until a prediction exists
    ended = Signal()  # "End experiment": close the guide and unmask everything

    STEPS = ["Set the switches", "Predict the LEDs", "Assemble", "Step through", "A after IN",
             "LEDs after OUT", "Compare", "Explain"]

    def __init__(self, parent=None):
        super().__init__("Experiment 1: Read Switches and Control LEDs", parent)
        self.kit: TrainerKit | None = None
        self.machine = None
        self.prediction: int | None = None
        self.predicted_switches: int | None = None
        self.helped = False
        self.observed_a: int | None = None
        self.observed_leds: int | None = None
        self.stage = 0

        self.objectives = QLabel(
            "<b>You will learn:</b> what <b>IN</b> does (copy an input port into the accumulator A), what <b>OUT</b> "
            "does (copy A to an output port), why A is the go-between, how to read an 8-bit binary number, how to "
            "predict the LEDs, and how to run and debug step by step.")
        self.step_label = QLabel()
        self.step_label.setObjectName("Section")
        self.text = QLabel()
        for w in (self.objectives, self.text):
            w.setWordWrap(True)
            w.setTextFormat(Qt.TextFormat.RichText)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.predict_edit = QLineEdit()
        self.predict_edit.setPlaceholderText("e.g. 10100101 or A5h")
        self.predict_edit.setAccessibleName("Predicted LED byte")
        self.predict_edit.setToolTip("Type the LED pattern you expect: 8 binary digits (LED7 first), or hex ending in h")
        self.predict_edit.setFont(mono(10))
        self.predict_edit.returnPressed.connect(self.lock_prediction)
        self.lock_btn = QPushButton("Lock in prediction")
        self.lock_btn.clicked.connect(self.lock_prediction)
        self.help_btn = QPushButton("Help me")
        self.help_btn.setToolTip("Show the expected answer and why (skips your own prediction)")
        self.help_btn.clicked.connect(self.ask_help)
        self.next_btn = QPushButton("Next")
        self.next_btn.clicked.connect(self.next_stage)
        self.load_btn = QPushButton("Load and assemble the program")
        self.load_btn.clicked.connect(self.load_requested.emit)
        self.restart_btn = QPushButton("Start over")
        self.restart_btn.clicked.connect(self.start_over)
        self.end_btn = QPushButton("End experiment")
        self.end_btn.setToolTip("Close the guide and show everything again (the answer is no longer hidden)")
        self.end_btn.clicked.connect(self.ended.emit)
        row1 = QHBoxLayout()
        row1.addWidget(self.predict_edit, 1)
        row1.addWidget(self.lock_btn)
        row2 = QHBoxLayout()
        for b in (self.next_btn, self.load_btn, self.help_btn):
            row2.addWidget(b)
        row2.addStretch(1)
        row2.addWidget(self.restart_btn)
        row2.addWidget(self.end_btn)
        lay = QVBoxLayout(self)
        lay.addWidget(self.objectives)
        lay.addWidget(self.step_label)
        lay.addWidget(self.text)
        lay.addLayout(row1)
        lay.addLayout(row2)
        self._show()

    def set_context(self, kit: TrainerKit, machine):
        self.kit, self.machine = kit, machine

    # ------------------------------------------------------------- flow
    @staticmethod
    def parse_prediction(text: str) -> int | None:
        t = text.strip().replace(" ", "").replace("_", "")
        if not t:
            return None
        low = t.lower()
        if low.endswith("b") and set(low[:-1]) <= {"0", "1"} and len(low) == 9:
            low = low[:-1]
        if len(low) == 8 and set(low) <= {"0", "1"}:
            return int(low, 2)
        return parse_hex(t, 8) if (low.endswith("h") or low.startswith("0x")) else None

    def answer_known(self) -> bool:
        return self.prediction is not None or self.helped

    def lock_prediction(self):
        v = self.parse_prediction(self.predict_edit.text())
        if v is None:
            self.text.setText("<p>Type the pattern as <b>8 binary digits</b> (LED7 first, e.g. <tt>10100101</tt>) "
                              "or as <b>hex</b> ending in h (e.g. <tt>A5h</tt>), then lock it in.</p>")
            return
        self.prediction = v
        self.predicted_switches = self.kit.switches.value if self.kit else None
        self.stage = max(self.stage, 2)
        self.conceal_changed.emit(False)
        self._show()

    def ask_help(self):
        self.helped = True
        self.stage = max(self.stage, 2)
        self.conceal_changed.emit(False)
        self._show()

    def next_stage(self):
        if self.stage == 1 and not self.answer_known():
            return
        self.stage = min(self.stage + 1, 2) if self.stage < 2 else self.stage
        self._show()

    def start_over(self):
        self.prediction = self.predicted_switches = None
        self.helped = False
        self.observed_a = self.observed_leds = None
        self.stage = 0
        self.predict_edit.clear()
        self.conceal_changed.emit(True)
        self._show()

    def program_loaded(self):
        """The main window loaded and assembled the Experiment 1 program (outputs were blanked)."""
        self.observed_a = self.observed_leds = None
        if self.answer_known():
            self.stage = 3
        self._show()

    def observe(self):
        """Called from the main window's refresh path: read the real CPU state and the real LED latch."""
        if self.kit is None or self.machine is None or self.stage < 3:
            return
        bus = self.kit.bus
        changed = False
        if self.observed_a is None and bus.last_in is not None and bus.last_in[0] == self.kit.switches.port:
            self.observed_a = self.machine.cpu.a  # the accumulator itself, after IN executed
            self.stage, changed = max(self.stage, 4), True
        if self.observed_leds is None and self.kit.leds.written:
            self.observed_leds = self.kit.leds.value  # the LED latch, after OUT executed
            if self.observed_a is None:
                self.observed_a = self.machine.cpu.a
            self.stage, changed = 7, True
        if changed:
            self._show()

    # ---------------------------------------------------------- display
    def _show(self):
        st = self.stage
        if st >= 6:
            self.step_label.setText("STEPS 7-8 OF 8 - COMPARE AND EXPLAIN")
        else:
            self.step_label.setText(f"STEP {st + 1} OF 8 - {self.STEPS[st].upper()}")
        self.predict_edit.setVisible(st == 1)
        self.lock_btn.setVisible(st == 1)
        self.help_btn.setVisible(st in (1, 2, 3, 4) and not self.helped)
        self.next_btn.setVisible(st in (0, 1))
        self.next_btn.setEnabled(st == 0 or self.answer_known())
        self.load_btn.setVisible(st >= 2)
        port = self.kit.ports if self.kit else PortMap()
        sw, led = f"{port.switches_in:02X}H", f"{port.leds_out:02X}H"
        if st == 0:
            html = (f"<p>Flip the switches <b>SW7...SW0</b> above to any pattern (click one, or Tab to it and press "
                    f"Space). Up = 1, down = 0; SW7 on the left is the most significant bit. They are wired to "
                    f"<b>IN {sw}</b>.</p><p>Then press <b>Next</b>.</p>")
        elif st == 1:
            html = (f"<p>The program is:</p><pre>START: IN  {sw}\n       OUT {led}\n       HLT</pre>"
                    f"<p>Read the switch positions yourself. Which LEDs will be lit after the program runs? Type "
                    f"your prediction and lock it in. (The switch value readout is hidden until you do.)</p>")
        elif st == 2:
            html = self._known() + "<p>Now load and assemble the program (the button below, or F7 on the source).</p>"
        elif st == 3:
            html = (self._known() + "<p>Press <b>Step Into</b> (F11) once and watch register <b>A</b> in the "
                    "Registers panel. You can also set a breakpoint or press Run.</p>")
        elif st in (4, 5):
            html = (self._known() + f"<p><b>IN {sw}</b> executed: the CPU copied the switch byte into the "
                    f"accumulator. <b>A = {bits(self.observed_a)}b ({self.observed_a:02X}h)</b> - read from the real "
                    f"register.</p><p>Step again to execute <b>OUT {led}</b> and watch the LEDs.</p>")
        else:
            html = self._known() + self._compare()
        self.text.setText(html)

    def _known(self) -> str:
        parts = []
        if self.prediction is not None:
            parts.append(f"Your prediction: <b>{bits(self.prediction)}b ({self.prediction:02X}h)</b>.")
        if self.helped and self.kit is not None:
            v = self.kit.switches.value
            parts.append(f"Help: IN copies the switch byte into A and OUT copies A to the LEDs, so the LEDs should "
                         f"show the switch pattern <b>{bits(v)}b ({v:02X}h)</b>.")
        return "<p>" + " ".join(parts) + "</p>" if parts else ""

    def _compare(self) -> str:
        a, leds = self.observed_a, self.observed_leds
        port = self.kit.ports if self.kit else PortMap()
        out = [f"<p><b>A after IN = {bits(a)}b ({a:02X}h)</b>; "
               f"<b>LEDs after OUT = {bits(leds)}b ({leds:02X}h)</b> - read from the CPU and the LED latch.</p>"]
        if self.prediction is None:
            out.append("<p>No prediction was locked in this time (you asked for help).</p>")
        elif self.prediction == leds:
            out.append("<p><b>Match - your prediction was right.</b></p>")
        else:
            diff = self.prediction ^ leds
            wrong = ", ".join(f"LED{n}" for n in range(7, -1, -1) if diff >> n & 1)
            out.append(f"<p><b>Not quite</b>: {wrong} differ from your prediction.</p>")
            if self.predicted_switches is not None and self.kit is not None \
                    and self.predicted_switches != self.kit.switches.value:
                out.append("<p>Note: the switches were changed after you made your prediction.</p>")
        out.append(f"<p><b>Why:</b> <tt>IN {port.switches_in:02X}H</tt> reads the 8 switches as one byte into the "
                   f"accumulator A (bit n = SWn). <tt>OUT {port.leds_out:02X}H</tt> sends A to the LED latch (bit n "
                   "lights LEDn). A is the go-between: the 8085 moves port data only through A. Neither instruction "
                   "changes any flag. <tt>HLT</tt> stops the CPU; the LEDs keep their value (a latch).</p>"
                   "<p>Try other switch patterns, press Restart and step again, or press Start over.</p>")
        return "".join(out)


# --------------------------------------------------------------------- panel
class TrainerPanel(QWidget):
    """The dock contents. ``changed`` is emitted when the user changes the hardware (switches, mode, ...)."""

    changed = Signal()
    concealed_changed = Signal(bool)  # Experiment 1 is hiding the answer (display only)
    enabled_changed = Signal(bool)
    mode_changed = Signal(str)
    ports_requested = Signal()
    reset_requested = Signal()

    def __init__(self, kit: TrainerKit, parent=None):
        super().__init__(parent)
        self.kit = kit
        self.theme: Theme | None = None
        self._conceal = False
        self._shown: tuple | None = None

        self.connected = QCheckBox("Kit connected")
        self.connected.setToolTip("Connect the virtual kit to the CPU's IN/OUT ports.\n"
                                  "Unchecked: IN/OUT behave exactly as without the kit (I/O Ports table only).")
        self.connected.toggled.connect(self._toggle_enabled)
        self.ports_btn = QPushButton("Ports...")
        self.ports_btn.setToolTip("Change which ports the switches, LEDs and display use")
        self.ports_btn.clicked.connect(self.ports_requested.emit)
        self.reset_btn = QPushButton("Reset hardware")
        self.reset_btn.setToolTip("Power-on reset of the kit: all switches down, LEDs and display blank.\n"
                                  "(Assembling or restarting a program blanks the LEDs and display but keeps the switches.)")
        self.reset_btn.clicked.connect(self.reset_requested.emit)
        top = QHBoxLayout()
        top.addWidget(self.connected)
        top.addStretch(1)
        top.addWidget(self.ports_btn)
        top.addWidget(self.reset_btn)

        # switches
        self.sw_box = QGroupBox()
        g = QGridLayout(self.sw_box)
        g.setHorizontalSpacing(6)
        self.switches: list[ToggleSwitch] = []
        for col, bit in enumerate(range(7, -1, -1)):
            s = ToggleSwitch(bit)
            s.toggled.connect(lambda on, b=bit: self._switch(b, on))
            g.addWidget(s, 0, col, Qt.AlignmentFlag.AlignHCenter)
            lab = QLabel(f"SW{bit}")
            lab.setFont(mono(9))
            lab.setObjectName("Dim")
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            g.addWidget(lab, 1, col)
            self.switches.append(s)
        for s in self.switches:
            s.neighbours = self.switches
        self.sw_value = QLabel()
        self.sw_value.setFont(mono(10))
        self.sw_value.setAccessibleName("Switch value")
        g.addWidget(self.sw_value, 2, 0, 1, 8)

        # LEDs
        self.led_box = QGroupBox()
        g = QGridLayout(self.led_box)
        g.setHorizontalSpacing(6)
        self.leds: list[LedLamp] = []
        for col, bit in enumerate(range(7, -1, -1)):
            lamp = LedLamp(bit)
            g.addWidget(lamp, 0, col, Qt.AlignmentFlag.AlignHCenter)
            lab = QLabel(f"LED{bit}")
            lab.setFont(mono(9))
            lab.setObjectName("Dim")
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            g.addWidget(lab, 1, col)
            self.leds.append(lamp)
        self.led_value = QLabel()
        self.led_value.setFont(mono(10))
        self.led_value.setAccessibleName("LED value")
        g.addWidget(self.led_value, 2, 0, 1, 8)

        # seven-segment
        self.seg_box = QGroupBox()
        h = QHBoxLayout(self.seg_box)
        self.digit = SevenSegmentWidget()
        h.addWidget(self.digit, 0, Qt.AlignmentFlag.AlignTop)
        side = QVBoxLayout()
        self.mode = QComboBox()
        self.mode.setAccessibleName("Seven-segment mode")
        # may be narrower than its longest item so it always fits a narrow dock (the popup list stays full width)
        self.mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.mode.setMinimumContentsLength(12)
        self.mode.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)  # never wider than the dock
        self.mode.addItem("Raw segment bits", RAW)
        self.mode.addItem("Hex decode (low nibble)", HEX)
        self.mode.setToolTip("Raw segment bits: bit0=a, bit1=b, ... bit6=g, bit7=DP; 1 lights a segment.\n"
                             "Hex decode: bits 3-0 choose a digit 0-F; bits 7-4 are ignored.\n"
                             "Changing this only changes the display, never the CPU.")
        self.mode.currentIndexChanged.connect(self._mode)
        self.seg_value = QLabel()
        self.seg_value.setFont(mono(10))
        self.seg_value.setAccessibleName("Seven-segment value")
        self.seg_value.setWordWrap(True)
        side.addWidget(self.mode)
        side.addWidget(self.seg_value)
        side.addStretch(1)
        h.addLayout(side, 1)

        self.guide = ExperimentGuide()
        self.guide.set_context(kit, None)
        self.guide.conceal_changed.connect(self.set_conceal)
        self.guide.ended.connect(self.hide_guide)
        self.guide.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addLayout(top)
        lay.addWidget(self.sw_box)
        lay.addWidget(self.led_box)
        lay.addWidget(self.seg_box)
        lay.addWidget(self.guide)
        lay.addStretch(1)
        self.sync_from_kit()

    # ------------------------------------------------------- geometry
    def _fit_height(self):
        """Word-wrapped text (the Experiment 1 guide) needs more height when the panel is narrow. The dock's
        scroll area sizes the panel from its minimum, so keep the minimum height equal to what the layout
        needs at the current width; then the text scrolls instead of being cut off."""
        lay = self.layout()
        if lay is None:
            return
        need = lay.totalHeightForWidth(self.width()) if lay.hasHeightForWidth() else lay.totalMinimumSize().height()
        need = max(need, lay.totalMinimumSize().height())
        if need != self.minimumHeight():
            self.setMinimumHeight(need)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_height()

    def event(self, e):
        if e.type() == e.Type.LayoutRequest:
            QTimer.singleShot(0, self._fit_height)
        return super().event(e)

    # ---------------------------------------------------------- wiring
    def set_machine(self, machine):
        self.guide.set_context(self.kit, machine)

    def set_theme(self, theme: Theme):
        self.theme = theme
        for w in (*self.switches, *self.leds, self.digit):
            w.theme = theme
            w.update()

    def set_conceal(self, on: bool):
        """Hide the switch value readout (Experiment 1, before the student has predicted)."""
        self._conceal = on
        self._shown = None
        self.refresh()
        self.concealed_changed.emit(on)

    @property
    def concealed(self) -> bool:
        return self._conceal

    def show_guide(self):
        self.guide.show()
        if not self.guide.answer_known() and self.guide.stage <= 1:
            self.set_conceal(True)

    def hide_guide(self):
        self.guide.hide()
        self.set_conceal(False)

    def _toggle_enabled(self, on: bool):
        if on != self.kit.enabled:
            self.kit.set_enabled(on)
            self.enabled_changed.emit(on)
        self._enable_widgets()
        self.refresh()

    def _enable_widgets(self):
        # the switches can be set while disconnected (they are just not read), the display only shows
        for b in (self.led_box, self.seg_box):
            b.setEnabled(self.kit.enabled)

    def _switch(self, bit: int, on: bool):
        if self.kit.switches.bit(bit) != on:
            self.kit.switches.set_bit(bit, on)
            self.kit.bus.sync_inputs()
            self.changed.emit()
        self.refresh()

    def _mode(self, _i):
        mode = self.mode.currentData()
        if mode != self.kit.display.mode:
            self.kit.display.set_mode(mode)
            self.mode_changed.emit(mode)
        self.refresh()

    def sync_from_kit(self):
        """Pull everything (ports, switch positions, mode, enabled) from the kit, e.g. after a reset."""
        k = self.kit
        p = k.ports
        self.sw_box.setTitle(f"Switches - IN {p.switches_in:02X}H")
        self.led_box.setTitle(f"LEDs - OUT {p.leds_out:02X}H")
        self.seg_box.setTitle(f"Seven-segment - OUT {p.seven_segment_out:02X}H")
        for s in self.switches:
            s.set_port(p.switches_in)
            s.blockSignals(True)
            s.setChecked(k.switches.bit(s.bit))
            s._describe(s.isChecked())
            s.blockSignals(False)
            s.update()
        for lamp in self.leds:
            lamp.set_port(p.leds_out)
        self.digit.setToolTip(f"Seven-segment digit on OUT {p.seven_segment_out:02X}H.\n"
                              "Raw mode (default, active-high): bit0=a, bit1=b, bit2=c, bit3=d, bit4=e, bit5=f, "
                              "bit6=g, bit7=DP.\nHex mode: the low nibble selects 0-F.")
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(max(0, self.mode.findData(k.display.mode)))
        self.mode.blockSignals(False)
        self.connected.blockSignals(True)
        self.connected.setChecked(k.enabled)
        self.connected.blockSignals(False)
        self._enable_widgets()
        self._shown = None
        self.refresh()

    # ---------------------------------------------------------- refresh
    def refresh(self):
        k = self.kit
        d = k.display
        key = (k.switches.value, k.leds.value, k.leds.written, d.value, d.written, d.mode, d.active_low,
               d.segment_order, k.enabled, self._conceal)
        if key != self._shown:
            self._shown = key
            sw = k.switches.value
            for s in self.switches:
                if s.isChecked() != k.switches.bit(s.bit):
                    s.blockSignals(True)
                    s.setChecked(k.switches.bit(s.bit))
                    s._describe(s.isChecked())
                    s.blockSignals(False)
            if self._conceal:
                self.sw_value.setText("= ???? ????b  (read the switches, then predict)")
            else:
                self.sw_value.setText(f"= {bits(sw)}b = {sw:02X}h" + ("" if k.enabled else "  (not connected)"))
            lv = k.leds.value
            hide = self._conceal  # presentation only: the latches themselves are untouched
            for lamp in self.leds:
                want = False if hide else k.leds.lit(lamp.bit)
                if lamp.on != want:
                    lamp.set_on(want)
            if hide:
                self.led_value.setText("= ???? ????b  (hidden until you predict)")
            else:
                self.led_value.setText(f"= {bits(lv)}b = {lv:02X}h" + ("" if k.leds.written else "  (no OUT yet)"))
            self.led_value.setAccessibleDescription(self.led_value.text())
            if hide:
                self.seg_value.setText("latch ??h\n(hidden until you predict)")
                self.digit.set_segments(set(), "Display hidden until you predict")
                if self.guide.isVisible():
                    self.guide.observe()
                return
            lit = d.segments()
            names = " ".join(s if s != "p" else "DP" for s in "abcdefgp" if s in lit) or "none"
            glyph = d.glyph()
            text = f"latch {d.value:02X}h = {bits(d.value)}b\nlit: {names}" + (f"\nshows: {glyph}" if glyph else "")
            if not d.written:
                text += "\n(no OUT yet)"
            self.seg_value.setText(text)
            self.digit.set_segments(lit, f"{'Hex digit ' + glyph if glyph else 'Segments lit: ' + names}")
        if self.guide.isVisible():
            self.guide.observe()
