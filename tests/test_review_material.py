import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review_material.py"
WORLD_TABLE = (
    "| 证据ID | 主体 | 属性/关系 | 值 | 出处 | origin | status |\n"
    "| --- | --- | --- | --- | --- | --- | --- |\n"
    "| 原本:L1–L2；L3 | 书店 | 位置 | 城北 | 原本 | first_book | confirmed |\n"
    "| 原本:L1 | 书店 | 位置 | | 原本 | first_book | confirmed |\n"
    "| 原本:L4 | 书店 | 位置 | 城北 | 原本 | first_book | confirmed |\n"
    "| 原本:L1 | 书店 | 位置 | 城北 | 原本 | first_book | 候选-待核 |\n"
    "\n### C4 必须人拍板\n" +
    "| 证据ID | 属性/关系 | 值 |\n| --- | --- | --- |\n"
    "| 原本:L1 | 位置 | 城北 |\n"
)


class ReviewMaterialTest(unittest.TestCase):
    def test_locate_and_gate_selected_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "原本.txt"
            source.write_bytes("\ufeff第一行\r\n第二行\r\n第三行\r\n".encode("utf-8"))
            candidate = Path(directory) / "世界书.md"
            candidate.write_text(WORLD_TABLE, encoding="utf-8")
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            reviewed_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()

            def run(*args):
                return subprocess.run(
                    [sys.executable, "-X", "utf8", "-B", str(SCRIPT), *args],
                    capture_output=True, encoding="utf-8",
                )

            located = run("locate", str(source), "原本:L1–L2；L3", "--source-sha256", source_sha)
            self.assertEqual(located.returncode, 0, located.stderr)
            self.assertIn("L1\t第一行\nL2\t第二行\nL3\t第三行", located.stdout)
            check = ("check", str(candidate), "--source", str(source))
            version = ("--source-sha256", source_sha)
            review = ("--reviewed-sha256", reviewed_sha)
            pending = run(*check, *version, "--rows", "L3")
            self.assertEqual(pending.returncode, 1)
            self.assertIn("通过机械检查", pending.stdout)
            self.assertEqual(run(*check, *version, "--rows", "L3", *review).returncode, 0)
            bad_rows = run(*check, *version, "--rows", "L2,L4–L6,L11", *review)
            self.assertEqual(bad_rows.returncode, 1)
            for message in ("L2  未找到", "L4  列数不符", "L5  行段", "L6  位于隔离章节", "L11  位于隔离章节"):
                self.assertIn(message, bad_rows.stdout)
            self.assertEqual(run(*check, "--source-sha256", "", "--rows", "L3", *review).returncode, 2)
            candidate.write_text(WORLD_TABLE + "\n改动", encoding="utf-8")
            stale = run(*check, *version, "--rows", "L3", *review)
            self.assertEqual(stale.returncode, 1)
            self.assertIn("与当前文件不符", stale.stdout)


if __name__ == "__main__":
    unittest.main()
