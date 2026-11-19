"""本地并排核对候选条目和原文。"""

import json
from pathlib import Path
import re
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.font import Font, nametofont
from tkinter.scrolledtext import ScrolledText

from review_material import MANUAL_COLUMNS, line_spans, read_text
from review_session import PENDING, QUESTION, REVIEWED, ReviewSession, workshop_hint

UNBOUND_FILTER = "未绑定出处"
CHAPTER_HINT_RE = re.compile(r"Atlas\s*章号\s*(\d+)")
LINE_PREFIX_RE = re.compile(r"^L([1-9][0-9]*)\b")


def enable_windows_dpi():
    if sys.platform != "win32":
        return

    from ctypes import windll
    from ctypes.wintypes import BOOL, HANDLE

    # Set per-monitor DPI awareness before Tk creates a window.
    try:
        set_context = windll.user32.SetProcessDpiAwarenessContext
        set_context.argtypes = [HANDLE]
        set_context.restype = BOOL
        if set_context(-4):
            return
    except AttributeError:
        pass
    windll.user32.SetProcessDPIAware()


class ReviewWindow:
    def __init__(self, root, recent_state_path=None):
        self.root = root
        self.session = None
        self.recent_state_path = (
            Path(recent_state_path)
            if recent_state_path
            else Path(__file__).resolve().parents[1] / ".runtime" / "recent_review_ui.json"
        )
        self.pending_sources = {}
        self.preview_binding = None
        self.inline_matches = []
        self.inline_vars = {}
        self.inline_columns = ()
        self._updating_inline = False

        root.title("资料核对 · 小说创作工坊")

        def px(value):
            return round(value * root.winfo_fpixels("1i") / 96)

        self.px = px
        width = min(px(1240), round(root.winfo_screenwidth() * 0.94))
        height = min(px(800), round(root.winfo_screenheight() * 0.90))
        root.geometry(f"{width}x{height}")
        root.minsize(min(px(860), width), min(px(580), height))
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        interface_font = nametofont("TkDefaultFont", root=root)
        if sys.platform == "win32":
            interface_font.configure(family="Microsoft YaHei UI", size=10)
            icon_path = Path(__file__).resolve().parents[1] / "assets" / "fiction-workbench-desktop.ico"
            if icon_path.is_file():
                root.iconbitmap(default=str(icon_path))
        self.reading_font = Font(root=root, family=interface_font.actual("family"), size=11)
        self.bold_font = Font(root=root, family=interface_font.actual("family"), size=10, weight="bold")

        style = ttk.Style(root)
        style.configure("Review.Treeview", font=interface_font, rowheight=interface_font.metrics("linespace") + px(8))
        style.configure("Step.TLabelframe.Label", font=self.bold_font)

        # ── 顶部四步工作流栏 ──
        files = ttk.Frame(root, padding=(px(16), px(10), px(16), px(6)))
        files.grid(row=0, column=0, sticky="ew")
        files.columnconfigure(2, weight=1)

        self.candidate_name = tk.StringVar(value="尚未打开候选资料（支持 Atlas .json 或候选 .md）")
        self.current_source = tk.StringVar()
        self.source_status = tk.StringVar(value="尚未选择原文")
        self.progress_text = tk.StringVar(value="")
        self.filter = tk.StringVar(value="全部")
        self.search_var = tk.StringVar()
        self.context_lines = tk.IntVar(value=8)
        self.auto_next = tk.BooleanVar(value=True)

        # 第一行：① 选原文（始终可用，支持先选原文再打开提取结果）
        self.add_source_button = ttk.Button(files, text="① 选原文…", command=self.open_sources)
        self.add_source_button.grid(row=0, column=0, sticky="w", pady=(0, px(6)))
        ttk.Label(files, textvariable=self.source_status).grid(row=0, column=1, sticky="w", padx=(px(10), px(6)), pady=(0, px(6)))
        self.sources = ttk.Combobox(files, textvariable=self.current_source, state="readonly")
        self.sources.grid(row=0, column=2, sticky="ew", pady=(0, px(6)))
        self.sources.bind("<<ComboboxSelected>>", lambda _: self.refresh())
        self.auto_bind_button = ttk.Button(files, text="自动匹配出处", command=self.run_auto_bind)
        self.auto_bind_button.grid(row=0, column=3, padx=px(4), pady=(0, px(6)))
        self.bind_button = ttk.Button(files, text="批量绑定当前原文…", command=self.bind_unbound)
        self.bind_button.grid(row=0, column=4, pady=(0, px(6)))

        # 第二行：② 打开提取结果 & ④ 导出本次资料
        open_frame = ttk.Frame(files)
        open_frame.grid(row=1, column=0, columnspan=3, sticky="ew")
        open_frame.columnconfigure(2, weight=1)
        ttk.Button(open_frame, text="② 打开提取结果…", command=self.open_candidate).grid(row=0, column=0, sticky="w")
        self.resume_button = ttk.Button(open_frame, text="继续上次", command=self.resume_recent)
        self.resume_button.grid(row=0, column=1, sticky="w", padx=(px(4), 0))
        ttk.Label(open_frame, textvariable=self.candidate_name).grid(row=0, column=2, sticky="w", padx=px(10))
        ttk.Label(open_frame, textvariable=self.progress_text).grid(row=0, column=3, sticky="e", padx=(px(6), px(6)))

        self.export_button = ttk.Button(files, text="④ 导出完整 Markdown…", command=self.export)
        self.export_button.grid(row=1, column=3, padx=px(4))
        self.split_button = ttk.Button(files, text="分卷导出（含完整文件）…", command=lambda: self.export(split=True))
        self.split_button.grid(row=1, column=4)

        # ── 主工作区（左：资料列表与直接修改；右：对应原文对照） ──
        panes = ttk.Panedwindow(root, orient="horizontal")
        panes.grid(row=1, column=0, sticky="nsew", padx=px(16), pady=px(4))
        candidate = ttk.Frame(panes, padding=(0, 0, px(8), 0))
        evidence = ttk.Frame(panes, padding=(px(8), 0, 0, 0))
        panes.add(candidate, weight=5)
        panes.add(evidence, weight=6)
        candidate.columnconfigure(0, weight=1)
        candidate.rowconfigure(1, weight=3)
        candidate.rowconfigure(2, weight=0)
        evidence.columnconfigure(0, weight=1)
        evidence.rowconfigure(2, weight=1)

        # 左侧顶部工具栏：筛选、搜索、新增、下一条待核对
        tools = ttk.Frame(candidate)
        tools.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, px(6)))
        ttk.Label(tools, text="③ 候选条目", font=self.bold_font).pack(side="left")
        filters = ttk.Combobox(
            tools,
            state="readonly",
            textvariable=self.filter,
            values=("全部", PENDING, REVIEWED, QUESTION, UNBOUND_FILTER),
            width=10,
        )
        filters.pack(side="left", padx=px(6))
        filters.bind("<<ComboboxSelected>>", lambda _: self.populate(self.selected()))

        ttk.Label(tools, text="搜索").pack(side="left", padx=(px(4), px(2)))
        search_entry = ttk.Entry(tools, textvariable=self.search_var, width=14)
        search_entry.pack(side="left")
        search_entry.bind("<KeyRelease>", lambda _: self.populate(self.selected()))
        ttk.Button(tools, text="×", width=2, command=self.clear_search).pack(side="left", padx=(px(2), px(6)))

        self.add_button = ttk.Button(tools, text="+ 新增漏项", command=self.edit_item)
        self.add_button.pack(side="left")
        self.edit_button = ttk.Button(tools, text="弹窗找/改…", command=lambda: self.edit_item(self.selected()))
        self.edit_button.pack(side="left", padx=px(4))
        self.next_button = ttk.Button(tools, text="下一条待核对", command=self.next_pending)
        self.next_button.pack(side="left")

        # 左侧中部：候选资料表格
        self.table = ttk.Treeview(
            candidate,
            style="Review.Treeview",
            columns=("line", "section", "value", "ref", "reviewed"),
            show="headings",
            selectmode="browse",
            height=10,
        )
        for key, title, col_width, stretch in (
            ("line", "条目", 56, False),
            ("section", "章节/分类", 110, False),
            ("value", "资料内容", 240, True),
            ("ref", "原文定位", 92, False),
            ("reviewed", "状态", 72, False),
        ):
            self.table.heading(key, text=title)
            self.table.column(key, width=px(col_width), minwidth=px(90 if stretch else col_width), stretch=stretch)
        self.table.tag_configure("tag_reviewed", background="#eef8f0", foreground="#1b5e20")
        self.table.tag_configure("tag_question", background="#fff6e5", foreground="#7c4dff" if False else "#8a4b00")
        self.table.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(candidate, orient="vertical", command=self.table.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.bind("<<TreeviewSelect>>", self.refresh)
        self.table.bind("<Double-1>", lambda _: self.edit_item(self.selected()) if self.selected() else None)

        # 左侧底部：内联直接编辑区（"提取有偏差可以直接改，漏掉的可以手动新增"）
        self.inline_card = ttk.LabelFrame(
            candidate,
            text="当前条目详情 · 提取有偏差可直接改（改后点「标为已核对」会自动保存）",
            padding=(px(10), px(6)),
        )
        self.inline_card.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(px(8), 0))
        self.inline_card.columnconfigure(0, weight=1)

        self.heading_label = ttk.Label(self.inline_card, text="打开提取结果后，在上方选择一条资料核对。")
        self.heading_label.grid(row=0, column=0, sticky="ew", pady=(0, px(4)))

        self.inline_fields_frame = ttk.Frame(self.inline_card)
        self.inline_fields_frame.grid(row=1, column=0, sticky="ew")
        self.inline_fields_frame.columnconfigure(1, weight=1)
        self.inline_fields_frame.columnconfigure(3, weight=1)

        inline_actions = ttk.Frame(self.inline_card)
        inline_actions.grid(row=2, column=0, sticky="ew", pady=(px(6), 0))
        ttk.Label(inline_actions, text="绑定原文").pack(side="left")
        self.inline_source_var = tk.StringVar()
        self.inline_source_combo = ttk.Combobox(inline_actions, textvariable=self.inline_source_var, state="readonly", width=26)
        self.inline_source_combo.pack(side="left", padx=(px(6), px(8)), fill="x", expand=True)
        self.inline_source_combo.bind("<<ComboboxSelected>>", lambda _: self.save_inline_edits(silent=True))

        self.save_inline_button = ttk.Button(inline_actions, text="保存修改 (Ctrl+S)", command=self.save_inline_edits)
        self.save_inline_button.pack(side="left", padx=(0, px(4)))
        self.revert_inline_button = ttk.Button(inline_actions, text="还原此条", command=self.revert_current_item)
        self.revert_inline_button.pack(side="left")

        # 保持 self.details 兼容原有接口
        self.details = ScrolledText(candidate, font=self.reading_font, height=4, width=32, wrap="word", state="disabled")

        # ── 右侧：原文对照与快速定位 ──
        ev_header = ttk.Frame(evidence)
        ev_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, px(4)))
        self.evidence_title = tk.StringVar(value="原文出处 · 高亮为引用行")
        ttk.Label(ev_header, textvariable=self.evidence_title, font=self.bold_font).pack(side="left")

        self.use_selection_button = ttk.Button(
            ev_header, text="将原文选中行设为出处", command=self.bind_selected_excerpt_lines
        )
        self.use_selection_button.pack(side="right", padx=(px(6), 0))

        context_combo = ttk.Combobox(
            ev_header,
            state="readonly",
            values=(3, 8, 15, 30, 60),
            textvariable=self.context_lines,
            width=4,
        )
        context_combo.pack(side="right")
        context_combo.bind("<<ComboboxSelected>>", lambda _: self.refresh())
        ttk.Label(ev_header, text="上下文 ±行数：").pack(side="right", padx=(px(8), px(2)))

        # 右侧第二行：原文内搜索摘句 / 跳行 / 多匹配切换
        locator = ttk.Frame(evidence)
        locator.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, px(6)))
        locator.columnconfigure(1, weight=1)
        locator.columnconfigure(3, weight=1)

        ttk.Label(locator, text="查找摘句/行号").grid(row=0, column=0, sticky="w", padx=(0, px(4)))
        self.quote_query = tk.StringVar()
        query_entry = ttk.Entry(locator, textvariable=self.quote_query)
        query_entry.grid(row=0, column=1, sticky="ew")
        query_entry.bind("<Return>", lambda _: self.search_in_sources())
        self.search_source_button = ttk.Button(locator, text="在原文中找", command=self.search_in_sources)
        self.search_source_button.grid(row=0, column=2, padx=px(4))

        self.match_var = tk.StringVar()
        self.match_combo = ttk.Combobox(locator, textvariable=self.match_var, state="readonly")
        self.match_combo.grid(row=0, column=3, sticky="ew", padx=(px(4), px(4)))
        self.match_combo.bind("<<ComboboxSelected>>", self.on_match_selected)
        self.apply_match_button = ttk.Button(locator, text="采用此出处", command=self.apply_selected_match)
        self.apply_match_button.grid(row=0, column=4)

        # 右侧第三行：原文展示框
        self.excerpt = ScrolledText(evidence, font=self.reading_font, width=48, wrap="word", state="disabled")
        self.excerpt.grid(row=2, column=0, columnspan=2, sticky="nsew")
        self.excerpt.tag_configure("cited", background="#fff0b8", foreground="#29231a")
        self.excerpt.tag_configure("context_meta", foreground="#666666")
        self.excerpt.bind("<Double-1>", self.on_excerpt_double_click)

        # ── 底部核对状态与快捷操作栏 ──
        footer = ttk.Frame(root, padding=(px(16), px(8), px(16), px(10)))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.result = tk.StringVar()
        ttk.Label(footer, textvariable=self.result, wraplength=px(640)).grid(row=0, column=0, sticky="w")

        ttk.Checkbutton(footer, text="标记后自动跳下一条待核对", variable=self.auto_next).grid(
            row=0, column=1, padx=(px(8), px(8))
        )
        self.confirm = ttk.Button(footer, text="✓ 标为已核对", command=self.toggle_reviewed)
        self.confirm.grid(row=0, column=2, padx=(px(4), px(6)))
        self.question = ttk.Button(footer, text="? 标为有疑问", command=self.toggle_question)
        self.question.grid(row=0, column=3)

        # 快捷键绑定
        root.bind("<Control-s>", lambda _: self.save_inline_edits())
        root.bind("<Control-n>", lambda _: self.edit_item(None) if self.session else None)
        root.bind("<F3>", lambda _: self.next_pending() if self.session else None)
        root.bind("<Alt-Key-1>", lambda _: self.toggle_reviewed() if self.session else None)
        root.bind("<Alt-Key-2>", lambda _: self.toggle_question() if self.session else None)

        self.update_recent_button()
        self.populate()

    # ── 最近会话记忆（保存在 .runtime/recent_review_ui.json，支持关闭窗口后一键接着做） ──
    def _load_recent_state(self):
        path = self.recent_state_path
        try:
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            pass
        return {}

    def _save_recent_state(self):
        path = self.recent_state_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = self._load_recent_state()
            if self.session:
                data["last_candidate"] = str(self.session.path)
                data["last_selected"] = self.selected()
                data["sources"] = list(self.session.state["sources"].keys())
            elif self.pending_sources:
                data["sources"] = list(self.pending_sources.keys())
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass
        self.update_recent_button()

    def update_recent_button(self):
        data = self._load_recent_state()
        last = data.get("last_candidate")
        if last and Path(last).is_file():
            self.resume_button.configure(state="normal", text=f"继续：{Path(last).name[:16]}")
        else:
            self.resume_button.configure(state="disabled", text="继续上次")

    def resume_recent(self):
        data = self._load_recent_state()
        last = data.get("last_candidate")
        if not last or not Path(last).is_file():
            self.show_error("未找到上次打开的候选资料文件。")
            self.update_recent_button()
            return
        self.load_candidate_path(last, preferred_key=data.get("last_selected"))

    def clear_search(self):
        if self.search_var.get():
            self.search_var.set("")
            self.populate(self.selected())

    def selected(self):
        selection = self.table.selection()
        return selection[0] if selection else None

    def open_candidate(self):
        name = filedialog.askopenfilename(
            parent=self.root,
            title="打开这次的提取结果（Atlas JSON 或候选 Markdown）",
            filetypes=[("候选资料与提取结果", "*.json *.md"), ("Atlas JSON", "*.json"), ("候选 Markdown", "*.md"), ("所有文件", "*")],
        )
        if not name:
            return
        self.load_candidate_path(name)

    def load_candidate_path(self, name, preferred_key=None):
        try:
            session = ReviewSession(name)
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.show_error(error)
            return
        self.session = session
        # 如果用户在第一步已经先选了原文，自动合入当前会话
        if self.pending_sources:
            missing = [path for path in self.pending_sources if path not in session.state["sources"] and Path(path).is_file()]
            if missing:
                try:
                    session.add_sources(missing)
                except (OSError, ValueError):
                    pass
        # 同步会话中已有的原文到窗口级缓存，方便切换文件时复用
        for path, digest in session.state["sources"].items():
            self.pending_sources[path] = digest
        # 对唯一匹配或单一原本自动完成绑定，省去手工逐条绑定的繁琐步骤
        try:
            session.auto_bind()
        except (OSError, ValueError):
            pass

        self.candidate_name.set(session.path.name)
        self.filter.set("全部")
        self.update_sources()
        # 如果之前保存了核对位置，或者有待核对项，优先定位
        if preferred_key is None:
            for key in session.keys():
                if session.status(key) == PENDING:
                    preferred_key = key
                    break
        self.populate(preferred_key)
        self._save_recent_state()

    def show_error(self, error):
        messagebox.showerror("操作失败", str(error), parent=self.root)

    def _active_sources_dict(self):
        if self.session:
            return dict(self.session.state["sources"])
        return dict(self.pending_sources)

    def update_sources(self):
        sources_dict = self._active_sources_dict()
        sources = tuple(sources_dict.keys())
        self.sources.configure(values=sources)
        self.inline_source_combo.configure(values=("", *sources))
        if self.current_source.get() not in sources:
            self.current_source.set(sources[0] if sources else "")
        if not sources:
            self.source_status.set("尚未选择原文")
        elif len(sources) == 1:
            self.source_status.set(f"已选原文：{Path(sources[0]).name}")
        else:
            self.source_status.set(f"已选 {len(sources)} 份原文")

    def open_sources(self):
        names = filedialog.askopenfilenames(
            parent=self.root,
            title="选择整本原文或多个章节文件（支持 .txt 和 .md）",
            filetypes=[("原文文件", "*.txt *.md"), ("文本文件", "*.txt"), ("Markdown", "*.md"), ("所有文件", "*")],
        )
        if not names:
            return
        self.add_source_paths(names)

    def add_source_paths(self, names):
        problems = []
        if self.session:
            try:
                problems = self.session.add_sources(names)
                for path, digest in self.session.state["sources"].items():
                    self.pending_sources[path] = digest
                self.session.auto_bind()
            except (OSError, ValueError) as error:
                self.show_error(error)
                return
        else:
            for name in names:
                path = Path(name).resolve()
                try:
                    _, digest = read_text(path)
                    self.pending_sources[str(path)] = digest
                except (OSError, ValueError) as error:
                    problems.append(f"{path.name}  {error}")
        self.update_sources()
        self.populate(self.selected())
        self._save_recent_state()
        if problems:
            self.show_error("\n".join(problems))

    def run_auto_bind(self):
        if not self.session:
            return
        if not self.session.state["sources"]:
            self.show_error("请先点「① 选原文…」选择整本或章节文件。")
            return
        try:
            count = self.session.auto_bind()
        except (OSError, ValueError) as error:
            self.show_error(error)
            return
        self.populate(self.selected())
        self.result.set(f"自动匹配完成：新增绑定 {count} 条出处。" if count else "没有更多可自动唯一匹配的条目，请结合右侧原文手动选择。")

    def bind_unbound(self):
        if not self.session:
            return
        path = self.current_source.get()
        if not path:
            self.show_error("请先选择一份原文文件。")
            return
        if not messagebox.askyesno(
            "批量绑定",
            f"把所有尚未绑定且行号有效的条目绑定到《{Path(path).name}》？\n仅在这些行号都按同一个文件编号时使用。",
            parent=self.root,
        ):
            return
        try:
            count = self.session.bind_unbound(path)
        except (OSError, ValueError) as error:
            self.show_error(error)
            return
        self.populate(self.selected())
        messagebox.showinfo("批量绑定", f"本次绑定 {count} 条。", parent=self.root)

    def update_progress_summary(self):
        if not self.session:
            self.progress_text.set("")
            return
        stats = self.session.counts()
        unbound_note = f" · 未定位 {stats['unbound']}" if stats["unbound"] else ""
        self.progress_text.set(
            f"共 {stats['total']} 条（✓已核对 {stats[REVIEWED]} · ?有疑问 {stats[QUESTION]} · 待核对 {stats[PENDING]}{unbound_note}）"
        )

    def populate(self, preferred=None):
        self.table.delete(*self.table.get_children())
        has_session = self.session is not None
        state = "normal" if has_session else "disabled"
        # 注意：self.add_source_button 始终保持 normal，允许第一步先选原文！
        self.add_source_button.configure(state="normal")
        for button in (
            self.export_button,
            self.split_button,
            self.bind_button,
            self.auto_bind_button,
            self.add_button,
            self.next_button,
        ):
            button.configure(state=state)

        self.update_sources()
        self.update_progress_summary()

        keyword = self.search_var.get().strip().lower()
        current_filter = self.filter.get()

        if self.session:
            for key in self.session.keys():
                status = self.session.status(key)
                item = self.session.item(key)
                binding = item.get("source")
                if current_filter == UNBOUND_FILTER:
                    if binding:
                        continue
                elif current_filter not in {"全部", status}:
                    continue

                columns, cells, headings = self.session.row(key)
                fields = dict(zip(columns, cells))
                summary = " · ".join(
                    fields[field] for field in ("主体", "属性/关系", "值", "原句") if fields.get(field)
                )
                section = headings[-1] if headings else "未分类"
                label = key if key.startswith("M") else f"L{key}"
                ref = fields.get("证据ID", "")
                if binding:
                    short_src = Path(binding[0]).stem[:10]
                    ref_display = f"{short_src}:{ref.replace('原本:', '')}" if ref else short_src
                else:
                    ref_display = ref if ref and ref != "〔缺〕" else "待定位"

                if keyword:
                    haystack = " ".join((label, section, summary, ref_display, " ".join(cells))).lower()
                    if keyword not in haystack:
                        continue

                tag = "tag_reviewed" if status == REVIEWED else "tag_question" if status == QUESTION else ""
                self.table.insert(
                    "",
                    "end",
                    iid=key,
                    values=(label, section, summary or "（缺少内容）", ref_display, status),
                    tags=(tag,) if tag else (),
                )

        visible = self.table.get_children()
        if visible:
            self.select(preferred if preferred in visible else visible[0])
        self.refresh()

    def select(self, key):
        self.table.selection_set(key)
        self.table.focus(key)
        self.table.see(key)

    def next_pending(self):
        if not self.session:
            return
        current = self.selected()
        keys = self.session.keys()
        index = keys.index(current) + 1 if current in keys else 0
        ordered = keys[index:] + keys[:index]
        for key in ordered:
            if key != current and self.session.status(key) == PENDING:
                if self.filter.get() not in {"全部", PENDING, UNBOUND_FILTER} or self.search_var.get().strip():
                    self.filter.set("全部")
                    self.search_var.set("")
                    self.populate(key)
                elif key in self.table.get_children():
                    self.select(key)
                else:
                    self.filter.set("全部")
                    self.populate(key)
                return
        self.result.set("全部条目均已处理，没有其他待核对条目。")

    def edit_item(self, key=None):
        if not self.session:
            return
        EditItem(self, key)

    def export(self, split=False):
        if not self.session:
            return
        stem = f"{self.session.path.stem}-核对资料"
        candidate_dir = self.session.path.parent
        default_name = f"{stem}.md"
        counter = 2
        while (candidate_dir / default_name).exists():
            default_name = f"{stem}-{counter}.md"
            counter += 1

        name = filedialog.asksaveasfilename(
            parent=self.root,
            title="导出完整资料与分卷（供分批与 Gemini 对话）" if split else "导出本次完整 Markdown 资料",
            initialdir=str(candidate_dir),
            defaultextension=".md",
            filetypes=[("Markdown", "*.md")],
            initialfile=default_name,
        )
        if not name:
            return
        try:
            paths = self.session.export(name, split)
        except (OSError, ValueError) as error:
            self.show_error(error)
            return
        lines_info = []
        for p in paths:
            try:
                char_count = len(Path(p).read_text(encoding="utf-8"))
                lines_info.append(f"• {Path(p).name}（{char_count:,} 字符）")
            except OSError:
                lines_info.append(f"• {p}")
        header = (
            f"已导出完整文件及 {len(paths) - 1} 个分卷（保存在 {Path(paths[0]).parent}）：\n\n"
            if len(paths) > 1
            else f"已导出完整 Markdown 文件（保存在 {Path(paths[0]).parent}）：\n\n"
        )
        messagebox.showinfo("导出完成", header + "\n".join(lines_info), parent=self.root)

    @staticmethod
    def write_text(widget, parts, see_index=None):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        for text, tag in parts:
            widget.insert("end", text, tag)
        if see_index:
            widget.see(see_index)
        widget.configure(state="disabled")

    # ── 左侧内联直接编辑构建与保存 ──
    def _build_inline_editor(self, key):
        for child in self.inline_fields_frame.winfo_children():
            child.destroy()
        self.inline_vars.clear()
        self.inline_columns = ()

        if key is None or not self.session:
            self.heading_label.configure(
                text="请先完成：① 选原文 → ② 打开提取结果，随后在上方列表选择条目逐条核对。"
                if not self.session
                else "当前筛选条件下没有条目。"
            )
            self.inline_source_var.set("")
            self.inline_source_combo.configure(state="disabled")
            self.save_inline_button.configure(state="disabled")
            self.revert_inline_button.configure(state="disabled")
            return

        columns, cells, headings = self.session.row(key)
        self.inline_columns = columns
        fields = dict(zip(columns, cells))
        item = self.session.item(key)
        binding = item.get("source")

        section_str = " / ".join(headings) if headings else "未分类"
        origin_tag = "人工新增" if key.startswith("M") else "Atlas 提取" if key in self.session.quotes else f"候选表 L{key}"
        self.heading_label.configure(text=f"【{origin_tag}】 {section_str}")

        self._updating_inline = True
        try:
            for idx, column in enumerate(columns):
                val_str = fields.get(column, "").replace(r"\|", "|")
                var = tk.StringVar(value=val_str)
                self.inline_vars[column] = var
                # 宽字段（值、原句）独占整行，短字段两列并排
                is_wide = column in {"值", "原句"} or len(columns) <= 3
                if is_wide:
                    row_num = idx * 2
                    ttk.Label(self.inline_fields_frame, text=column).grid(
                        row=row_num, column=0, sticky="w", padx=(0, self.px(6)), pady=self.px(2)
                    )
                    entry = ttk.Entry(self.inline_fields_frame, textvariable=var)
                    entry.grid(row=row_num, column=1, columnspan=3, sticky="ew", pady=self.px(2))
                    entry.bind("<Return>", lambda _: self.save_inline_edits())
                else:
                    row_num = idx // 2
                    col_offset = (idx % 2) * 2
                    ttk.Label(self.inline_fields_frame, text=column).grid(
                        row=row_num, column=col_offset, sticky="w", padx=(self.px(6) if col_offset else 0, self.px(6)), pady=self.px(2)
                    )
                    entry = ttk.Entry(self.inline_fields_frame, textvariable=var)
                    entry.grid(row=row_num, column=col_offset + 1, sticky="ew", pady=self.px(2))
                    entry.bind("<Return>", lambda _: self.save_inline_edits())

            self.inline_source_combo.configure(state="readonly", values=("", *self.session.state["sources"]))
            self.inline_source_var.set(binding[0] if binding else "")
            self.save_inline_button.configure(state="normal")
            self.revert_inline_button.configure(state="normal" if key in self.session.state["items"] else "disabled")
        finally:
            self._updating_inline = False

    def has_unsaved_inline_edits(self, key):
        if key is None or not self.session or not self.inline_columns:
            return False
        _, current_cells, _ = self.session.row(key)
        current_clean = tuple(c.replace(r"\|", "|") for c in current_cells)
        edited_cells = tuple(self.inline_vars[col].get().strip() for col in self.inline_columns)
        old_binding = self.session.item(key).get("source")
        old_source_path = old_binding[0] if old_binding else ""
        new_source_path = self.inline_source_var.get().strip()
        return edited_cells != current_clean or new_source_path != old_source_path

    def save_inline_edits(self, silent=False):
        if self._updating_inline or not self.session:
            return False
        key = self.selected()
        if key is None or not self.inline_columns:
            return False
        cells = tuple(self.inline_vars[col].get().strip() for col in self.inline_columns)
        source_path = self.inline_source_var.get().strip()
        # 如果尚未选择绑定来源，但右侧正好预览了出处且用户填写了有效行号，自动带上预览来源
        if not source_path and self.preview_binding:
            ref_val = dict(zip(self.inline_columns, cells)).get("证据ID", "")
            if ref_val.startswith(("原本:", "原本：")):
                source_path = self.preview_binding[0]
        try:
            self.session.update_item(key, cells, source_path)
        except (OSError, ValueError) as error:
            if not silent:
                self.show_error(error)
            return False
        self.populate(key)
        if not silent:
            self.result.set("已保存对该条资料的修改。")
        return True

    def revert_current_item(self):
        key = self.selected()
        if key is None or not self.session:
            return
        if key.startswith("M"):
            if not messagebox.askyesno("删除人工条目", f"确定删除人工新增的条目 {key} 吗？", parent=self.root):
                return
        try:
            self.session.reset_item(key)
        except (OSError, ValueError) as error:
            self.show_error(error)
            return
        self.populate(None if key.startswith("M") else key)

    # ── 右侧原文对照渲染与智能定位 ──
    def _render_source_spans(self, source_path, source_lines, spans, prefix_note=""):
        ctx = max(1, int(self.context_lines.get() or 8))
        parts = []
        if prefix_note:
            parts.append((f"{prefix_note}\n\n", "context_meta"))
        first_cited_line_idx = None
        current_text_line = len(prefix_note.splitlines()) + (2 if prefix_note else 1)

        for start, end in spans:
            if parts and (not prefix_note or len(parts) > 1):
                parts.append(("\n", ""))
                current_text_line += 1
            win_start = max(1, start - ctx)
            win_end = min(len(source_lines), end + ctx)
            for number in range(win_start, win_end + 1):
                is_cited = start <= number <= end
                if is_cited and first_cited_line_idx is None:
                    first_cited_line_idx = f"{current_text_line}.0"
                parts.append((f"L{number}  {source_lines[number - 1]}\n", "cited" if is_cited else ""))
                current_text_line += 1

        self.evidence_title.set(f"原文出处 · {Path(source_path).name}（高亮为引用行，双击任意行可改绑行号）")
        self.write_text(self.excerpt, parts, see_index=first_cited_line_idx)

    def _auto_preview_unbound(self, key, columns, cells):
        """当条目尚未绑定原文时，自动在已选原文中查找并直接预览对应段落，做到『左边选资料，右边看对应原文』。"""
        self.preview_binding = None
        self.inline_matches = []
        self.match_combo.configure(values=())
        self.match_var.set("")
        self.apply_match_button.configure(state="disabled")

        if not self.session or not self.session.state["sources"]:
            self.evidence_title.set("原文出处 · 尚未选择原文")
            self.write_text(
                self.excerpt,
                [("请先点击左上角「① 选原文…」选择整本小说或几个章节文件（.txt / .md）。\n选择后右侧会自动定位并高亮对应原文。", "context_meta")],
            )
            self.result.set("请先点击「① 选原文…」加载原书或章节文件。")
            return

        fields = dict(zip(columns, cells))
        ref = fields.get("证据ID", "").strip()
        quote = (self.session.quotes.get(key) or fields.get("原句") or fields.get("值") or "").replace(r"\|", "|").strip()
        self.quote_query.set(quote if quote and quote != "〔缺〕" else ref)

        # 情况 1：条目自带 原本:L... 行号，但还未绑定具体原本文件
        if ref.startswith(("原本:", "原本：")):
            preferred_sources = []
            if self.current_source.get() in self.session.state["sources"]:
                preferred_sources.append(self.current_source.get())
            for p in self.session.state["sources"]:
                if p not in preferred_sources:
                    preferred_sources.append(p)
            for cand_path in preferred_sources:
                digest = self.session.state["sources"][cand_path]
                try:
                    source_lines = self.session.source(cand_path, digest)
                    spans = line_spans(ref, len(source_lines), require_original=True)
                except (OSError, ValueError):
                    continue
                self.preview_binding = (cand_path, digest, ref)
                self._render_source_spans(
                    cand_path,
                    source_lines,
                    spans,
                    prefix_note=f"【预览未绑定出处：{Path(cand_path).name} · {ref}】 直接点右下角「✓ 标为已核对」即可自动绑定并确认。",
                )
                self.apply_match_button.configure(state="normal")
                self.result.set(f"已自动预览《{Path(cand_path).name}》{ref}。核对无误可直接点「✓ 标为已核对」（会自动完成绑定）。")
                return

        # 情况 2：Atlas 提取或缺少行号，根据原句/值自动在原文中检索定位
        search_target = self.session.quotes.get(key) or fields.get("原句", "") or fields.get("值", "")
        search_target = search_target.replace(r"\|", "|").strip()
        if search_target and search_target != "〔缺〕":
            chapter_match = CHAPTER_HINT_RE.search(fields.get("属性/关系", ""))
            chapter_hint = int(chapter_match[1]) if chapter_match else None
            try:
                matches, unavailable, is_exact = self.session.find_quote_candidates(search_target, chapter_hint=chapter_hint)
            except (OSError, ValueError):
                matches, unavailable, is_exact = [], [], True
            if matches:
                self.inline_matches = matches
                labels = [f"{Path(p).name} · L{num}  {txt.strip()[:38]}" for p, num, txt in matches]
                self.match_combo.configure(values=labels)
                self.match_combo.current(0)
                self.apply_match_button.configure(state="normal")
                self._preview_match_index(0, is_exact=is_exact, total=len(matches))
                return

        self.evidence_title.set("原文出处 · 未找到自动匹配")
        self.write_text(
            self.excerpt,
            [(
                "未能在已选原文中自动定位到该条目的逐字出处。\n"
                "你可以在上方「查找摘句/行号」输入框缩短关键词（或输入 L行号）按回车查找。",
                "context_meta",
            )],
        )
        self.result.set("未自动找到逐字匹配行，可在右侧顶部缩短摘句或输入行号查找。")

    def _preview_match_index(self, index, is_exact=True, total=1):
        if not (0 <= index < len(self.inline_matches)):
            return
        cand_path, line_num, _ = self.inline_matches[index]
        digest = self.session.state["sources"].get(cand_path)
        if not digest:
            return
        try:
            source_lines = self.session.source(cand_path, digest)
        except (OSError, ValueError) as error:
            self.result.set(str(error))
            return
        ref = f"原本:L{line_num}"
        self.preview_binding = (cand_path, digest, ref)
        mode_note = "精确匹配" if is_exact else "按长分句智能匹配"
        note = (
            f"【自动定位预览（{mode_note}，共 {total} 处，当前第 {index + 1} 处）：{Path(cand_path).name} · L{line_num}】\n"
            "点「采用此出处」或直接点右下角「✓ 标为已核对」即可自动填入行号并绑定。"
        )
        self._render_source_spans(cand_path, source_lines, [(line_num, line_num)], prefix_note=note)
        self.result.set(
            f"已在《{Path(cand_path).name}》L{line_num} 找到匹配（共 {total} 处）。对得上可直接点「✓ 标为已核对」自动绑定！"
        )

    def on_match_selected(self, *_):
        idx = self.match_combo.current()
        if idx >= 0:
            self._preview_match_index(idx, is_exact=True, total=len(self.inline_matches))

    def apply_selected_match(self):
        if not self.session:
            return
        key = self.selected()
        if key is None or not self.preview_binding:
            return
        cand_path, _, ref = self.preview_binding
        if "证据ID" in self.inline_vars:
            self.inline_vars["证据ID"].set(ref)
        self.inline_source_var.set(cand_path)
        self.save_inline_edits(silent=True)
        self.result.set(f"已绑定出处：{Path(cand_path).name} · {ref}")

    def search_in_sources(self):
        if not self.session or not self.session.state["sources"]:
            self.show_error("请先点「① 选原文…」加载原文文件。")
            return
        query = self.quote_query.get().strip()
        if not query:
            return
        # 支持直接输入 L1234 或 原本:L1234–L1240 跳行查看
        if re.match(r"^(?:原本[:：]\s*)?L?[1-9][0-9]*", query):
            ref_str = query if query.startswith(("原本:", "原本：")) else f"原本:{query if query.startswith('L') else 'L' + query}"
            target_path = self.current_source.get() or next(iter(self.session.state["sources"]))
            digest = self.session.state["sources"].get(target_path)
            try:
                source_lines = self.session.source(target_path, digest)
                spans = line_spans(ref_str, len(source_lines), require_original=True)
                self.preview_binding = (target_path, digest, f"原本:L{spans[0][0]}" if spans[0][0] == spans[0][1] else ref_str)
                self.apply_match_button.configure(state="normal")
                self._render_source_spans(
                    target_path,
                    source_lines,
                    spans,
                    prefix_note=f"【跳行预览：{Path(target_path).name} · {ref_str}】 可点「采用此出处」绑定到当前条目。",
                )
                self.result.set(f"已跳转到《{Path(target_path).name}》{ref_str}。")
                return
            except (OSError, ValueError) as error:
                self.result.set(str(error))
                return

        try:
            matches, unavailable, is_exact = self.session.find_quote_candidates(query)
        except (OSError, ValueError) as error:
            self.result.set(str(error))
            return
        self.inline_matches = matches
        if not matches:
            self.match_combo.configure(values=())
            self.match_var.set("")
            self.apply_match_button.configure(state="disabled")
            self.result.set("在已选原文中没有找到匹配行，请尝试缩短关键词。")
            return
        labels = [f"{Path(p).name} · L{num}  {txt.strip()[:38]}" for p, num, txt in matches]
        self.match_combo.configure(values=labels)
        self.match_combo.current(0)
        self.apply_match_button.configure(state="normal")
        self._preview_match_index(0, is_exact=is_exact, total=len(matches))

    def _extract_excerpt_line_numbers(self, use_selection=True):
        try:
            if use_selection and self.excerpt.tag_ranges("sel"):
                start_idx = self.excerpt.index("sel.first linestart")
                end_idx = self.excerpt.index("sel.last lineend")
                text_block = self.excerpt.get(start_idx, end_idx)
            else:
                line_idx = self.excerpt.index("insert linestart")
                text_block = self.excerpt.get(line_idx, f"{line_idx} lineend")
        except tk.TclError:
            return None
        nums = []
        for line in text_block.splitlines():
            m = LINE_PREFIX_RE.match(line.strip())
            if m:
                nums.append(int(m[1]))
        if not nums:
            return None
        return min(nums), max(nums)

    def bind_selected_excerpt_lines(self):
        if not self.session:
            return
        key = self.selected()
        if key is None:
            return
        span = self._extract_excerpt_line_numbers(use_selection=True)
        if not span:
            self.show_error("请先在右侧原文框中选中或点击带有 L行号 的原文行。")
            return
        start, end = span
        ref = f"原本:L{start}" if start == end else f"原本:L{start}–L{end}"
        item = self.session.item(key)
        binding = item.get("source")
        target_path = (
            binding[0]
            if binding
            else (self.preview_binding[0] if self.preview_binding else self.current_source.get())
        )
        if not target_path:
            self.show_error("请先选择一份原文文件。")
            return
        if "证据ID" in self.inline_vars:
            self.inline_vars["证据ID"].set(ref)
        self.inline_source_var.set(target_path)
        self.save_inline_edits(silent=True)
        self.result.set(f"已将当前条目出处更新为：《{Path(target_path).name}》{ref}")

    def on_excerpt_double_click(self, *_):
        if not self.session or self.selected() is None:
            return
        span = self._extract_excerpt_line_numbers(use_selection=False)
        if span:
            self.bind_selected_excerpt_lines()

    def refresh(self, *_):
        key = self.selected()
        self.confirm.configure(state="disabled", text="✓ 标为已核对")
        self.question.configure(state="disabled", text="? 标为有疑问")
        self.edit_button.configure(state="disabled")
        self.use_selection_button.configure(state="disabled")
        self.search_source_button.configure(state="normal" if self.session else "disabled")
        self.preview_binding = None
        self.write_text(self.excerpt, [])
        self._build_inline_editor(key)

        if key is None:
            self.write_text(self.details, [])
            if not self.session and self.pending_sources:
                src_names = "、".join(Path(p).name for p in self.pending_sources)
                self.result.set(f"已选原文（{src_names}）。下一步请点「② 打开提取结果…」选择 Atlas .json 或候选 .md。")
                # 在右侧预览已选原文开头，给用户直观反馈
                first_path = self.current_source.get() or next(iter(self.pending_sources))
                try:
                    lines, _ = read_text(Path(first_path))
                    preview_parts = [(f"【已加载原文：{Path(first_path).name}（共 {len(lines)} 行）】\n\n", "context_meta")]
                    for n in range(1, min(len(lines), 25) + 1):
                        preview_parts.append((f"L{n}  {lines[n - 1]}\n", ""))
                    self.write_text(self.excerpt, preview_parts)
                except (OSError, ValueError):
                    pass
            else:
                self.result.set(
                    "请先「① 选原文」并「② 打开提取结果」（支持 Atlas .json 或候选 .md）。"
                    if not self.session
                    else "当前筛选条件下没有条目。"
                )
            return

        self.edit_button.configure(state="normal")
        self.use_selection_button.configure(state="normal")
        columns, cells, headings = self.session.row(key)
        fields = dict(zip(columns, cells))
        item = self.session.item(key)
        binding = item.get("source")

        details = [" / ".join(headings)]
        if binding:
            details.append(f"来源  {Path(binding[0]).name}（{binding[1][:12]}）")
        details.extend(f"{column}  {fields.get(column) or '〔缺〕'}" for column in columns)
        self.write_text(self.details, [("\n".join(details), "")])

        is_question = item.get("status") == QUESTION
        self.question.configure(state="normal", text="撤销疑问" if is_question else "? 标为有疑问")

        quote_default = (self.session.quotes.get(key) or fields.get("原句") or fields.get("值") or "").replace(r"\|", "|").strip()
        self.quote_query.set(quote_default)

        if not binding:
            # 未绑定时自动在右侧尝试预览匹配到的原文，并且如果已有预览出处，允许一键标为已核对（自动完成绑定）
            self._auto_preview_unbound(key, columns, cells)
            if self.preview_binding:
                self.confirm.configure(state="normal", text="✓ 绑定并标为已核对")
            return

        self.match_combo.configure(values=())
        self.match_var.set("")
        self.apply_match_button.configure(state="disabled")

        try:
            source = self.session.source(*binding)
            spans = line_spans(fields.get("证据ID", ""), len(source), require_original=True)
            self._render_source_spans(binding[0], source, spans)
            self.session.check(key)
        except (OSError, ValueError) as error:
            self.result.set(f"⚠ {error}（可在左侧直接修改字段，或在右侧重新查找绑定出处）")
            return

        reviewed = item.get("status") == REVIEWED
        self.confirm.configure(state="normal", text="撤销已核对" if reviewed else "✓ 标为已核对")
        hint = workshop_hint(columns, cells)
        base_msg = "✓ 已核对，进度已自动保存。" if reviewed else "✓ 字段和出处检查通过，请对照右侧原文核对。"
        self.result.set(f"{base_msg}  {hint}" if hint else base_msg)
        self._save_recent_state()

    def set_status(self, status):
        key = self.selected()
        if key is None or not self.session:
            return
        # 1. 如果用户在左侧内联输入框改了内容，先自动保存
        if self.has_unsaved_inline_edits(key):
            if not self.save_inline_edits(silent=True):
                return
        # 2. 如果该条尚未绑定原文（或证据ID为〔缺〕），但右侧已经自动定位预览了出处，点「标为已核对」时自动完成绑定！
        item = self.session.item(key)
        if status == REVIEWED and (not item.get("source") or dict(zip(*self.session.row(key)[:2])).get("证据ID") in {"", "〔缺〕"}):
            if self.preview_binding:
                cand_path, _, ref = self.preview_binding
                if "证据ID" in self.inline_vars and self.inline_vars["证据ID"].get().strip() in {"", "〔缺〕", "-"}:
                    self.inline_vars["证据ID"].set(ref)
                self.inline_source_var.set(cand_path)
                self.save_inline_edits(silent=True)

        toggling_off = self.session.item(key).get("status") == status
        target_status = PENDING if toggling_off else status
        try:
            self.session.set_status(key, target_status)
        except (OSError, ValueError) as error:
            self.show_error(error)
            return

        self._save_recent_state()
        # 如果开启了「标记后自动跳下一条待核对」，且当前是正向标记（非撤销），自动前进到下一条
        if not toggling_off and target_status in {REVIEWED, QUESTION} and self.auto_next.get():
            self.populate(key)
            self.next_pending()
        else:
            self.populate(key)

    def toggle_reviewed(self):
        self.set_status(REVIEWED)

    def toggle_question(self):
        self.set_status(QUESTION)


class EditItem:
    def __init__(self, app, key):
        self.app, self.key = app, key
        self.session = app.session
        self.window = tk.Toplevel(app.root)
        self.window.title("新增人工资料" if key is None else "编辑资料与出处")
        self.window.transient(app.root)
        self.window.grab_set()
        form = ttk.Frame(self.window, padding=16)
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)
        columns, cells, _ = self.session.row(key) if key else (MANUAL_COLUMNS, (), ())
        fields = dict(zip(columns, cells))

        # 新增资料时，如果用户在右侧原文选中了某几行，自动预填证据ID和摘句
        prefill_ref = ""
        prefill_quote = ""
        if key is None:
            span = app._extract_excerpt_line_numbers(use_selection=True)
            if span:
                prefill_ref = f"原本:L{span[0]}" if span[0] == span[1] else f"原本:L{span[0]}–L{span[1]}"

        self.values = {}
        for index, column in enumerate(columns):
            ttk.Label(form, text=column).grid(row=index, column=0, sticky="w", padx=(0, 8), pady=3)
            default_val = fields.get(column, "").replace(r"\|", "|")
            if key is None and column == "证据ID" and prefill_ref:
                default_val = prefill_ref
            value = tk.StringVar(value=default_val)
            self.values[column] = value
            ttk.Entry(form, textvariable=value, width=58).grid(row=index, column=1, sticky="ew")

        previous = self.session.item(key).get("source") if key else None
        default_source = (
            previous[0]
            if previous
            else (app.current_source.get() if app.current_source.get() in self.session.state["sources"] else "")
        )
        self.source = tk.StringVar(value=default_source)
        ttk.Label(form, text="绑定来源").grid(row=len(columns), column=0, sticky="w")
        ttk.Combobox(
            form,
            textvariable=self.source,
            values=("", *self.session.state["sources"]),
            state="readonly",
        ).grid(row=len(columns), column=1, sticky="ew", pady=5)

        excerpt = (
            self.session.quotes.get(key, fields.get("原句", "").replace(r"\|", "|"))
            if key
            else prefill_quote
        )
        self.excerpt = tk.StringVar(value=excerpt)
        ttk.Label(form, text="原文摘句").grid(row=len(columns) + 1, column=0, sticky="w")
        excerpt_entry = ttk.Entry(form, textvariable=self.excerpt)
        excerpt_entry.grid(row=len(columns) + 1, column=1, sticky="ew")
        excerpt_entry.bind("<Return>", lambda _: self.find())

        ttk.Button(form, text="在已登记的原本里找", command=self.find).grid(
            row=len(columns) + 2, column=1, sticky="w", pady=5
        )
        self.results = tk.Listbox(form, height=6, width=60)
        self.results.grid(row=len(columns) + 3, column=0, columnspan=2, sticky="ew")
        self.results.bind("<Double-1>", lambda _: self.use_match())
        self.matches = []
        self.message = tk.StringVar()
        ttk.Label(form, textvariable=self.message, wraplength=520).grid(
            row=len(columns) + 4, column=0, columnspan=2, sticky="w"
        )
        ttk.Button(form, text="使用选中的出处", command=self.use_match).grid(
            row=len(columns) + 5, column=0, sticky="w", pady=5
        )
        ttk.Button(form, text="保存", command=self.save).grid(row=len(columns) + 5, column=1, sticky="e", pady=5)

        self.window.bind("<Escape>", lambda _: self.window.destroy())
        if excerpt:
            self.find()

    def find(self):
        self.results.delete(0, "end")
        self.matches = []
        try:
            self.matches, unavailable, is_exact = self.session.find_quote_candidates(self.excerpt.get())
        except (OSError, ValueError) as error:
            self.message.set(str(error))
            return
        for path, number, text in self.matches:
            self.results.insert("end", f"{Path(path).name} · L{number}  {text}")
        if len(self.matches) == 1 and not unavailable and is_exact:
            self.results.selection_set(0)
            self.use_match()
            self.message.set("找到唯一一处，保存前可以核对文件和行号。")
            return
        if self.matches:
            mode = "" if is_exact else "（按分句智能匹配）"
            hint = f"找到 {len(self.matches)} 处{mode}，请选中正确位置。"
        else:
            hint = "没有找到匹配的行，可缩短摘句重试。"
        if len(self.matches) == 200:
            hint = "仅显示前 200 处；可以输入更长的摘句缩小范围。"
        if unavailable:
            hint += f" 跳过不可用来源：{'、'.join(unavailable)}"
        self.message.set(hint)

    def use_match(self):
        selected = self.results.curselection()
        if selected:
            path, number, _ = self.matches[selected[0]]
            self.source.set(path)
            self.values["证据ID"].set(f"原本:L{number}")

    def save(self):
        cells = tuple(value.get().strip() for value in self.values.values())
        if self.key is None and not self.values["值"].get().strip():
            self.message.set("请填写要补充的资料。")
            return
        try:
            key = self.session.update_item(self.key, cells, self.source.get())
        except (OSError, ValueError) as error:
            self.message.set(str(error))
            return
        self.window.destroy()
        self.app.filter.set("全部")
        self.app.populate(key)


if __name__ == "__main__":
    enable_windows_dpi()
    window = tk.Tk()
    ReviewWindow(window)
    window.mainloop()
