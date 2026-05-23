"""Per-layer QGIS expression filter dialog with field list and function browser."""

from __future__ import annotations

from typing import ClassVar

from qgis.core import (
    QgsExpression,
    QgsFeatureRequest,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class SQLFilterDialog(QDialog):
    """Per-layer QGIS expression filter editor.

    Signals
    -------
    filter_applied(layer_id: str, expression: str)
    """

    filter_applied = pyqtSignal(str, str)

    def __init__(
        self,
        layer_items: list[tuple[str, str]] | None = None,
        current_filters: dict[str, str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._layer_items: list[tuple[str, str]] = layer_items or []
        self.current_filters: dict[str, str] = dict(current_filters or {})
        self._current_layer: QgsVectorLayer | None = None

        self.setWindowTitle("Feature Filter (QGIS Expression)")
        self.setMinimumWidth(860)
        self.setMinimumHeight(640)
        self.setModal(False)

        self._build_ui()
        self._populate_layer_combo()
        self._populate_expression_tree()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        title = QLabel("Feature Filter - QGIS Expression")
        f = QFont()
        f.setPointSize(11)
        f.setBold(True)
        title.setFont(f)
        layout.addWidget(title)

        layer_row = QHBoxLayout()
        layer_row.addWidget(QLabel("Layer:"))
        self._layer_combo = QComboBox()
        self._layer_combo.currentIndexChanged.connect(self._on_layer_changed)
        layer_row.addWidget(self._layer_combo)
        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color: #777; font-size: 9pt;")
        layer_row.addWidget(self._info_label)
        layer_row.addStretch()
        layout.addLayout(layer_row)

        editor_label = QLabel("Expression (WHERE clause):")
        editor_label.setStyleSheet("font-weight:bold; font-size:10pt;")
        layout.addWidget(editor_label)

        self._editor = QPlainTextEdit()
        self._editor.setPlaceholderText(
            "Examples:\n"
            "\"type\" = 'school'\n"
            '"population" > 5000 AND "population" < 50000\n'
            "\"name\" LIKE '%Park%'\n"
            'LENGTH("description") > 0',
        )
        mono = QFont("Courier New" if Qt is not None else "monospace")
        mono.setPointSize(10)
        self._editor.setFont(mono)
        self._editor.setMinimumHeight(110)
        layout.addWidget(self._editor)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        fields_w = QWidget()
        fl = QVBoxLayout(fields_w)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.addWidget(QLabel("Fields (double-click to insert):"))
        self._field_list = QListWidget()
        self._field_list.itemDoubleClicked.connect(self._insert_field)
        fl.addWidget(self._field_list)
        splitter.addWidget(fields_w)

        expr_w = QWidget()
        el = QVBoxLayout(expr_w)
        el.setContentsMargins(0, 0, 0, 0)
        self._expr_search = QComboBox()
        self._expr_search.setEditable(True)
        self._expr_search.setPlaceholderText("Search functions...")
        self._expr_search.currentTextChanged.connect(self._filter_tree)
        el.addWidget(self._expr_search)
        self._expr_tree = QTreeWidget()
        self._expr_tree.setHeaderLabel("Functions & Operators")
        self._expr_tree.itemDoubleClicked.connect(self._insert_expression)
        el.addWidget(self._expr_tree)
        splitter.addWidget(expr_w)

        splitter.setSizes([400, 420])
        layout.addWidget(splitter)

        val_row = QHBoxLayout()
        self._validate_btn = QPushButton("Validate")
        self._validate_btn.setMaximumWidth(200)
        self._validate_btn.clicked.connect(self._validate)
        val_row.addWidget(self._validate_btn)
        val_row.addStretch()
        layout.addLayout(val_row)

        self._result_label = QLabel("")
        self._result_label.setWordWrap(True)
        self._result_label.setMinimumHeight(44)
        self._result_label.setStyleSheet(
            "font-size:9pt; padding:6px; border-radius:3px; background:#f5f5f5;",
        )
        layout.addWidget(self._result_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear)
        btn_row.addWidget(clear_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        apply_btn = QPushButton("Apply Filter")
        apply_btn.setStyleSheet(
            "background:#3a7f46; color:white; font-weight:bold; padding:5px 14px;",
        )
        apply_btn.clicked.connect(self._apply)
        btn_row.addWidget(apply_btn)

        layout.addLayout(btn_row)

    def _populate_layer_combo(self) -> None:
        """Populate the layer combo from the current layer_items list."""
        prev_id = self._layer_combo.currentData()
        self._layer_combo.blockSignals(True)
        self._layer_combo.clear()

        restore_idx = 0
        for idx, (layer_id, export_name) in enumerate(self._layer_items):
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer and isinstance(layer, QgsVectorLayer):
                n = layer.featureCount()
                filt = self.current_filters.get(layer_id, "")
                label = f"{export_name}  ({n} features)"
                if filt:
                    label += "  [filtered]"
                self._layer_combo.addItem(label, layer_id)
                if layer_id == prev_id:
                    restore_idx = idx

        self._layer_combo.blockSignals(False)

        if self._layer_combo.count() > 0:
            self._layer_combo.setCurrentIndex(restore_idx)
            self._on_layer_changed(restore_idx)

    def update_layer_items(self, layer_items: list[tuple[str, str]]) -> None:
        """Replace the layer list and repopulate the combo."""
        self._layer_items = layer_items
        self._populate_layer_combo()

    def _on_layer_changed(self, index: int) -> None:
        """Load the expression for the newly selected layer."""
        if index < 0 or self._layer_combo.count() == 0:
            self._current_layer = None
            self._field_list.clear()
            self._info_label.setText("")
            return

        layer_id = self._layer_combo.itemData(index)
        self._current_layer = QgsProject.instance().mapLayer(layer_id)

        if self._current_layer:
            n = self._current_layer.featureCount()
            self._info_label.setText(f"{n} features")
            self._populate_fields()
            expr = self.current_filters.get(layer_id, "")
            self._editor.setPlainText(expr)
        self._result_label.setText("")

    def _populate_fields(self) -> None:
        """Fill the field list for the current layer."""
        self._field_list.clear()
        if not self._current_layer:
            return
        for field in self._current_layer.fields():
            item = QListWidgetItem(f"{field.name()}  ({field.typeName()})")
            item.setData(Qt.ItemDataRole.UserRole, field.name())
            self._field_list.addItem(item)

    def _insert_field(self, item: QListWidgetItem) -> None:
        cursor = self._editor.textCursor()
        cursor.insertText(f'"{item.data(Qt.ItemDataRole.UserRole)}"')
        self._editor.setTextCursor(cursor)
        self._editor.setFocus()

    _CATEGORIES: ClassVar[dict[str, list[tuple[str, str]]]] = {
        "Operators": [
            ("=", "Equal"),
            ("!=", "Not equal"),
            ("<", "Less than"),
            (">", "Greater than"),
            ("<=", "Less or equal"),
            (">=", "Greater or equal"),
            ("AND", "Logical AND"),
            ("OR", "Logical OR"),
            ("NOT", "Logical NOT"),
            ("LIKE", "Pattern match"),
            ("ILIKE", "Case-insensitive LIKE"),
            ("IS NULL", "Null check"),
            ("IS NOT NULL", "Non-null check"),
            ("IN (...)", "Value in list"),
        ],
        "String": [
            ("upper( )", "Uppercase"),
            ("lower( )", "Lowercase"),
            ("title( )", "Title case"),
            ("length( )", "String length"),
            ("trim( )", "Trim whitespace"),
            ("substr( string, start, len )", "Substring"),
            ("concat( val1, val2 )", "Concatenate"),
            ("replace( string, old, new )", "Replace"),
            ("regexp_match( string, pattern )", "Regex match"),
            ("like( string, pattern )", "LIKE"),
        ],
        "Math": [
            ("abs( val )", "Absolute value"),
            ("round( val, dp )", "Round"),
            ("floor( val )", "Floor"),
            ("ceil( val )", "Ceiling"),
            ("sqrt( val )", "Square root"),
            ("pi( )", "π"),
            ("log( val )", "Natural log"),
            ("log10( val )", "Log base 10"),
        ],
        "Date / Time": [
            ("now( )", "Current datetime"),
            ("today( )", "Today's date"),
            ("year( date )", "Year"),
            ("month( date )", "Month"),
            ("day( date )", "Day"),
            ("hour( datetime )", "Hour"),
            ("minute( datetime )", "Minute"),
            ("age( date1, date2 )", "Difference"),
        ],
        "Conditionals": [
            ("CASE WHEN cond THEN val ELSE other END", "Case expression"),
            ("coalesce( v1, v2 )", "First non-null"),
            ("if( cond, true_val, false_val )", "If-then-else"),
            ("nullif( v1, v2 )", "Null if equal"),
        ],
        "Geometry": [
            ("$area", "Feature area"),
            ("$length", "Feature length"),
            ("$perimeter", "Perimeter"),
            ("$x", "X centroid"),
            ("$y", "Y centroid"),
            ("area( geom )", "Area of geometry"),
            ("length( geom )", "Length of geometry"),
            ("perimeter( geom )", "Perimeter of geometry"),
            ("buffer( geom, dist )", "Buffer"),
            ("centroid( geom )", "Centroid"),
            ("num_geometries( geom )", "Part count"),
        ],
        "Record": [
            ("$id", "Feature ID"),
            ("attribute( 'field' )", "Attribute value"),
            ("$currentfeature", "Current feature object"),
        ],
        "Type conversion": [
            ("to_int( val )", "To integer"),
            ("to_real( val )", "To decimal"),
            ("to_string( val )", "To string"),
            ("to_date( val )", "To date"),
            ("to_datetime( val )", "To datetime"),
        ],
    }

    def _populate_expression_tree(self) -> None:
        """Build the function/operator tree from _CATEGORIES."""
        self._expr_tree.clear()
        for category, funcs in self._CATEGORIES.items():
            cat_item = QTreeWidgetItem([category])
            cat_item.setExpanded(False)
            for func, desc in funcs:
                child = QTreeWidgetItem([func])
                child.setToolTip(0, desc)
                child.setData(0, Qt.ItemDataRole.UserRole, func)
                cat_item.addChild(child)
            self._expr_tree.addTopLevelItem(cat_item)

    def _filter_tree(self, text: str) -> None:
        """Filter the expression tree by the search text."""
        txt = text.lower()
        for i in range(self._expr_tree.topLevelItemCount()):
            cat = self._expr_tree.topLevelItem(i)
            visible = False
            for j in range(cat.childCount()):
                child = cat.child(j)
                match = not txt or txt in child.text(0).lower()
                child.setHidden(not match)
                if match:
                    visible = True
            cat.setHidden(not visible)
            if visible and txt:
                cat.setExpanded(True)

    def _insert_expression(self, item: QTreeWidgetItem, _col: int) -> None:
        if item.childCount() > 0:
            return
        token = item.data(0, Qt.ItemDataRole.UserRole) or item.text(0)
        cursor = self._editor.textCursor()
        operators = {
            "=",
            "!=",
            "<",
            ">",
            "<=",
            ">=",
            "AND",
            "OR",
            "NOT",
            "LIKE",
            "ILIKE",
            "IN (...)",
            "IS NULL",
            "IS NOT NULL",
        }
        if token.strip() in operators:
            cursor.insertText(f" {token.strip()} ")
        else:
            cursor.insertText(token)
        self._editor.setTextCursor(cursor)
        self._editor.setFocus()

    def _validate(self) -> None:
        """Parse the current expression and report feature match count."""
        if not self._current_layer:
            self._set_result("No layer selected.", "error")
            return

        expr_text = self._editor.toPlainText().strip()
        if not expr_text:
            self._set_result(
                "Empty expression - all features will be exported.",
                "info",
            )
            return

        expr = QgsExpression(expr_text)
        if expr.hasParserError():
            self._set_result(f"Syntax error: {expr.parserErrorString()}", "error")
            return

        req = QgsFeatureRequest(expr)
        matched = sum(1 for _ in self._current_layer.getFeatures(req))
        total = self._current_layer.featureCount()
        pct = (100.0 * matched / total) if total > 0 else 0.0
        self._set_result(
            f"Valid - {matched} of {total} features match ({pct:.1f}%)",
            "ok",
        )

    def _set_result(self, msg: str, kind: str) -> None:
        """Set the validation result label with colour coding."""
        colors = {"ok": "#27ae60", "error": "#c0392b", "info": "#2980b9"}
        bg = colors.get(kind, "#888")
        self._result_label.setText(msg)
        self._result_label.setStyleSheet(
            f"color:white; font-size:9pt; padding:6px; "
            f"border-radius:3px; background:{bg};",
        )

    def _clear(self) -> None:
        self._editor.clear()
        self._result_label.setText("")

    def _apply(self) -> None:
        """Apply the current expression as a filter on the selected layer."""
        if not self._current_layer:
            QMessageBox.warning(self, "No Layer", "Please select a layer first.")
            return

        expr_text = self._editor.toPlainText().strip()

        if expr_text:
            expr = QgsExpression(expr_text)
            if expr.hasParserError():
                QMessageBox.warning(
                    self,
                    "Invalid Expression",
                    f"Expression has errors:\n{expr.parserErrorString()}",
                )
                return

        layer_id = self._current_layer.id()
        self.current_filters[layer_id] = expr_text
        self.filter_applied.emit(layer_id, expr_text)
        self.accept()

    def get_all_filters(self) -> dict[str, str]:
        """Return a copy of the full filter dict."""
        return dict(self.current_filters)
