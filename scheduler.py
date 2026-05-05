"""
定时任务：每日自动采集 + 打招呼
由 Windows 任务计划程序触发，或手动运行：python scheduler.py
"""
import sys
import os
import json
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "collector"))
sys.path.insert(0, os.path.join(BASE_DIR, "auto_greet"))

from DrissionPage import Chromium
from claw import run_collector
from auto_greek import run_auto_greet


def main():
    config_path = os.path.join(BASE_DIR, "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    schedule = config.get("schedule", {})
    if not schedule.get("enabled", True):
        print("定时任务未启用（schedule.enabled = false），退出")
        return

    cities_dict = schedule.get("cities", {})
    if not cities_dict:
        print("未配置定时任务城市（schedule.cities），退出")
        return

    cities = [(code, name) for code, name in cities_dict.items()]
    date_str = datetime.now().strftime("%Y%m%d")

    print(f"\n{'=' * 60}")
    print(f"定时任务启动 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"目标城市：{[name for _, name in cities]}")
    print(f"日期尾缀：{date_str}")
    print(f"{'=' * 60}\n")

    output_dir = os.path.join(BASE_DIR, "output")
    os.makedirs(output_dir, exist_ok=True)

    output_csv = os.path.join(output_dir, f"boss_jobs_{date_str}.csv")
    progress_csv = os.path.join(output_dir, f"city_progress_{date_str}.txt")

    browser = Chromium()
    tab = browser.latest_tab

    try:
        # Phase 1: 采集
        print(f"[Phase 1] 开始采集 → {output_csv}")
        result = run_collector(
            cities,
            output_csv_path=output_csv,
            progress_file_path=progress_csv,
            max_pages=schedule.get("max_pages"),
            city_delay=schedule.get("city_delay"),
            base_delay=schedule.get("base_delay"),
            max_retries=schedule.get("max_retries"),
            rate_limit_cooldown=schedule.get("rate_limit_cooldown"),
            tab=tab,
        )

        if result is None or result[0] is None:
            print("采集阶段无结果，退出")
            return

        df, actual_csv = result
        print(f"[Phase 1] 采集完成：{len(df)} 条岗位 → {actual_csv}\n")

        # Phase 2: 评估 + 打招呼
        print(f"[Phase 2] 开始评估+打招呼")
        greet_result = run_auto_greet(
            input_csv=actual_csv,
            output_suffix=f"_{date_str}",
            tab=tab,
            base_delay=schedule.get("base_delay"),
            max_retries=schedule.get("max_retries"),
            rate_limit_cooldown=schedule.get("rate_limit_cooldown"),
        )

        if greet_result:
            print(f"\n{'=' * 60}")
            print(f"定时任务完成 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  采集岗位：{len(df)} 条")
            print(f"  评估通过：{greet_result['approved']} 个")
            print(f"  成功沟通：{greet_result['greeted']} 个")
            print(f"  评估详情：{greet_result['eval_file']}")
            print(f"  通过列表：{greet_result['approved_csv']}")
            print(f"{'=' * 60}")
        else:
            print("\n[Phase 2] 打招呼阶段无结果（可能无通过岗位）")

    finally:
        browser.quit()


if __name__ == "__main__":
    main()
