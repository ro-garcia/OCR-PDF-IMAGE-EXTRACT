"""Ventana principal PySide6 para OCR Boletas."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw
from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config.settings import APP_NAME, OUTPUT_DIR, setup_logging
from core.image_processing import preprocess_for_ocr
from core.json_exporter import data_to_json, save_json, suggest_filename
from core.ocr_engine import OCRError, get_ocr_boxes, run_ocr
from core.parser import (
    build_product_table_from_compartments,
    empty_boleta_data,
    normalize_result,
    parse_boleta,
)
from core.pdf_utils import PDFError, render_first_page
from core.plan_cargue_extractor import extract_plan_cargue_compartments
from core.validators import validate_before_export


logger = logging.getLogger(__name__)


HEADER_FIELD_DEFINITIONS = [
    ("boleta_de_carga", "Boleta de carga"),
    ("terminal_direccion", "Terminal/Direccion"),
    ("contacto", "Contacto"),
    ("terminal", "Terminal"),
    ("conductor", "Conductor"),
    ("numero_tanque_siglas_unidad", "Numero tanque/siglas unidad"),
    ("numero_cabezal_cabezal", "Numero cabezal/cabezal"),
    ("fecha", "Fecha"),
    ("transportador", "Transportador"),
    ("hora_inicio_cargue", "Hora inicio cargue"),
    ("hora_final_cargue", "Hora final cargue"),
    ("anotacion", "Anotacion"),
]

PRODUCT_TABLE_COLUMNS = [
    ("numero_entrega", "Numero entrega"),
    ("nombre_cliente", "Nombre cliente"),
    ("nombre_producto", "Nombre producto"),
    ("cantidad", "Cantidad"),
]

COMPARTMENT_TABLE_COLUMNS = [
    ("numero_compartimiento", "No."),
    ("nombre_producto", "Nombre producto"),
    ("codigo_producto", "Codigo producto"),
    ("capacidad_de_cargue", "Capacidad"),
    ("cantidad_a_cargar", "Cant. a cargar"),
    ("cantidad_cargada", "Cant. cargada"),
    ("cantidad_total_en_transporte", "Total transporte"),
    ("temperatura_de_cargue", "Temperatura"),
    ("consumo_propio", "Consumo propio"),
]


class OCRWorker(QObject):
    """Ejecuta OCR en un hilo secundario."""

    finished = Signal(dict, str, str, list)
    error = Signal(str)
    status = Signal(str)

    def __init__(self, pdf_path: Path) -> None:
        super().__init__()
        self.pdf_path = pdf_path

    @Slot()
    def run(self) -> None:
        """Renderiza, preprocesa, ejecuta OCR y parsea la boleta."""

        try:
            self.status.emit("Renderizando PDF...")
            image = render_first_page(self.pdf_path)

            self.status.emit("Mejorando imagen...")
            processed_image = preprocess_for_ocr(image)

            self.status.emit("Ejecutando OCR...")
            ocr_text = run_ocr(processed_image)
            try:
                ocr_boxes = get_ocr_boxes(processed_image)
            except Exception:
                logger.exception("No se pudieron obtener cajas OCR")
                ocr_boxes = []

            warning = ""
            if not ocr_text.strip():
                warning = "El OCR finalizo, pero no se detecto texto en el documento."

            self.status.emit("Extrayendo campos...")
            data = parse_boleta(ocr_text, archivo_origen=str(self.pdf_path))
            self.status.emit("Leyendo tabla Plan de Cargue...")
            try:
                compartments = extract_plan_cargue_compartments(image)
            except Exception:
                logger.exception("No se pudo extraer la tabla Plan de Cargue")
                compartments = []

            if compartments:
                data["plan_de_cargue"]["compartimientos"] = compartments
                aggregated = build_product_table_from_compartments(
                    compartments,
                    numero_entrega=data["tabla_productos"][0]["numero_entrega"] if data["tabla_productos"] else "",
                    nombre_cliente=data["tabla_productos"][0]["nombre_cliente"] if data["tabla_productos"] else "",
                )
                if aggregated:
                    data["tabla_productos"] = aggregated
                data = normalize_result(data)

            self.finished.emit(data, warning, ocr_text, ocr_boxes)
        except (PDFError, OCRError) as exc:
            logger.exception("Error controlado durante OCR")
            self.error.emit(str(exc))
        except Exception as exc:
            logger.exception("Error inesperado durante OCR")
            self.error.emit("Ocurrio un error inesperado al procesar el documento.")


class MainWindow(QMainWindow):
    """Ventana principal de la aplicacion."""

    def __init__(self) -> None:
        super().__init__()
        setup_logging()
        self.setWindowTitle(APP_NAME)
        self.resize(1320, 860)

        self.current_pdf_path: Path | None = None
        self.current_data = empty_boleta_data()
        self.ocr_thread: QThread | None = None
        self.ocr_worker: OCRWorker | None = None
        self.header_inputs: dict[str, QLineEdit] = {}
        self.current_pdf_image: Image.Image | None = None
        self.highlight_boxes: list[dict] = []
        self.pdf_zoom_factor = 1.0
        self.pdf_base_scale = 1.0
        self.updating_ui = False

        self._build_ui()
        self._apply_styles()
        self._connect_signals()
        self._set_initial_state()

    def _build_ui(self) -> None:
        central = QWidget()
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.setObjectName("MainSplitter")

        left_column = QWidget()
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(self._build_header())
        left_layout.addWidget(self._build_content(), 1)

        main_splitter.addWidget(left_column)
        main_splitter.addWidget(self._build_form_panel())
        main_splitter.setStretchFactor(0, 5)
        main_splitter.setStretchFactor(1, 4)
        main_splitter.setSizes([1020, 860])

        root_layout.addWidget(main_splitter, 1)
        self.setCentralWidget(central)

        status_bar = QStatusBar()
        status_bar.showMessage("Listo")
        self.setStatusBar(status_bar)

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 18, 18, 18)
        layout.setSpacing(18)

        title_block = QWidget()
        title_layout = QVBoxLayout(title_block)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(8)
        title = QLabel("OCR Boletas")
        title.setObjectName("AppTitle")
        subtitle = QLabel("Procesamiento de Boletas PDF para extraer su información")
        subtitle.setObjectName("AppSubtitle")

        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)

        self.load_button = QPushButton("Cargar PDF")
        self.process_button = QPushButton("Procesar OCR")
        self.export_button = QPushButton("Exportar JSON")
        self.clear_button = QPushButton("Limpiar")

        self.load_button.setObjectName("PrimaryButton")
        self.process_button.setObjectName("PrimaryButton")
        self.export_button.setObjectName("SuccessButton")
        self.clear_button.setObjectName("HeaderSecondaryButton")

        for button in (self.load_button, self.process_button, self.export_button, self.clear_button):
            button.setMinimumSize(112, 62)
            button.setMaximumHeight(62)

        button_row = QHBoxLayout()
        button_row.setSpacing(14)
        button_row.addWidget(self.load_button)
        button_row.addWidget(self.process_button)
        button_row.addWidget(self.export_button)
        button_row.addWidget(self.clear_button)

        layout.addWidget(title_block, 1)
        layout.addLayout(button_row)
        return header

    def _build_toolbar(self) -> QWidget:
        toolbar = QFrame()
        toolbar.setObjectName("Toolbar")
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(10)

        self.load_button = QPushButton("Cargar PDF")
        self.process_button = QPushButton("Procesar OCR")
        self.export_button = QPushButton("Exportar JSON")
        self.clear_button = QPushButton("Limpiar")

        self.load_button.setObjectName("PrimaryButton")
        self.process_button.setObjectName("PrimaryButton")
        self.export_button.setObjectName("SuccessButton")
        self.clear_button.setObjectName("SecondaryButton")

        layout.addWidget(self.load_button)
        layout.addWidget(self.process_button)
        layout.addWidget(self.export_button)
        layout.addWidget(self.clear_button)
        layout.addStretch(1)
        return toolbar

    def _build_content(self) -> QWidget:
        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.addWidget(self._build_pdf_panel())
        left_splitter.addWidget(self._build_bottom_tabs())
        left_splitter.setStretchFactor(0, 4)
        left_splitter.setStretchFactor(1, 1)
        left_splitter.setSizes([660, 180])

        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(left_splitter)
        return wrapper

    def _build_pdf_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("Vista PDF")
        title.setObjectName("PanelTitle")
        self.zoom_out_button = QPushButton("-")
        self.zoom_reset_button = QPushButton("100%")
        self.zoom_in_button = QPushButton("+")
        self.zoom_out_button.setObjectName("IconButton")
        self.zoom_reset_button.setObjectName("SecondaryButton")
        self.zoom_in_button.setObjectName("IconButton")
        self.zoom_out_button.setToolTip("Alejar PDF")
        self.zoom_reset_button.setToolTip("Restablecer zoom")
        self.zoom_in_button.setToolTip("Acercar PDF")
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.zoom_out_button)
        title_row.addWidget(self.zoom_reset_button)
        title_row.addWidget(self.zoom_in_button)

        self.pdf_label = QLabel("Cargue un PDF para ver la primera pagina.")
        self.pdf_label.setObjectName("PdfPlaceholder")
        self.pdf_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pdf_label.setMinimumSize(560, 720)
        self.pdf_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

        self.pdf_scroll = QScrollArea()
        self.pdf_scroll.setObjectName("PdfScroll")
        self.pdf_scroll.setWidgetResizable(False)
        self.pdf_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pdf_scroll.setWidget(self.pdf_label)

        layout.addLayout(title_row)
        layout.addWidget(self.pdf_scroll, 1)
        return panel

    def _build_form_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        outer_layout = QVBoxLayout(panel)
        outer_layout.setContentsMargins(14, 14, 14, 14)
        outer_layout.setSpacing(12)

        title = QLabel("Informacion extraida")
        title.setObjectName("PanelTitle")
        outer_layout.addWidget(title)

        info_splitter = QSplitter(Qt.Orientation.Vertical)
        info_splitter.setObjectName("InfoSplitter")
        info_splitter.setChildrenCollapsible(False)
        info_splitter.setHandleWidth(8)

        header_section = QWidget()
        header_section.setObjectName("ResizableSection")
        header_layout = QVBoxLayout(header_section)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        section_header = QLabel("Encabezado")
        section_header.setObjectName("SectionTitle")
        header_layout.addWidget(section_header)

        form_container = QWidget()
        form_layout = QFormLayout(form_container)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(8)

        for key, label in HEADER_FIELD_DEFINITIONS:
            input_field = QLineEdit()
            input_field.setObjectName("DataInput")
            input_field.setClearButtonEnabled(True)
            self.header_inputs[key] = input_field
            form_layout.addRow(label, input_field)

        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setFrameShape(QFrame.Shape.NoFrame)
        form_scroll.setWidget(form_container)
        header_layout.addWidget(form_scroll, 1)
        header_section.setMinimumHeight(150)

        products_section = QWidget()
        products_section.setObjectName("ResizableSection")
        products_layout = QVBoxLayout(products_section)
        products_layout.setContentsMargins(0, 0, 0, 0)
        products_layout.setSpacing(8)
        products_title = QLabel("Tabla productos")
        products_title.setObjectName("SectionTitle")
        products_layout.addWidget(products_title)

        self.products_table = QTableWidget(0, 4)
        self.products_table.setObjectName("ProductsTable")
        self.products_table.setHorizontalHeaderLabels([label for _key, label in PRODUCT_TABLE_COLUMNS])
        self.products_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.products_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.products_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.products_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.products_table.verticalHeader().setVisible(False)
        self.products_table.setAlternatingRowColors(True)
        self.products_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        products_layout.addWidget(self.products_table, 1)

        product_buttons = QHBoxLayout()
        self.add_product_button = QPushButton("Agregar producto")
        self.remove_product_button = QPushButton("Eliminar producto seleccionado")
        self.add_product_button.setObjectName("SecondaryButton")
        self.remove_product_button.setObjectName("DangerButton")
        product_buttons.addWidget(self.add_product_button)
        product_buttons.addWidget(self.remove_product_button)
        products_layout.addLayout(product_buttons)
        products_section.setMinimumHeight(140)

        compartments_section = QWidget()
        compartments_section.setObjectName("ResizableSection")
        compartments_layout = QVBoxLayout(compartments_section)
        compartments_layout.setContentsMargins(0, 0, 0, 0)
        compartments_layout.setSpacing(8)
        compartments_title = QLabel("Plan de cargue")
        compartments_title.setObjectName("SectionTitle")
        compartments_layout.addWidget(compartments_title)

        self.compartments_table = QTableWidget(10, len(COMPARTMENT_TABLE_COLUMNS))
        self.compartments_table.setObjectName("ProductsTable")
        self.compartments_table.setHorizontalHeaderLabels([label for _key, label in COMPARTMENT_TABLE_COLUMNS])
        self.compartments_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.compartments_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in range(2, len(COMPARTMENT_TABLE_COLUMNS)):
            self.compartments_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.compartments_table.verticalHeader().setVisible(False)
        self.compartments_table.setAlternatingRowColors(True)
        self.compartments_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        compartments_layout.addWidget(self.compartments_table, 1)
        compartments_section.setMinimumHeight(180)

        info_splitter.addWidget(header_section)
        info_splitter.addWidget(products_section)
        info_splitter.addWidget(compartments_section)
        info_splitter.setStretchFactor(0, 2)
        info_splitter.setStretchFactor(1, 2)
        info_splitter.setStretchFactor(2, 3)
        info_splitter.setSizes([320, 230, 350])

        outer_layout.addWidget(info_splitter, 1)
        return panel

    def _build_bottom_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setObjectName("BottomTabs")

        self.ocr_text = QTextEdit()
        self.ocr_text.setReadOnly(True)
        self.ocr_text.setPlaceholderText("Aqui se mostrara el texto OCR completo.")
        tabs.addTab(self.ocr_text, "OCR completo")

        json_tab = QWidget()
        json_layout = QVBoxLayout(json_tab)
        json_layout.setContentsMargins(8, 8, 8, 8)
        json_layout.setSpacing(8)

        self.json_preview = QTextEdit()
        self.json_preview.setReadOnly(True)
        self.json_preview.setPlaceholderText("Aqui se mostrara la previsualizacion del JSON.")

        copy_row = QHBoxLayout()
        copy_row.addStretch(1)
        self.copy_json_button = QPushButton("Copiar JSON")
        self.copy_json_button.setObjectName("SecondaryButton")
        copy_row.addWidget(self.copy_json_button)

        json_layout.addWidget(self.json_preview, 1)
        json_layout.addLayout(copy_row)
        tabs.addTab(json_tab, "Vista JSON")
        return tabs

    def _connect_signals(self) -> None:
        self.load_button.clicked.connect(self.load_pdf)
        self.process_button.clicked.connect(self.process_ocr)
        self.export_button.clicked.connect(self.export_json)
        self.clear_button.clicked.connect(self.clear_all)
        self.add_product_button.clicked.connect(lambda _checked=False: self.add_product_row())
        self.remove_product_button.clicked.connect(self.remove_selected_product)
        self.copy_json_button.clicked.connect(self.copy_json_to_clipboard)
        self.zoom_out_button.clicked.connect(self.zoom_out_pdf)
        self.zoom_reset_button.clicked.connect(self.reset_pdf_zoom)
        self.zoom_in_button.clicked.connect(self.zoom_in_pdf)

        for input_field in self.header_inputs.values():
            input_field.textChanged.connect(lambda _value: self.refresh_json_preview())

        self.products_table.itemChanged.connect(lambda _item: self.refresh_json_preview())
        self.compartments_table.itemChanged.connect(lambda _item: self.refresh_json_preview())
        self.ocr_text.textChanged.connect(self.refresh_json_preview)

    def _set_initial_state(self) -> None:
        self.process_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.copy_json_button.setEnabled(False)
        self.refresh_json_preview()

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background: #f3f6fb;
                color: #1f2937;
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 10.5pt;
            }
            #Header {
                background: #111827;
                border: none;
            }
            #AppTitle {
                color: #ffffff;
                font-size: 22pt;
                font-weight: 700;
                letter-spacing: 0;
            }
            #AppSubtitle {
                color: #cbd5e1;
                font-size: 10.5pt;
                margin-top: 2px;
            }
            #Toolbar {
                background: #ffffff;
                border-bottom: 1px solid #dbe3ef;
            }
            QPushButton {
                min-height: 34px;
                padding: 7px 14px;
                border-radius: 6px;
                border: 1px solid #cbd5e1;
                font-weight: 600;
            }
            QPushButton:disabled {
                background: #e5e7eb;
                color: #9ca3af;
                border-color: #d1d5db;
            }
            #PrimaryButton {
                background: #2563eb;
                color: #ffffff;
                border-color: #1d4ed8;
            }
            #PrimaryButton:hover {
                background: #1d4ed8;
            }
            #SuccessButton {
                background: #0f766e;
                color: #ffffff;
                border-color: #0f766e;
            }
            #SuccessButton:hover {
                background: #115e59;
            }
            #SecondaryButton {
                background: #f8fafc;
                color: #1f2937;
                border-color: #cbd5e1;
            }
            #SecondaryButton:hover {
                background: #eef2f7;
            }
            #HeaderSecondaryButton {
                background: #f8fafc;
                color: #111827;
                border-color: #cbd5e1;
            }
            #HeaderSecondaryButton:hover {
                background: #e5eaf2;
            }
            #IconButton {
                background: #f8fafc;
                color: #1f2937;
                border-color: #cbd5e1;
                min-width: 36px;
                max-width: 36px;
                padding: 7px 0;
                font-size: 13pt;
                font-weight: 800;
            }
            #IconButton:hover {
                background: #eef2f7;
            }
            #DangerButton {
                background: #fff7ed;
                color: #9a3412;
                border-color: #fdba74;
            }
            #DangerButton:hover {
                background: #ffedd5;
            }
            #Panel {
                background: #ffffff;
                border: 1px solid #dbe3ef;
                border-radius: 8px;
            }
            #PanelTitle {
                color: #111827;
                font-size: 14pt;
                font-weight: 700;
            }
            #SectionTitle {
                color: #334155;
                font-weight: 700;
                padding-top: 4px;
            }
            #ResizableSection {
                background: #ffffff;
            }
            #InfoSplitter::handle {
                background: #dbe3ef;
                border-radius: 3px;
                margin: 2px 80px;
            }
            #InfoSplitter::handle:hover {
                background: #93c5fd;
            }
            #PdfScroll, QScrollArea {
                background: #eef2f7;
                border: 1px solid #dbe3ef;
                border-radius: 6px;
            }
            #PdfPlaceholder {
                color: #64748b;
                background: #eef2f7;
                border: none;
            }
            QLineEdit, QTextEdit, QTableWidget {
                background: #ffffff;
                color: #111827;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                selection-background-color: #bfdbfe;
            }
            QLineEdit {
                min-height: 30px;
                padding: 4px 8px;
            }
            QTextEdit {
                padding: 8px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 10pt;
            }
            QTableWidget {
                gridline-color: #e5e7eb;
                alternate-background-color: #f8fafc;
            }
            QHeaderView::section {
                background: #eaf0f8;
                color: #334155;
                border: none;
                border-right: 1px solid #dbe3ef;
                padding: 7px;
                font-weight: 700;
            }
            QTabWidget::pane {
                border: 1px solid #dbe3ef;
                border-radius: 8px;
                background: #ffffff;
            }
            QTabBar::tab {
                background: #eaf0f8;
                color: #334155;
                padding: 8px 14px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #111827;
                font-weight: 700;
            }
            QStatusBar {
                background: #ffffff;
                color: #334155;
                border-top: 1px solid #dbe3ef;
            }
            """
        )

    @Slot()
    def load_pdf(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar PDF",
            str(Path.home()),
            "Archivos PDF (*.pdf)",
        )
        if not file_path:
            self.statusBar().showMessage("PDF no seleccionado")
            return

        try:
            path = Path(file_path)
            preview_image = render_first_page(path)
            self.current_pdf_path = path
            self.current_data = empty_boleta_data(str(path))
            self.highlight_boxes = []
            self.pdf_zoom_factor = 1.0
            self._show_pdf_image(preview_image)
            self.apply_data_to_form(self.current_data)
            self.process_button.setEnabled(True)
            self.export_button.setEnabled(True)
            self.copy_json_button.setEnabled(True)
            self.statusBar().showMessage("PDF cargado")
        except PDFError as exc:
            logger.exception("Error al cargar PDF")
            self._show_error("No se pudo cargar el PDF", str(exc))
            self.statusBar().showMessage("Error")
        except Exception as exc:
            logger.exception("Error inesperado al cargar PDF")
            self._show_error("No se pudo cargar el PDF", "Ocurrio un error inesperado al abrir el archivo.")
            self.statusBar().showMessage("Error")

    def _show_pdf_image(self, image: Image.Image) -> None:
        self.current_pdf_image = image.convert("RGB")
        self.pdf_base_scale = min(900 / max(self.current_pdf_image.width, 1), 1.0)
        self._render_pdf_preview()

    def _render_pdf_preview(self) -> None:
        if self.current_pdf_image is None:
            return

        image = self.current_pdf_image.copy()
        if self.highlight_boxes:
            draw = ImageDraw.Draw(image)
            for box in self.highlight_boxes:
                x = int(box.get("x", 0))
                y = int(box.get("y", 0))
                w = int(box.get("w", 0))
                h = int(box.get("h", 0))
                if w <= 0 or h <= 0:
                    continue
                draw.rectangle((x, y, x + w, y + h), outline=(0, 102, 255), width=4)

        scale = max(0.2, min(self.pdf_base_scale * self.pdf_zoom_factor, 4.0))
        display_width = max(1, int(image.width * scale))
        display_height = max(1, int(image.height * scale))
        image = image.resize((display_width, display_height), Image.Resampling.LANCZOS)

        pixmap = self._pil_to_pixmap(image)
        self.pdf_label.setPixmap(pixmap)
        self.pdf_label.setText("")
        self.pdf_label.resize(pixmap.size())
        self.zoom_reset_button.setText(f"{int(self.pdf_zoom_factor * 100)}%")

    @Slot()
    def zoom_in_pdf(self) -> None:
        self.pdf_zoom_factor = min(self.pdf_zoom_factor + 0.15, 3.0)
        self._render_pdf_preview()

    @Slot()
    def zoom_out_pdf(self) -> None:
        self.pdf_zoom_factor = max(self.pdf_zoom_factor - 0.15, 0.35)
        self._render_pdf_preview()

    @Slot()
    def reset_pdf_zoom(self) -> None:
        self.pdf_zoom_factor = 1.0
        self._render_pdf_preview()

    @staticmethod
    def _pil_to_pixmap(image: Image.Image) -> QPixmap:
        rgb_image = image.convert("RGB")
        width, height = rgb_image.size
        bytes_per_line = width * 3
        q_image = QImage(
            rgb_image.tobytes(),
            width,
            height,
            bytes_per_line,
            QImage.Format.Format_RGB888,
        )
        return QPixmap.fromImage(q_image.copy())

    @Slot()
    def process_ocr(self) -> None:
        if not self.current_pdf_path:
            self._show_info("Seleccione un PDF", "Primero cargue un archivo PDF.")
            return

        self._set_processing_state(True)
        self.statusBar().showMessage("OCR procesando")

        self.ocr_thread = QThread(self)
        self.ocr_worker = OCRWorker(self.current_pdf_path)
        self.ocr_worker.moveToThread(self.ocr_thread)

        self.ocr_thread.started.connect(self.ocr_worker.run)
        self.ocr_worker.status.connect(self.statusBar().showMessage)
        self.ocr_worker.finished.connect(self._on_ocr_finished)
        self.ocr_worker.error.connect(self._on_ocr_error)
        self.ocr_worker.finished.connect(self.ocr_thread.quit)
        self.ocr_worker.error.connect(self.ocr_thread.quit)
        self.ocr_thread.finished.connect(self.ocr_worker.deleteLater)
        self.ocr_thread.finished.connect(self.ocr_thread.deleteLater)
        self.ocr_thread.finished.connect(self._clear_worker_refs)
        self.ocr_thread.start()

    def _set_processing_state(self, is_processing: bool) -> None:
        self.load_button.setEnabled(not is_processing)
        self.process_button.setEnabled(not is_processing and self.current_pdf_path is not None)
        self.export_button.setEnabled(not is_processing and self.current_pdf_path is not None)
        self.clear_button.setEnabled(not is_processing)

    @Slot(dict, str, str, list)
    def _on_ocr_finished(self, data: dict, warning: str, ocr_text: str, ocr_boxes: list) -> None:
        self.current_data = data
        self.highlight_boxes = ocr_boxes
        self._render_pdf_preview()
        self.apply_data_to_form(data, ocr_text)
        self.statusBar().showMessage("OCR completado")
        self._set_processing_state(False)

        if warning:
            self._show_warning("OCR completado con advertencia", warning)
        else:
            self._show_info("OCR completado", "La informacion fue extraida y cargada en el formulario.")

    @Slot(str)
    def _on_ocr_error(self, message: str) -> None:
        self._set_processing_state(False)
        self.statusBar().showMessage("Error")
        self._show_error("Error de OCR", message)

    @Slot()
    def _clear_worker_refs(self) -> None:
        self.ocr_thread = None
        self.ocr_worker = None

    def apply_data_to_form(self, data: dict, ocr_text: str = "") -> None:
        data = normalize_result(data)
        self.updating_ui = True
        try:
            for key, input_field in self.header_inputs.items():
                input_field.setText(str(data["encabezado"].get(key, "") or ""))

            self.products_table.setRowCount(0)
            for product in data.get("tabla_productos", []):
                self.add_product_row(product)

            self._apply_compartments_to_table(data["plan_de_cargue"]["compartimientos"])

            self.ocr_text.setPlainText(ocr_text)
        finally:
            self.updating_ui = False

        self.refresh_json_preview()

    @Slot()
    def add_product_row(
        self,
        product: dict | None = None,
    ) -> None:
        product = product or {}
        row = self.products_table.rowCount()
        self.products_table.insertRow(row)
        for column, (key, _label) in enumerate(PRODUCT_TABLE_COLUMNS):
            self.products_table.setItem(row, column, QTableWidgetItem(str(product.get(key, "") or "")))
        self.refresh_json_preview()

    def _apply_compartments_to_table(self, compartments: list[dict[str, str]]) -> None:
        self.compartments_table.setRowCount(10)
        for row in range(10):
            source = compartments[row] if row < len(compartments) else {}
            for column, (key, _label) in enumerate(COMPARTMENT_TABLE_COLUMNS):
                value = source.get(key, "") if isinstance(source, dict) else ""
                if key == "numero_compartimiento":
                    value = str(row + 1)
                self.compartments_table.setItem(row, column, QTableWidgetItem(str(value or "")))

    @Slot()
    def remove_selected_product(self) -> None:
        selected_rows = sorted(
            {index.row() for index in self.products_table.selectedIndexes()},
            reverse=True,
        )
        if not selected_rows:
            self._show_info("Seleccione un producto", "Seleccione una fila de la tabla para eliminarla.")
            return

        for row in selected_rows:
            self.products_table.removeRow(row)
        self.refresh_json_preview()

    def collect_form_data(self) -> dict:
        data = empty_boleta_data()

        for key, input_field in self.header_inputs.items():
            data["encabezado"][key] = input_field.text().strip()

        products: list[dict[str, str]] = []
        for row in range(self.products_table.rowCount()):
            product = {}
            for column, (key, _label) in enumerate(PRODUCT_TABLE_COLUMNS):
                item = self.products_table.item(row, column)
                product[key] = item.text().strip() if item else ""
            if any(product.values()):
                products.append(product)

        compartments: list[dict[str, str]] = []
        for row in range(10):
            compartment = {}
            for column, (key, _label) in enumerate(COMPARTMENT_TABLE_COLUMNS):
                item = self.compartments_table.item(row, column)
                value = item.text().strip() if item else ""
                if key == "numero_compartimiento":
                    value = str(row + 1)
                compartment[key] = value
            compartments.append(compartment)

        data["tabla_productos"] = products
        data["plan_de_cargue"]["compartimientos"] = compartments
        return normalize_result(data)

    @Slot()
    def refresh_json_preview(self) -> None:
        if self.updating_ui:
            return
        data = self.collect_form_data()
        self.json_preview.setPlainText(data_to_json(data))

    @Slot()
    def export_json(self) -> None:
        if not self.current_pdf_path:
            self._show_info("Seleccione un PDF", "Primero cargue un archivo PDF.")
            return

        data = self.collect_form_data()
        warnings = validate_before_export(data)
        if warnings:
            details = "\n".join(f"- {warning}" for warning in warnings)
            response = QMessageBox.question(
                self,
                "Campos importantes vacios",
                "Hay campos importantes vacios. Desea exportar de todos modos?\n\n" + details,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if response != QMessageBox.StandardButton.Yes:
                return

        suggested_path = OUTPUT_DIR / suggest_filename(data)
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar JSON",
            str(suggested_path),
            "Archivos JSON (*.json)",
        )
        if not file_path:
            return

        path = Path(file_path)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")

        try:
            saved_path = save_json(data, path)
            self.statusBar().showMessage("JSON exportado")
            self._show_info("JSON exportado", f"El archivo se guardo correctamente en:\n{saved_path}")
        except PermissionError as exc:
            logger.exception("Error de permisos al guardar JSON")
            self.statusBar().showMessage("Error")
            self._show_error("No se pudo guardar", "No tiene permisos para guardar en esa ubicacion.")
        except Exception as exc:
            logger.exception("Error al guardar JSON")
            self.statusBar().showMessage("Error")
            self._show_error("No se pudo guardar", "Ocurrio un error al exportar el JSON.")

    @Slot()
    def copy_json_to_clipboard(self) -> None:
        QApplication.clipboard().setText(self.json_preview.toPlainText())
        self.statusBar().showMessage("JSON copiado al portapapeles")

    @Slot()
    def clear_all(self) -> None:
        self.current_pdf_path = None
        self.current_data = empty_boleta_data()
        self.current_pdf_image = None
        self.highlight_boxes = []
        self.pdf_zoom_factor = 1.0
        self.pdf_base_scale = 1.0
        self.pdf_label.clear()
        self.pdf_label.setText("Cargue un PDF para ver la primera pagina.")
        self.pdf_label.resize(560, 720)
        self.zoom_reset_button.setText("100%")
        self.apply_data_to_form(self.current_data)
        self.process_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.copy_json_button.setEnabled(False)
        self.statusBar().showMessage("Listo para cargar otro PDF")

    def _show_info(self, title: str, message: str) -> None:
        QMessageBox.information(self, title, message)

    def _show_warning(self, title: str, message: str) -> None:
        QMessageBox.warning(self, title, message)

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)
