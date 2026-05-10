"""
循环任务：每轮完成后间隔 loop_interval_hours 小时再次运行
输出文件格式：boss_jobs_<timestamp>_batch<NNN>.csv（如 boss_jobs_20260510_143025_batch001.csv）
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


def load_batch_counter(counter_file):
    if os.path.exists(counter_file):
        with open(counter_file, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    return 0


def save_batch_counter(counter_file, count):
    with open(counter_file, "w", encoding="utf-8") as f:
        f.write(str(count))


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

    loop_hours = schedule.get("loop_interval_hours", 6)
    cities = [(code, name) for code, name in cities_dict.items()]

    output_dir = os.path.join(BASE_DIR, "output")
    os.makedirs(output_dir, exist_ok=True)
    counter_file = os.path.join(output_dir, "batch_counter.txt")
    batch_num = load_batch_counter(counter_file)

    print(f"\n{'=' * 60}")
    print(f"循环任务模式启动")
    print(f"目标城市：{[name for _, name in cities]}")
    print(f"间隔：每 {loop_hours} 小时运行一轮")
    print(f"起始批次：{batch_num + 1}")
    print(f"{'=' * 60}")

    while True:
        batch_num += 1
        save_batch_counter(counter_file, batch_num)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_tag = f"{ts}_batch{batch_num:03d}"

        print(f"\n{'=' * 60}")
        print(f"第 {batch_num} 轮启动 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"批次标签：{batch_tag}")
        print(f"{'=' * 60}\n")

        output_csv = os.path.join(output_dir, f"boss_jobs_{batch_tag}.csv")
        progress_csv = os.path.join(output_dir, f"city_progress_{batch_tag}.txt")

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
                print("采集阶段无结果，跳过本轮打招呼")
                greet_ok = False
            else:
                df, actual_csv = result
                print(f"[Phase 1] 采集完成：{len(df)} 条岗位 → {actual_csv}\n")

                # Phase 2: 评估 + 打招呼
                print(f"[Phase 2] 开始评估+打招呼")
                greet_result = run_auto_greet(
                    input_csv=actual_csv,
                    output_suffix=f"_{batch_tag}",
                    tab=tab,
                    base_delay=schedule.get("base_delay"),
                    max_retries=schedule.get("max_retries"),
                    rate_limit_cooldown=schedule.get("rate_limit_cooldown"),
                )

                greet_ok = greet_result is not None
                if greet_ok:
                    print(f"\n{'=' * 60}")
                    print(f"第 {batch_num} 轮完成 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"  采集岗位：{len(df)} 条")
                    print(f"  评估通过：{greet_result['approved']} 个")
                    print(f"  成功沟通：{greet_result['greeted']} 个")
                    print(f"{'=' * 60}")
                else:
                    print("\n[Phase 2] 打招呼阶段无结果")

        finally:
            browser.quit()

        # 等待指定小时后进入下一轮
        next_run = datetime.now().timestamp() + loop_hours * 3600
        next_str = datetime.fromtimestamp(next_run).strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n下一轮预计启动：{next_str}（{loop_hours} 小时后）")
        print("按 Ctrl+C 可中断循环\n")

        try:
            import time
            time.sleep(loop_hours * 3600)
        except KeyboardInterrupt:
            print(f"\n已中断。共完成 {batch_num} 轮，下次从批次 {batch_num + 1} 开始。")
            break


if __name__ == "__main__":
    main()
