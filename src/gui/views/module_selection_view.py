import json
import logging
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QPushButton,
    QLabel,
    QLineEdit,
    QGroupBox,
    QComboBox,
    QSizePolicy,
)
from src.config.settings_manager import SettingsManager

class ModuleSelectionView(QWidget):
    """Third screen: allows selection of modules and lessons."""
    download_requested = Signal(str)

    def __init__(self, settings_manager: SettingsManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings_manager = settings_manager
        self._courses_by_id = {}
        self._last_clicked_item = None
        
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Selecione o conteúdo a ser baixado:"))

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar módulo ou aula...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._filter_tree)
        layout.addWidget(self.search_input)

        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabel("Conteúdo do Curso")
        self.tree_widget.itemChanged.connect(self._on_item_changed)
        self.tree_widget.itemClicked.connect(self._on_item_clicked)

        btn_layout = QHBoxLayout()
        self.btn_select_all = QPushButton("Selecionar Tudo")
        self.btn_select_all.clicked.connect(self._select_all)
        self.btn_deselect_all = QPushButton("Deselecionar Tudo")
        self.btn_deselect_all.clicked.connect(self._deselect_all)
        
        self.btn_expand_all = QPushButton("Expandir Tudo")
        self.btn_expand_all.clicked.connect(self.tree_widget.expandAll)
        self.btn_collapse_all = QPushButton("Colapsar Tudo")
        self.btn_collapse_all.clicked.connect(self.tree_widget.collapseAll)

        btn_layout.addWidget(self.btn_select_all)
        btn_layout.addWidget(self.btn_deselect_all)
        btn_layout.addWidget(self.btn_expand_all)
        btn_layout.addWidget(self.btn_collapse_all)
        layout.addLayout(btn_layout)

        layout.addWidget(self.tree_widget)

        # Folder Organization Mode GroupBox directly on this view for live preview/selection
        org_group = QGroupBox("Estrutura das Pastas e Arquivos")
        org_group_layout = QVBoxLayout(org_group)
        
        combo_layout = QHBoxLayout()
        combo_layout.addWidget(QLabel("Modo de Organização:"))
        
        self.folder_org_combo = QComboBox()
        self.folder_org_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.folder_org_combo.addItem("Padrão (Subpastas + 1. Aula.mp4)", "legacy")
        self.folder_org_combo.addItem("Plano (Sem subpastas de aula - Recomendado)", "flat")
        self.folder_org_combo.addItem("Misto (Subpastas + Vídeos renomeados)", "folders_descriptive")
        self.folder_org_combo.currentIndexChanged.connect(self._update_org_preview)
        combo_layout.addWidget(self.folder_org_combo)
        org_group_layout.addLayout(combo_layout)
        
        self.preview_label = QLabel()
        self.preview_label.setStyleSheet(
            "color: #3daee9; font-family: 'Consolas', monospace; font-size: 11px; "
            "background-color: rgba(61, 174, 233, 0.08); border: 1px solid rgba(61, 174, 233, 0.3); "
            "border-radius: 4px; padding: 8px;"
        )
        self.preview_label.setTextFormat(Qt.TextFormat.RichText)
        org_group_layout.addWidget(self.preview_label)
        
        layout.addWidget(org_group)

        self.download_button = QPushButton("Baixar Selecionados")
        self.download_button.clicked.connect(self._on_download)
        self.download_button.setStyleSheet("""
            QPushButton {
                padding: 12px 24px;
                font-weight: 700;
                font-size: 14px;
                background-color: #27ae60;
                color: white;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
            QPushButton:pressed {
                background-color: #1e8449;
            }
        """)
        layout.addWidget(self.download_button)

        # Initialize combo selection and preview
        settings = self._settings_manager.get_settings()
        saved_mode = getattr(settings, "folder_organization_mode", "legacy")
        idx = self.folder_org_combo.findData(saved_mode)
        if idx != -1:
            self.folder_org_combo.setCurrentIndex(idx)
        self._update_org_preview()

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        """Handles changes in item's check state to update parents and children."""
        # Recursão
        self.tree_widget.blockSignals(True)

        new_state = item.checkState(column)
        if new_state != Qt.CheckState.PartiallyChecked:
            for i in range(item.childCount()):
                child = item.child(i)
                child.setCheckState(column, new_state)

        parent = item.parent()
        if parent:
            self._update_parent_state(parent, column)

        self.tree_widget.blockSignals(False)

    def _update_parent_state(self, parent: QTreeWidgetItem, column: int) -> None:
        """Recursively updates the parent's check state based on its children's states."""
        child_states = [parent.child(i).checkState(column) for i in range(parent.childCount())]

        all_checked = all(state == Qt.CheckState.Checked for state in child_states)
        all_unchecked = all(state == Qt.CheckState.Unchecked for state in child_states)

        self.tree_widget.blockSignals(True)
        if all_checked:
            parent.setCheckState(column, Qt.CheckState.Checked)
        elif all_unchecked:
            parent.setCheckState(column, Qt.CheckState.Unchecked)
        else:
            parent.setCheckState(column, Qt.CheckState.PartiallyChecked)
        self.tree_widget.blockSignals(False)

        grandparent = parent.parent()
        if grandparent:
            self._update_parent_state(grandparent, column)

    def update_modules(self, content: dict, courses: list) -> None:
        """Clears the tree and populates it with course modules and lessons."""
        self._last_clicked_item = None
        self.search_input.clear()
        self.tree_widget.clear()
        self._courses_by_id = {str(course["id"]): course for course in courses}

        # Sync the organization mode combobox with current settings
        settings = self._settings_manager.get_settings()
        saved_mode = getattr(settings, "folder_organization_mode", "legacy")
        idx = self.folder_org_combo.findData(saved_mode)
        if idx != -1:
            self.folder_org_combo.setCurrentIndex(idx)
        self._update_org_preview()

        for course_id, course_data in content.items():
            course_item = QTreeWidgetItem(self.tree_widget, [course_data["title"]])
            course_item.setData(0, Qt.ItemDataRole.UserRole, {"id": course_id})
            course_item.setFlags(course_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            course_item.setCheckState(0, Qt.CheckState.Checked)

            for module in course_data.get("modules", []):
                module_item = QTreeWidgetItem(course_item, [module["title"]])
                module_item.setData(0, Qt.ItemDataRole.UserRole, module)
                module_item.setFlags(module_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                module_item.setCheckState(0, Qt.CheckState.Checked)
                
                for lesson in module.get("lessons", []):
                    title = lesson["title"]
                    is_locked = lesson.get("locked", False)
                    if is_locked:
                        title = f"🔒 {title}"
                    lesson_item = QTreeWidgetItem(module_item, [title])
                    lesson_item.setData(0, Qt.ItemDataRole.UserRole, lesson)
                    lesson_item.setFlags(lesson_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    if is_locked:
                        lesson_item.setCheckState(0, Qt.CheckState.Unchecked)
                        lesson_item.setDisabled(True)
                    else:
                        lesson_item.setCheckState(0, Qt.CheckState.Checked)
        
        self.tree_widget.expandAll()

    def _select_all(self) -> None:
        self._set_all_check_state(Qt.CheckState.Checked)

    def _deselect_all(self) -> None:
        self._set_all_check_state(Qt.CheckState.Unchecked)

    def _set_all_check_state(self, state: Qt.CheckState) -> None:
        self.tree_widget.blockSignals(True)
        root = self.tree_widget.invisibleRootItem()
        self._recursive_set_state(root, state)
        self.tree_widget.blockSignals(False)

    def _recursive_set_state(self, item: QTreeWidgetItem, state: Qt.CheckState) -> None:
        for i in range(item.childCount()):
            child = item.child(i)
            child.setCheckState(0, state)
            self._recursive_set_state(child, state)

    def _on_download(self) -> None:
        """
        Collects all items, adding a 'download' flag based on checkbox state,
        and emits a signal with the complete data structure.
        """
        selection = {}
        root = self.tree_widget.invisibleRootItem()

        for i in range(root.childCount()):
            course_item = root.child(i)
            course_data = course_item.data(0, Qt.ItemDataRole.UserRole)
            course_id = course_data["id"]
            full_course_data = self._courses_by_id.get(str(course_id), {}).copy()
            full_course_data["modules"] = []

            selection[course_id] = full_course_data

            for j in range(course_item.childCount()):
                module_item = course_item.child(j)
                module_data = module_item.data(0, Qt.ItemDataRole.UserRole).copy()

                module_data["download"] = module_item.checkState(0) in (Qt.CheckState.Checked, Qt.CheckState.PartiallyChecked)
                module_locked = module_data.get("locked", False)
                if module_locked:
                    module_data["download"] = False

                if "lessons" not in module_data:
                    module_data["lessons"] = []

                modified_lessons = []
                for k in range(module_item.childCount()):
                    lesson_item = module_item.child(k)
                    lesson_data = lesson_item.data(0, Qt.ItemDataRole.UserRole).copy()

                    is_checked = lesson_item.checkState(0) == Qt.CheckState.Checked
                    is_locked = lesson_data.get("locked", False)
                    lesson_data["download"] = is_checked and not is_locked
                    
                    modified_lessons.append(lesson_data)
                
                module_data["lessons"] = modified_lessons
                full_course_data["modules"].append(module_data)

        selection_json = json.dumps(selection, indent=2)
        logging.debug("\n--- DEBUG: Content Selected for Download ---")
        logging.debug(selection_json)
        logging.debug("------------------------------------------\n")

        self.download_requested.emit(selection_json)

    def _filter_tree(self, search_text: str) -> None:
        """Filters the tree to show only items matching the search text."""
        search_text = search_text.lower().strip()
        root = self.tree_widget.invisibleRootItem()

        for i in range(root.childCount()):
            course_item = root.child(i)
            course_visible = False

            for j in range(course_item.childCount()):
                module_item = course_item.child(j)
                module_text = module_item.text(0).lower()
                module_matches = search_text in module_text if search_text else True
                module_visible = module_matches

                for k in range(module_item.childCount()):
                    lesson_item = module_item.child(k)
                    lesson_text = lesson_item.text(0).lower()
                    lesson_matches = search_text in lesson_text if search_text else True

                    lesson_item.setHidden(not lesson_matches and not module_matches)

                    if lesson_matches:
                        module_visible = True

                module_item.setHidden(not module_visible)

                if module_visible:
                    course_visible = True

            course_item.setHidden(not course_visible)

            if search_text and course_visible:
                course_item.setExpanded(True)
                for j in range(course_item.childCount()):
                    module_item = course_item.child(j)
                    if not module_item.isHidden():
                        module_item.setExpanded(True)

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        from PySide6.QtWidgets import QApplication
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.KeyboardModifier.ShiftModifier and getattr(self, "_last_clicked_item", None):
            self._select_range(self._last_clicked_item, item, column)
        else:
            self._last_clicked_item = item

    def _select_range(self, item_from: QTreeWidgetItem, item_to: QTreeWidgetItem, column: int) -> None:
        all_items = []
        def traverse(parent_item):
            for i in range(parent_item.childCount()):
                child = parent_item.child(i)
                all_items.append(child)
                traverse(child)
        traverse(self.tree_widget.invisibleRootItem())

        try:
            idx_from = all_items.index(item_from)
            idx_to = all_items.index(item_to)
        except ValueError:
            self._last_clicked_item = item_to
            return

        start = min(idx_from, idx_to)
        end = max(idx_from, idx_to)
        
        target_state = item_to.checkState(column)

        self.tree_widget.blockSignals(True)
        for i in range(start, end + 1):
            target_item = all_items[i]
            if not target_item.isDisabled():
                target_item.setCheckState(column, target_state)
                if target_state != Qt.CheckState.PartiallyChecked:
                    self._recursive_set_children_state(target_item, target_state, column)
        self.tree_widget.blockSignals(False)

        self.tree_widget.blockSignals(True)
        unique_parents = set()
        for i in range(start, end + 1):
            parent = all_items[i].parent()
            if parent:
                unique_parents.add(parent)
        for parent in unique_parents:
            self._update_parent_state(parent, column)
        self.tree_widget.blockSignals(False)
        
        self._last_clicked_item = item_to

    def _recursive_set_children_state(self, item: QTreeWidgetItem, state: Qt.CheckState, column: int) -> None:
        for i in range(item.childCount()):
            child = item.child(i)
            if not child.isDisabled():
                child.setCheckState(column, state)
                self._recursive_set_children_state(child, state, column)

    def _update_org_preview(self) -> None:
        mode = self.folder_org_combo.currentData()
        
        # Save the new organization mode to settings on the fly
        settings = self._settings_manager.get_settings()
        if getattr(settings, "folder_organization_mode", "legacy") != mode:
            settings.folder_organization_mode = mode
            self._settings_manager.save_settings(settings)
            
        # Update preview text
        if mode == "flat":
            preview = (
                "<b>Modo Plano (Sem subpastas de aula - Recomendado):</b><br/>"
                "📂 downloads/<br/>"
                " ┗ 📂 Forró/<br/>"
                "    ┗ 📂 AV1 - Sequências/<br/>"
                "       ┗ 📄 <b>01 - 1.0 Sequencia 1 - Dançando.mp4</b><br/>"
                "       ┗ 📄 01 - 1.0 Sequencia 1 - Dançando - Descrição.txt"
            )
        elif mode == "folders_descriptive":
            preview = (
                "<b>Modo Misto (Subpastas + Vídeos descritivos):</b><br/>"
                "📂 downloads/<br/>"
                " ┗ 📂 Forró/<br/>"
                "    ┗ 📂 AV1 - Sequências/<br/>"
                "       ┗ 📂 01. 1.0 Sequencia 1 - Dançando/<br/>"
                "          ┗ 📄 <b>01. 1.0 Sequencia 1 - Dançando.mp4</b><br/>"
                "          ┗ 📄 01. 1.0 Sequencia 1 - Dançando - Descrição.txt"
            )
        else: # legacy
            preview = (
                "<b>Modo Padrão (Legado - Subpastas + Arquivo genérico):</b><br/>"
                "📂 downloads/<br/>"
                " ┗ 📂 Forró/<br/>"
                "    ┗ 📂 AV1 - Sequências/<br/>"
                "       ┗ 📂 1. 1.0 Sequencia 1 - Dançando/<br/>"
                "          ┗ 📄 <b>1. Aula.mp4</b><br/>"
                "          ┗ 📄 Descrição.txt"
            )
            
        self.preview_label.setText(preview)
