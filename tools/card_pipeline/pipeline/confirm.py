#!/usr/bin/env python3
"""第③段：人工确认闸门。不带 --set/--feedback 时只列出待确认内容，绝不默认确认。

  confirm.py --run-id R                          列出 pending 卡片与未确认反馈
  confirm.py --run-id R --show <card_id>         打印一张卡
  confirm.py --run-id R --set <card_id> confirmed|rejected|pending [--note 文本]
  confirm.py --run-id R --feedback <序号> confirm|unconfirm
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402


def load_cards(run_dir: Path):
    for p in sorted((run_dir / "cards").glob("*.json")):
        yield p, C.load_json(p)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", required=True)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--set", nargs=2, metavar=("CARD_ID", "STATUS"))
    g.add_argument("--feedback", nargs=2, metavar=("IDX", "ACTION"))
    g.add_argument("--show", metavar="CARD_ID")
    ap.add_argument("--note")
    ap.add_argument("--reviewed-at", help="审定时间（ISO 8601 带时区），补录用户实际确认时间；默认当前时间")
    ap.add_argument("--all", action="store_true", help="列表时也显示已审")
    a = ap.parse_args(argv)
    run_dir = C.staging_dir(a.run_id)
    if not run_dir.is_dir():
        sys.exit(f"run 不存在：{run_dir}")

    if a.set:
        cid, status = a.set
        if status not in ("confirmed", "rejected", "pending"):
            sys.exit("STATUS 只能是 confirmed / rejected / pending")
        p = run_dir / "cards" / f"{cid}.json"
        if not p.is_file():
            sys.exit(f"找不到卡片 {cid}")
        card = C.load_json(p)
        card["review"]["status"] = status
        rv = card["review"]
        rv.pop("confirmed_at", None)
        if status == "pending":
            rv.pop("reviewed_at", None)
        else:
            if a.reviewed_at:
                import datetime as _dt
                t = _dt.datetime.fromisoformat(a.reviewed_at)
                if t.tzinfo is None:
                    sys.exit("--reviewed-at 必须带时区")
                rv["reviewed_at"] = t.isoformat(timespec="seconds")
            else:
                rv["reviewed_at"] = C.now_iso()
            if status == "confirmed":
                rv["confirmed_at"] = rv["reviewed_at"]  # 兼容字段
        if a.note is not None:
            card["review"]["note"] = a.note
        C.validate(card, "staging-card.v1")
        C.dump_json(p, card)
        print(f"{cid} → {status}")
        return 0

    if a.feedback:
        idx, action = a.feedback
        if action not in ("confirm", "unconfirm"):
            sys.exit("ACTION 只能是 confirm / unconfirm")
        p = run_dir / "feedback.json"
        fb = C.load_json(p)
        i = int(idx)
        if not 0 <= i < len(fb["entries"]):
            sys.exit(f"反馈序号越界（共 {len(fb['entries'])} 条）")
        fb["entries"][i]["confirmed"] = action == "confirm"
        C.validate(fb, "atlas-feedback.v1")
        C.dump_json(p, fb)
        print(f"反馈 #{i} confirmed={fb['entries'][i]['confirmed']}")
        return 0

    if a.show:
        print(json.dumps(C.load_json(run_dir / "cards" / f"{a.show}.json"), ensure_ascii=False, indent=2))
        return 0

    n = 0
    for _, c in load_cards(run_dir):
        st = c["review"]["status"]
        if st == "pending" or a.all:
            n += st == "pending"
            yuan = sum(1 for it in c["items"] if it["basis"] == "原文")
            als = "、".join(x["name"] for x in c.get("aliases", [])) or "-"
            print(f"[{st}] {c['card_id']}  {c['kind']} {c['title']}  别名(推断):{als}  原文{yuan}/推断{len(c['items'])-yuan}")
    print(f"-- pending 卡片 {n} 张")
    fbp = run_dir / "feedback.json"
    if fbp.is_file():
        for i, e in enumerate(C.load_json(fbp)["entries"]):
            if not e["confirmed"] or a.all:
                print(f"  反馈 #{i} [{'已确认' if e['confirmed'] else '未确认'}] {e['type']} {e['candidate']}"
                      f"{' / ' + e['alias'] if e.get('alias') else ''}：{e['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
