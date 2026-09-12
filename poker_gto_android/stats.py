# -*- coding: utf-8 -*-
"""训练成绩统计与持久化。

会话内即时统计 + 历史记录落盘（JSON），用于追踪长期进步。
"""

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


def _history_dir():
    """成绩目录：安卓用 app 私有目录，桌面用主目录（与 config 保持一致）。"""
    if "ANDROID_ARGUMENT" in os.environ or "ANDROID_PRIVATE" in os.environ:
        base = os.environ.get("ANDROID_PRIVATE") or os.getcwd()
        return Path(base)
    return Path.home() / ".poker_gto"


HISTORY_DIR = _history_dir()
HISTORY_FILE = HISTORY_DIR / "history.json"


@dataclass
class Session:
    """一次训练会话的成绩。"""
    total: int = 0
    correct: int = 0
    by_module: dict = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    records: list = field(default_factory=list)

    @property
    def accuracy(self):
        return self.correct / self.total if self.total else 0.0

    def record(self, module, correct, chosen="", correct_label=""):
        """记录一次作答。"""
        self.total += 1
        if correct:
            self.correct += 1
            self.by_module[module][0] += 1
        self.by_module[module][1] += 1
        self.records.append({
            "module": module,
            "correct": bool(correct),
            "chosen": chosen,
            "correct_label": correct_label,
            "time": datetime.now().isoformat(timespec="seconds"),
        })

    def weakest_module(self):
        """返回正确率最低的模块 (模块名, 正确率)；无数据返回 None。"""
        candidates = [
            (m, c / t) for m, (c, t) in self.by_module.items() if t >= 3
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda x: x[1])

    def to_dict(self):
        return {
            "total": self.total,
            "correct": self.correct,
            "accuracy": round(self.accuracy, 4),
            "by_module": {k: v for k, v in self.by_module.items()},
        }


def save_session(session):
    """把会话结果追加到历史文件。"""
    if session.total == 0:
        return None
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    data = {"sessions": []}
    if HISTORY_FILE.exists():
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {"sessions": []}

    entry = session.to_dict()
    entry["ended_at"] = datetime.now().isoformat(timespec="seconds")
    data.setdefault("sessions", []).append(entry)

    HISTORY_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return str(HISTORY_FILE)


def load_history():
    """读取历史会话列表。"""
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data.get("sessions", [])
    except (json.JSONDecodeError, OSError):
        return []


def overall_stats():
    """汇总所有历史会话的长期统计。"""
    sessions = load_history()
    if not sessions:
        return {"sessions": 0, "total": 0, "correct": 0, "accuracy": 0.0}

    total = sum(s.get("total", 0) for s in sessions)
    correct = sum(s.get("correct", 0) for s in sessions)
    return {
        "sessions": len(sessions),
        "total": total,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
    }


if __name__ == "__main__":
    s = Session()
    checks = [
        ("preflop_open", True), ("preflop_open", False), ("preflop_open", True),
        ("postflop", False), ("postflop", False), ("postflop", True),
        ("preflop_vs_open", True), ("preflop_vs_open", True),
    ]
    for module, ok in checks:
        s.record(module, ok)

    print("=== 统计自检 ===")
    print(f"总题数 {s.total}，答对 {s.correct}，正确率 {s.accuracy:.1%}")
    assert s.total == 8 and s.correct == 5, "统计计数错误"
    for module, (c, t) in sorted(s.by_module.items()):
        print(f"  {module:16} {c}/{t} = {c / t:.0%}")
    weak = s.weakest_module()
    print(f"最弱模块：{weak[0]} ({weak[1]:.0%})")
    assert weak[0] == "postflop", "最弱模块判断错误"

    print("\n所有自检通过 ✓")
