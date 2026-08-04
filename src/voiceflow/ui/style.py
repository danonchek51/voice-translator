"""Тёмная тема приложения.

Одна палитра и один лист стилей на всё приложение: плашка, окно настроек
и мастер берут цвета отсюда, поэтому оформление не разъезжается.

Принципы оформления: глубокий тёмный фон без чистого чёрного, содержимое
собрано в скруглённые карточки, один акцентный цвет на действие, рамок
и разделителей минимум — их роль выполняет разница фонов.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Palette:
    """Цвета интерфейса."""

    #: Фон окна.
    base: str = "#141517"
    #: Фон карточки поверх окна.
    surface: str = "#1c1e22"
    #: Фон элемента ввода и наведения.
    elevated: str = "#242730"
    #: Едва заметная линия там, где без неё не обойтись.
    line: str = "#2c303a"
    text: str = "#e8eaed"
    text_dim: str = "#9ba1ac"
    text_faint: str = "#6b7280"
    accent: str = "#4c8dff"
    accent_hover: str = "#5f9bff"
    accent_dim: str = "#2f5aa8"
    danger: str = "#ef4444"
    success: str = "#22c55e"
    warning: str = "#eab308"


PALETTE = Palette()

#: Скругления и отступы в пикселях.
RADIUS = 10
RADIUS_SMALL = 6
GAP = 10
PADDING = 14

#: Высота элементов ввода: одинаковая, иначе строки формы «прыгают».
CONTROL_HEIGHT = 30

FONT_FAMILY = "Segoe UI"
FONT_SIZE_PT = 10
MONO_FAMILY = "Cascadia Mono, Consolas, monospace"


def stylesheet(palette: Palette = PALETTE) -> str:
    """Лист стилей для всего приложения.

    Свойство ``role`` у виджета задаёт роль надписи: ``hint`` — пояснение
    мелким серым, ``accent`` — выделенная строка итога.
    """
    p = palette
    return f"""
* {{
    font-family: "{FONT_FAMILY}";
    font-size: {FONT_SIZE_PT}pt;
}}

QWidget {{
    background-color: {p.base};
    color: {p.text};
}}

QDialog, QMainWindow, QWizard {{
    background-color: {p.base};
}}

QLabel {{
    background: transparent;
    color: {p.text};
}}

QLabel[role="hint"] {{
    color: {p.text_faint};
    font-size: {FONT_SIZE_PT - 1}pt;
    padding-left: 22px;
    padding-bottom: 4px;
}}

QLabel[role="accent"] {{
    color: {p.accent};
    padding-top: 6px;
}}

/* --- Карточки ------------------------------------------------------- */

QGroupBox {{
    background-color: {p.surface};
    border: none;
    border-radius: {RADIUS}px;
    margin-top: 18px;
    padding: {PADDING}px;
    font-weight: 600;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 2px;
    padding: 0 0 6px 0;
    color: {p.text_dim};
    font-weight: 600;
}}

/* Карточка без заголовка: верхний отступ под заголовок не нужен,
   иначе содержимое обрезается по нижней границе. */
QGroupBox#card {{
    margin-top: 0;
}}

/* --- Вкладки -------------------------------------------------------- */

QTabWidget::pane {{
    border: none;
    background-color: {p.base};
    top: -1px;
}}

QTabBar {{
    background: transparent;
    qproperty-drawBase: 0;
}}

QTabBar::tab {{
    background: transparent;
    color: {p.text_dim};
    padding: 8px 16px;
    margin-right: 2px;
    border: none;
    border-radius: {RADIUS_SMALL}px;
}}

QTabBar::tab:hover {{
    background-color: {p.elevated};
    color: {p.text};
}}

QTabBar::tab:selected {{
    background-color: {p.elevated};
    color: {p.text};
    font-weight: 600;
}}

/* --- Кнопки --------------------------------------------------------- */

QPushButton {{
    background-color: {p.elevated};
    color: {p.text};
    border: none;
    border-radius: {RADIUS_SMALL}px;
    padding: 7px 14px;
    min-height: {CONTROL_HEIGHT - 14}px;
}}

QPushButton:hover {{
    background-color: {p.line};
}}

QPushButton:pressed {{
    background-color: {p.accent_dim};
}}

QPushButton:disabled {{
    color: {p.text_faint};
    background-color: {p.surface};
}}

QPushButton:default {{
    background-color: {p.accent};
    color: #ffffff;
    font-weight: 600;
}}

QPushButton:default:hover {{
    background-color: {p.accent_hover};
}}

/* --- Переключатели вместо галочек ------------------------------------ */

QCheckBox {{
    spacing: 10px;
    padding: 5px 0;
    background: transparent;
}}

/* Ползунок-переключатель без картинки нарисовать нельзя, а пилюля без
   бегунка читается двусмысленно. Поэтому индикатор — скруглённый квадрат:
   пустой с рамкой означает «выключено», залитый акцентом — «включено». */
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 2px solid {p.line};
    background-color: transparent;
}}

QCheckBox::indicator:hover {{
    border-color: {p.text_faint};
}}

QCheckBox::indicator:checked {{
    background-color: {p.accent};
    border: 2px solid {p.accent};
}}

QCheckBox::indicator:checked:hover {{
    background-color: {p.accent_hover};
    border-color: {p.accent_hover};
}}

QCheckBox::indicator:disabled {{
    border-color: {p.surface};
}}

QCheckBox:disabled {{
    color: {p.text_faint};
}}

QRadioButton {{
    spacing: 10px;
    padding: 4px 0;
    background: transparent;
}}

QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 9px;
    border: 2px solid {p.line};
    background-color: transparent;
}}

QRadioButton::indicator:hover {{
    border-color: {p.text_faint};
}}

QRadioButton::indicator:checked {{
    border: 2px solid {p.accent};
    background-color: {p.accent};
}}

/* --- Поля ввода ----------------------------------------------------- */

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {p.elevated};
    color: {p.text};
    border: 1px solid transparent;
    border-radius: {RADIUS_SMALL}px;
    padding: 5px 8px;
    min-height: {CONTROL_HEIGHT - 12}px;
    selection-background-color: {p.accent};
}}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {p.accent};
}}

QLineEdit:disabled, QComboBox:disabled {{
    color: {p.text_faint};
}}

QComboBox::drop-down {{
    border: none;
    width: 22px;
}}

QComboBox QAbstractItemView {{
    background-color: {p.elevated};
    color: {p.text};
    border: 1px solid {p.line};
    border-radius: {RADIUS_SMALL}px;
    padding: 4px;
    outline: none;
    selection-background-color: {p.accent};
}}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background-color: {p.line};
    border: none;
    width: 16px;
}}

QPlainTextEdit, QTextEdit {{
    background-color: {p.elevated};
    color: {p.text};
    border: 1px solid transparent;
    border-radius: {RADIUS_SMALL}px;
    padding: 8px;
    selection-background-color: {p.accent};
}}

QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {p.accent};
}}

/* --- Списки и таблицы ----------------------------------------------- */

QListWidget, QTreeWidget {{
    background-color: {p.elevated};
    color: {p.text};
    border: none;
    border-radius: {RADIUS_SMALL}px;
    padding: 4px;
    outline: none;
}}

QListWidget::item, QTreeWidget::item {{
    padding: 6px 8px;
    border-radius: {RADIUS_SMALL - 2}px;
}}

QListWidget::item:hover, QTreeWidget::item:hover {{
    background-color: {p.line};
}}

QListWidget::item:selected, QTreeWidget::item:selected {{
    background-color: {p.accent};
    color: #ffffff;
}}

QHeaderView::section {{
    background-color: {p.surface};
    color: {p.text_dim};
    border: none;
    padding: 6px 8px;
    font-weight: 600;
}}

/* --- Прочее --------------------------------------------------------- */

QSlider::groove:horizontal {{
    height: 4px;
    background-color: {p.line};
    border-radius: 2px;
}}

QSlider::sub-page:horizontal {{
    background-color: {p.accent};
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 7px;
    background-color: {p.text};
}}

QProgressBar {{
    background-color: {p.elevated};
    border: none;
    border-radius: {RADIUS_SMALL}px;
    height: 6px;
    text-align: center;
    color: transparent;
}}

QProgressBar::chunk {{
    background-color: {p.accent};
    border-radius: {RADIUS_SMALL}px;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background-color: {p.line};
    border-radius: 5px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {p.text_faint};
}}

QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    height: 0;
    width: 0;
    background: transparent;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
}}

QScrollBar::handle:horizontal {{
    background-color: {p.line};
    border-radius: 5px;
    min-width: 30px;
}}

QSplitter::handle {{
    background-color: transparent;
    width: {GAP}px;
}}

QToolTip {{
    background-color: {p.elevated};
    color: {p.text};
    border: 1px solid {p.line};
    border-radius: {RADIUS_SMALL}px;
    padding: 6px 8px;
}}

QMenu {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.line};
    border-radius: {RADIUS_SMALL}px;
    padding: 6px;
}}

QMenu::item {{
    padding: 7px 22px 7px 14px;
    border-radius: {RADIUS_SMALL - 2}px;
}}

QMenu::item:selected {{
    background-color: {p.accent};
    color: #ffffff;
}}

QMenu::item:disabled {{
    color: {p.text_faint};
}}

QMenu::separator {{
    height: 1px;
    background-color: {p.line};
    margin: 5px 8px;
}}

QMessageBox, QFileDialog {{
    background-color: {p.base};
}}

/* Правило вида «QWizard QWidget» здесь недопустимо: по специфичности оно
   перебило бы QPushButton, и кнопки внутри мастера остались бы без фона. */

/* Плашка рисует себя сама в paintEvent: общий фон ей мешает,
   поэтому она и всё внутри неё остаются прозрачными. */
#overlay, #overlay QWidget, #overlay QLabel {{
    background: transparent;
    border: none;
}}
"""


def apply_to(app: object) -> None:
    """Включает тёмную тему для всего приложения.

    Помимо листа стилей задаётся палитра Qt: без неё системные диалоги
    остаются светлыми и режут глаз на тёмном фоне.
    """
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QApplication

    if not isinstance(app, QApplication):
        return

    p = PALETTE
    qt_palette = QPalette()
    qt_palette.setColor(QPalette.ColorRole.Window, QColor(p.base))
    qt_palette.setColor(QPalette.ColorRole.WindowText, QColor(p.text))
    qt_palette.setColor(QPalette.ColorRole.Base, QColor(p.elevated))
    qt_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(p.surface))
    qt_palette.setColor(QPalette.ColorRole.Text, QColor(p.text))
    qt_palette.setColor(QPalette.ColorRole.Button, QColor(p.elevated))
    qt_palette.setColor(QPalette.ColorRole.ButtonText, QColor(p.text))
    qt_palette.setColor(QPalette.ColorRole.Highlight, QColor(p.accent))
    qt_palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    qt_palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(p.elevated))
    qt_palette.setColor(QPalette.ColorRole.ToolTipText, QColor(p.text))
    qt_palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(p.text_faint))
    qt_palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(p.text_faint)
    )
    qt_palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(p.text_faint)
    )

    app.setStyle("Fusion")
    app.setPalette(qt_palette)
    app.setStyleSheet(stylesheet())
