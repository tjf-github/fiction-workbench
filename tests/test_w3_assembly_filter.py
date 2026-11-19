from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import w3_assembly_filter as wf  # noqa: E402


class W3AssemblyFilterTest(unittest.TestCase):
    def test_calibrated_sample_card_passes(self):
        sample = ROOT / "W3-场景与物理词表" / "W3-推门场-已校准样卡.md"
        issues = wf.check_w3_card(sample.read_text(encoding="utf-8"))
        self.assertEqual(issues, [])

    def test_blocks_x1_in_default_non_adult_mode(self):
        card = "## 五、挂载的上游锚点\n- 引用 `X1-成年向隔离词表/嘉德丽雅-高张力词表.md`\n"
        issues = wf.check_w3_card(card, adult_mode=False)
        self.assertTrue(any(i.rule == "X1隔离门禁" for i in issues))
        issues_adult = wf.check_w3_card(card, adult_mode=True)
        self.assertFalse(any(i.rule == "X1隔离门禁" for i in issues_adult))

    def test_blocks_full_w2_dump_and_excess_anchors(self):
        dump = (
            "一、基础身份与阶段边界\n二、外貌与衣着物理结构\n三、习惯动作与职业感官\n"
            "## 五、挂载的上游锚点\n"
            "- **嘉德丽雅**\n"
            "  1. a\n  2. b\n  3. c\n  4. d\n  5. e\n  6. f\n"
        )
        issues = wf.check_w3_card(dump)
        rules = {i.rule for i in issues}
        self.assertIn("禁止整份塞入W2全文", rules)
        self.assertIn("单角色锚点超限", rules)

    def test_detects_and_sanitizes_braised_pork_triggers(self):
        dirty = (
            "两人刚把一段话收在半截，谁都不打算重头说一遍。\n"
            "她不顶撞也不讨好，未做第二次试探，保留是否赴约的决定权。\n"
            "- 禁止问旧称呼来源。\n"
        )
        issues = wf.check_w3_card(dirty)
        self.assertGreaterEqual(len(issues), 4)

        cleaned, count = wf.sanitize_w3_card(dirty)
        self.assertEqual(count, 4)
        self.assertNotIn("未做第二次试探", cleaned)
        self.assertNotIn("不顶撞也不讨好", cleaned)
        self.assertNotIn("保留是否赴约的决定权", cleaned)
        self.assertIn("先看书面资料再点头", cleaned)


if __name__ == "__main__":
    unittest.main()
