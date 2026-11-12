"""The "Labs" tab of the Interactive CPU Architecture panel. Content lives in ``core/lab_content.py``; this class
only renders it and forwards two requests (load the lab program, check the result) to the main window."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import QBoxLayout, QComboBox, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from ..core.lab_content import LABS, feedback
from ..core.visual import CpuState, KitView


class LabGuidePanel(QWidget):
    load_requested = Signal(str)
    check_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.combo = QComboBox()
        self.combo.setAccessibleName("Lab")
        for key, lab in LABS.items():
            self.combo.addItem(lab.title, key)
        self.load_btn = QPushButton("Load lab program")
        self.load_btn.setToolTip("Put the lab program in the editor (you are asked first if you have unsaved changes)")
        self.check_btn = QPushButton("Check my result")
        self.check_btn.setToolTip("Compare the CPU's current state with what the lab expects")
        self.view = QTextBrowser()
        self.view.setAccessibleName("Lab guide")
        # two short rows (the lab list, then the buttons) and a combo that may be narrower than its longest title,
        # so the guide never forces the CPU panel wider than a small dock
        self.combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(12)
        # the two buttons sit side by side when the panel is wide enough and one above the other when it is narrow
        self._btn_row = row = QBoxLayout(QBoxLayout.Direction.TopToBottom)
        row.addWidget(self.load_btn)
        row.addWidget(self.check_btn)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.combo)
        lay.addLayout(row)
        lay.addWidget(self.view, 1)
        self.combo.currentIndexChanged.connect(lambda _i: self.show_lab())
        self.load_btn.clicked.connect(lambda: self.load_requested.emit(self.key))
        self.check_btn.clicked.connect(lambda: self.check_requested.emit(self.key))
        self.show_lab()

    def minimumSizeHint(self) -> QSize:
        """Narrow enough for a small dock: the stacked layout (buttons one above the other) is the minimum."""
        sh = super().minimumSizeHint()
        m = self.layout().contentsMargins()
        w = max(self.combo.minimumSizeHint().width(), self.load_btn.sizeHint().width(),
                self.check_btn.sizeHint().width()) + m.left() + m.right()
        return QSize(w, sh.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        m = self.layout().contentsMargins()
        need = (self.load_btn.sizeHint().width() + self.check_btn.sizeHint().width()
                + self._btn_row.spacing() + 8 + m.left() + m.right())
        want = QBoxLayout.Direction.LeftToRight if self.width() >= need else QBoxLayout.Direction.TopToBottom
        if self._btn_row.direction() != want:
            self._btn_row.setDirection(want)

    @property
    def key(self) -> str:
        return str(self.combo.currentData())

    def select(self, key: str):
        i = self.combo.findData(key)
        if i >= 0:
            self.combo.setCurrentIndex(i)

    def show_lab(self):
        lab = LABS[self.key]
        h = [f"<h3>{escape(lab.title)}</h3><p><b>Objectives</b></p><ul>"]
        h += [f"<li>{escape(t)}</li>" for t in lab.objectives]
        h.append("</ul><p><b>What to do</b></p><ol>")
        h += [f"<li>{escape(t)}</li>" for t in lab.instructions]
        h.append("</ol>")
        if not lab.reveal_expected:
            h.append("<p><i>The expected result is not printed here: predict it first, then run it and compare.</i></p>")
        else:
            h.append("<p><i>Press <b>Check my result</b> after the program has run to see the expected outcomes "
                     "and feedback.</i></p>")
        self.view.setHtml("".join(h))

    def show_feedback(self, state: CpuState, kit: KitView):
        lab = LABS[self.key]
        results, ok = feedback(lab, state, kit)
        h = [f"<h3>{escape(lab.title)}: feedback</h3><ul>"]
        for c in results:
            h.append(f"<li><b>{'PASS' if c.ok else 'NOT YET'}</b> - {escape(c.text)}"
                     + ("" if c.ok else f"<br><i>{escape(c.hint)}</i>") + "</li>")
        h.append("</ul>")
        if ok:
            h.append("<p><b>Lab complete.</b> Every check passed.</p>")
            if lab.reveal_expected and lab.expected:
                h.append("<p><b>Expected outcomes</b></p><ul>" + "".join(f"<li>{escape(t)}</li>" for t in lab.expected)
                         + "</ul>")
        else:
            h.append("<p>Not finished yet: follow the hints, then check again.</p>")
        self.view.setHtml("".join(h))
