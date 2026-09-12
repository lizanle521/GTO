# -*- coding: utf-8 -*-
"""Kivy App 自动化测试。

在无人工干预下验证：界面构建、三页切换、答题流程、推荐逻辑、设置读写。
运行：python test_app.py
"""

import os
import sys
import traceback as tb

os.environ["KIVY_NO_ARGS"] = "1"
os.environ["KIVY_LOG_LEVEL"] = "error"

from kivy.config import Config
Config.set("graphics", "width", "420")
Config.set("graphics", "height", "820")
Config.set("graphics", "window_state", "hidden")

from kivy.clock import Clock

LINES = []
RESULT = {"ok": False, "errors": []}


def log(msg):
    LINES.append(msg)
    print(msg, flush=True)


def run_checks():
    import main as m

    app = m.GTOTrainerApp()

    def check(dt):
        try:
            run_all(app, m)
            RESULT["ok"] = True
        except Exception:
            RESULT["errors"].append(tb.format_exc())
        finally:
            app.stop()

    Clock.schedule_once(check, 1.5)
    app.run()


def run_all(app, m):
    # ---------- 构建
    assert app.sm is not None, "ScreenManager 未创建"
    assert len(app.nav_buttons) == 3, "导航按钮数量不对"
    log("✓ App 构建成功")
    log(f"  导航标签: {list(app.nav_buttons.keys())}")
    log(f"  中文字体: {'已注册 ' + str(m._FONT_PATH) if m._FONT_OK else '未找到'}")

    # ---------- 训练页
    ts = app.train_screen
    assert ts.current_q is not None, "首题未生成"
    q = ts.current_q
    log(f"  首题: 模块={q.module} 选项={len(q.options)}个")
    log(f"  题干: {q.prompt.splitlines()[0][:44]}")

    ts.answer(0)
    assert ts.answered, "答题状态未更新"
    assert ts.lbl_verdict.text, "判定文本为空"
    assert ts.lbl_explain.text, "讲解为空"
    log(f"  答题判定: {ts.lbl_verdict.text[:34]}")
    log(f"  计分: {ts.lbl_score.text}")

    before = ts.session.total
    ts.answer(1)
    assert ts.session.total == before, "重复答题被重复计分"
    log("  ✓ 重复答题被正确忽略")

    modules_seen = set()
    for i in range(20):
        ts.next_question()
        modules_seen.add(ts.current_q.module)
        ts.answer(i % len(ts.current_q.options))
        assert ts.lbl_explain.text.strip(), f"第{i}题讲解为空"
        assert ts.current_q.correct_action in dict(ts.current_q.options), \
            f"第{i}题正确答案不在选项内"
    log(f"  连续答 20 题通过，计分: {ts.lbl_score.text}")
    log(f"  覆盖模块: {sorted(modules_seen)}")
    assert len(modules_seen) >= 2, "出题模块过于单一"

    for name in ["翻前开池", "翻前应对", "翻后决策", "混合模式"]:
        ts.module_spinner.text = name
        assert ts.current_q is not None, f"切换到 {name} 后无题目"
    log("  ✓ 训练模块切换正常")

    # ---------- 实时识别页
    rs = app.realtime_screen
    assert rs.btn_cam is not None
    assert rs.lbl_rec is not None

    rs._apply_cards({
        "hole_cards": ["As", "Kh"], "board_cards": [],
        "hero_position": "BTN", "confidence": "high",
    })
    assert "翻前" in rs.lbl_rec.text, f"翻前推荐异常: {rs.lbl_rec.text}"
    log(f"  翻前推荐: {rs.lbl_rec.text}")
    log(f"    详情: {rs.lbl_detail.text.splitlines()[0]}")

    rs._apply_cards({
        "hole_cards": ["As", "Ks"], "board_cards": ["Qs", "Js", "2h"],
        "hero_position": "BTN", "confidence": "high",
    })
    assert "翻牌" in rs.lbl_rec.text or "牌型" in rs.lbl_rec.text, \
        f"翻后推荐异常: {rs.lbl_rec.text}"
    log(f"  翻后推荐: {rs.lbl_rec.text}")
    log(f"    详情: {rs.lbl_detail.text.splitlines()[0]}")
    # AKs 在 QsJs2h 上是同花听牌 + 两头顺听牌，必须识别出来
    assert "同花听牌" in rs.lbl_detail.text, \
        f"未识别出同花听牌: {rs.lbl_detail.text}"
    log("  ✓ 正确识别同花听牌")
    assert "半诈唬" in rs.lbl_detail.text or "听牌" in rs.lbl_detail.text, \
        "强听牌未给出下注建议"
    log("  ✓ 强听牌给出合理建议")

    # 成牌顺子 → 应建议下大注
    # 用 JTs 在 98 7 的牌面：手牌 JT + 公共牌 9、8、7 = 789TJ 已成顺子
    rs._apply_cards({
        "hole_cards": ["Jh", "Th"], "board_cards": ["9s", "8d", "7c"],
        "hero_position": "BTN", "confidence": "high",
    })
    assert "顺子" in rs.lbl_rec.text, f"未识别顺子: {rs.lbl_rec.text}"
    assert "大注" in rs.lbl_detail.text, f"成牌未建议大注: {rs.lbl_detail.text}"
    log("  ✓ 成牌顺子正确建议下大注")

    # 未成顺但两头顺听牌 → 不应被判成成牌，且应给出听牌建议
    # 9h8h 在 Ts7d2c：只有 9、8、T、7 四张顺畅，缺 6 或 J
    rs._apply_cards({
        "hole_cards": ["9h", "8h"], "board_cards": ["Ts", "7d", "2c"],
        "hero_position": "BTN", "confidence": "high",
    })
    assert "高牌" in rs.lbl_rec.text, f"四张顺不该判成成牌: {rs.lbl_rec.text}"
    assert "两头顺听牌" in rs.lbl_detail.text, \
        f"未识别两头顺听牌: {rs.lbl_detail.text}"
    assert "半诈唬" in rs.lbl_detail.text, \
        f"强听牌未建议半诈唬: {rs.lbl_detail.text}"
    log("  ✓ 未成顺时正确识别两头顺听牌")

    # 纯空气牌 → 应建议过牌
    rs._apply_cards({
        "hole_cards": ["3h", "2d"], "board_cards": ["Ks", "Qd", "9c"],
        "hero_position": "BTN", "confidence": "high",
    })
    assert "过牌" in rs.lbl_detail.text, f"弱牌未建议过牌: {rs.lbl_detail.text}"
    log("  ✓ 弱牌正确建议过牌")

    rs._apply_cards({
        "hole_cards": ["As"], "board_cards": [],
        "hero_position": "BTN", "confidence": "low",
    })
    assert "无法" in rs.lbl_rec.text or "不完整" in rs.lbl_rec.text, \
        f"不完整手牌未提示: {rs.lbl_rec.text}"
    log("  ✓ 手牌不完整时正确提示")

    # 垃圾牌在 UTG 应推荐弃牌
    rs._apply_cards({
        "hole_cards": ["7h", "2d"], "board_cards": [],
        "hero_position": "UTG", "confidence": "high",
    })
    assert "弃牌" in rs.lbl_rec.text, f"垃圾牌未推荐弃牌: {rs.lbl_rec.text}"
    log(f"  ✓ 72o @ UTG 正确推荐: {rs.lbl_rec.text}")

    # ---------- 设置页
    ss = app.settings_screen
    assert ss.model_input.text, "模型字段为空"
    assert ss.base_url_input.text, "接口字段为空"
    log(f"  设置页模型: {ss.model_input.text}")
    log(f"  设置页接口: {ss.base_url_input.text}")

    ss.preset_spinner.text = "通义千问"
    assert "dashscope" in ss.base_url_input.text, "预设未正确应用"
    log(f"  ✓ 预设切换: 通义千问 -> {ss.model_input.text}")

    ss.interval_input.text = "5.0"
    ss.threshold_input.text = "0.15"
    ss.save()
    import config as cfg_mod
    reloaded = cfg_mod.load_config()
    assert reloaded["capture_interval"] == 5.0, "间隔未保存"
    assert reloaded["confidence_threshold"] == 0.15, "阈值未保存"
    log("  ✓ 设置保存并可读回")

    ss.interval_input.text = "0.1"
    ss.threshold_input.text = "9.9"
    ss.save()
    reloaded = cfg_mod.load_config()
    assert reloaded["capture_interval"] >= 1.0, "间隔未夹紧"
    assert reloaded["confidence_threshold"] <= 1.0, "阈值未夹紧"
    log("  ✓ 非法数值被正确夹紧")

    # 恢复默认
    ss.interval_input.text = "3.0"
    ss.threshold_input.text = "0.08"
    ss.save()

    # ---------- 页面切换
    for tab in ["train", "settings", "realtime"]:
        app.switch_tab(tab)
        assert app.sm.current == tab, f"切换 {tab} 失败"
    log("  ✓ 三个页面切换正常")


def main():
    print("=" * 58, flush=True)
    print("Kivy App 自动化测试", flush=True)
    print("=" * 58, flush=True)

    import logging
    logging.getLogger("kivy").setLevel(logging.ERROR)

    try:
        run_checks()
    except Exception:
        RESULT["errors"].append(tb.format_exc())

    print("", flush=True)
    if RESULT["ok"]:
        print("=" * 58, flush=True)
        print("全部测试通过 ✓", flush=True)
        print("=" * 58, flush=True)
        return 0

    print("=" * 58, flush=True)
    print("测试失败 ✗", flush=True)
    print("=" * 58, flush=True)
    for err in RESULT["errors"]:
        print(err, flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
