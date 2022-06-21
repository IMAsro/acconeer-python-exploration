from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

import attrs

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from acconeer.exptool.a121._core import Criticality

from .types import PidgetMapping
from .utils import VerticalGroupBox


T = TypeVar("T")


class AttrsConfigEditor(QWidget, Generic[T]):
    _config: Optional[T]

    sig_update = Signal(object)

    def __init__(
        self, title: str, pidget_mapping: PidgetMapping, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent=parent)
        self._config = None
        self._pidget_mapping = pidget_mapping
        self.setLayout(QVBoxLayout(self))
        self.layout().setContentsMargins(0, 0, 0, 0)
        self.layout().setSpacing(11)
        group_box = VerticalGroupBox(title, parent=self)
        self.layout().addWidget(group_box)

        for aspect, (pidget, f) in self._pidget_mapping.items():
            pidget.sig_parameter_changed.connect(
                lambda val: self._update_config_aspect(aspect, val if (f is None) else f(val))
            )
            group_box.layout().addWidget(pidget)

    def set_data(self, config: Optional[T]) -> None:
        self._config = config

    def sync(self) -> None:
        self._update_pidgets()

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled and self._config is not None)

    def _broadcast(self) -> None:
        self.sig_update.emit(self._config)

    def _update_pidgets(self) -> None:
        if self._config is None:
            return

        for aspect, (pidget, _) in self._pidget_mapping.items():
            config_value = getattr(self._config, aspect)
            pidget.set_parameter(config_value)

    def _update_config_aspect(self, aspect: str, value: Any) -> None:
        if self._config is None:
            return

        try:
            self._config = attrs.evolve(self._config, **{aspect: value})
        except Exception as e:
            self._pidget_mapping[aspect][0].set_note_text(e.args[0], Criticality.ERROR)

        self._broadcast()
