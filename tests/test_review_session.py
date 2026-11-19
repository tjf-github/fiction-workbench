import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from review_session import PENDING, QUESTION, REVIEWED, ReviewSession


class ReviewSessionTest(unittest.TestCase):
    def test_multiple_files_resume_and_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            whole = root / "整本.txt"
            whole.write_text("书来自城北。\n书店开门了。\n", encoding="utf-8-sig")
            chapter = root / "章节.md"
            chapter.write_text("# 新一天\n渡船停在码头。\n", encoding="utf-8")
            candidate = root / "候选.md"
            body = (
                "# 候选\n\n## 城北\n\n| 证据ID | 属性/关系 | 值 |\n| --- | --- | --- |\n"
                "| 原本:L2 | 地点 | 城北书店 |\n\n"
                "## 渡口\n\n| 证据ID | 属性/关系 | 值 |\n| --- | --- | --- |\n"
                "| 原本:L2 | 地点 | 渡口 |\n"
            )
            candidate.write_text(body, encoding="utf-8")
            session = ReviewSession(candidate)
            self.assertEqual(session.add_sources([whole, chapter]), [])
            first, second = session.keys()
            with self.assertRaisesRegex(ValueError, "先绑定"):
                session.set_status(first, REVIEWED)
            for key, source in ((first, whole), (second, chapter)):
                session.update_item(key, session.row(key)[1], str(source))
            session.set_status(first, REVIEWED)
            session.set_status(second, QUESTION)
            added = session.update_item(None, ("原本:L2", "渡船", "位置", "码头"), str(chapter))
            self.assertEqual(session.status(added), PENDING)

            reopened = ReviewSession(candidate)
            self.assertEqual(reopened.status(first), REVIEWED)
            self.assertEqual(reopened.status(second), QUESTION)
            self.assertEqual(reopened.item(second)["source"][0], str(chapter.resolve()))
            self.assertEqual(reopened.source(*reopened.item(second)["source"])[1], "渡船停在码头。")
            self.assertEqual(candidate.read_text(encoding="utf-8"), body)

            paths = reopened.export(root / "讨论.md", split=True)
            self.assertEqual(len(paths), 4)
            full, city, waterfront, manual = [path.read_text(encoding="utf-8") for path in paths]
            for text in ("## 城北", "## 渡口", "## 人工补充", REVIEWED, QUESTION, PENDING):
                self.assertIn(text, full)
            self.assertIn("整本.txt", city)
            self.assertNotIn("渡口", city)
            self.assertIn("章节.md", waterfront)
            self.assertIn("渡船", manual)
            self.assertNotIn(str(root), full)
            with self.assertRaises(FileExistsError):
                reopened.export(paths[0])

            whole.write_text("修改了原本。\n这一行已经不同。", encoding="utf-8")
            self.assertEqual(reopened.status(first), QUESTION)
            self.assertEqual(reopened.status(second), QUESTION)
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                reopened.set_status(first, REVIEWED)
            reopened.add_sources([whole])
            self.assertEqual(reopened.status(first), QUESTION)
            reopened.update_item(first, reopened.row(first)[1], str(whole))
            self.assertEqual(reopened.status(first), PENDING)

    def test_atlas_chapter_hint_and_ambiguous_quote(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            one, two = root / "第一章.txt", root / "第二章.md"
            one.write_text("林澄走过码头。", encoding="utf-8")
            two.write_text("# 第二章\n林澄走过码头。", encoding="utf-8")
            candidate = root / "Atlas.json"
            candidate.write_text(json.dumps({"characters": [
                {"name": "林澄", "evidence": {"动作": ["走过码头"]}, "evidence_chapters": {"动作": [2]}},
            ]}, ensure_ascii=False), encoding="utf-8")
            session = ReviewSession(candidate)
            session.add_sources([one, two])
            (key,) = session.keys()
            self.assertIn("Atlas 章号 2", session.row(key)[1][1])
            matches, unavailable = session.find_quote(session.quotes[key])
            self.assertEqual([(Path(path).name, line) for path, line, _ in matches], [("第一章.txt", 1), ("第二章.md", 2)])
            self.assertFalse(unavailable)
            self.assertNotIn("source", session.item(key))

    def test_ui_full_four_step_workflow(self):
        import tkinter as tk
        from review_material_ui import ReviewWindow

        with tempfile.TemporaryDirectory() as directory:
            root_dir = Path(directory)
            chap1 = root_dir / "第一章.txt"
            chap1.write_text("克莱恩推开船长室的门。\n嘉德丽雅戴着沉厚的眼镜。\n", encoding="utf-8")
            chap2 = root_dir / "第二章.md"
            chap2.write_text("# 第二章\n嘉德丽雅戴着沉厚的眼镜。\n书桌上摆着黄铜六分仪。\n", encoding="utf-8")
            atlas_file = root_dir / "Atlas.json"
            atlas_file.write_text(
                json.dumps(
                    {
                        "characters": [
                            {
                                "name": "嘉德丽雅",
                                "evidence": {
                                    "物件": ["书桌上摆着黄铜六分仪"],
                                    "外貌": ["戴着沉厚的眼镜"],
                                },
                                "evidence_chapters": {"物件": [2], "外貌": [2]},
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            recent_file = root_dir / "recent_ui.json"
            tk_root = tk.Tk()
            tk_root.withdraw()
            try:
                app = ReviewWindow(tk_root, recent_state_path=recent_file)
                # Step 1: 选原文（未打开候选资料前按钮直接可用）
                self.assertEqual(str(app.add_source_button.cget("state")), "normal")
                app.add_source_paths([chap1, chap2])
                self.assertEqual(len(app.pending_sources), 2)
                self.assertIn("第一章.txt", app.excerpt.get("1.0", "end"))

                # Step 2: 打开这次的提取结果（自动合入已选原文并自动绑定唯一出处）
                app.load_candidate_path(atlas_file)
                first_key, second_key = app.session.keys()
                # 第一条在两章中唯一匹配，应已自动绑定到第二章 L3
                self.assertEqual(app.session.item(first_key)["source"][0], str(chap2.resolve()))
                self.assertEqual(dict(zip(*app.session.row(first_key)[:2]))["证据ID"], "原本:L3")

                # Step 3: 逐条核对（左边选资料，右边看对应原文，直接内联修改并标为已核对）
                app.select(first_key)
                app.refresh()
                self.assertIn("L3  书桌上摆着黄铜六分仪。", app.excerpt.get("1.0", "end"))
                # 内联直接修改有偏差的值
                app.inline_vars["值"].set("书桌上摆着黄铜色六分仪")
                app.toggle_reviewed()
                self.assertEqual(app.session.status(first_key), REVIEWED)
                self.assertIn("书桌上摆着黄铜色六分仪", app.session.row(first_key)[1])
                # 开启了自动跳下一条待核对，应已自动切到 second_key
                self.assertEqual(app.selected(), second_key)
                app.refresh()
                # 第二条在两章都有出现，但右侧应按 Atlas 章号 2 优先预览第二章原文
                self.assertIn("第二章.md · L2", app.excerpt.get("1.0", "end"))
                # 拿不准标为「有疑问」
                app.toggle_question()
                self.assertEqual(app.session.status(second_key), QUESTION)
                # 手动新增漏掉的资料
                added_key = app.session.update_item(None, ("原本:L1", "克莱恩", "动作", "推开船长室的门"), str(chap1))
                app.session.set_status(added_key, REVIEWED)
            finally:
                tk_root.destroy()

            # 关掉窗口后，重新打开同一份提取结果接着做
            tk_root2 = tk.Tk()
            tk_root2.withdraw()
            try:
                app2 = ReviewWindow(tk_root2, recent_state_path=recent_file)
                app2.resume_recent()
                self.assertEqual(app2.session.status(first_key), REVIEWED)
                self.assertEqual(app2.session.status(second_key), QUESTION)
                self.assertEqual(app2.session.status(added_key), REVIEWED)

                # Step 4: 导出完整 Markdown 与分卷
                out_paths = app2.session.export(root_dir / "导出结果.md", split=True)
                self.assertEqual(len(out_paths), 3)
                full_text = out_paths[0].read_text(encoding="utf-8")
                self.assertIn("黄铜色六分仪", full_text)
                self.assertIn("推开船长室的门", full_text)
            finally:
                tk_root2.destroy()
