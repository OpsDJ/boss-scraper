import time
import json
import pandas as pd
from DrissionPage import Chromium
import os

# ==========================================
# 路径（基于脚本所在目录，而非 CWD）
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)

with open(os.path.join(PROJECT_DIR, "config.json"), "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

SEARCH = CONFIG["search"]
COLLECT = CONFIG["collect"]

KEYWORD = SEARCH["keyword"]
URL_FILTERS = SEARCH["url_filters"]
MAX_PAGES = COLLECT["max_pages"]
CITY_DELAY = COLLECT["city_delay"]
BASE_DELAY = COLLECT["base_delay"]
MAX_RETRIES = COLLECT["max_retries"]
RATE_LIMIT_COOLDOWN = COLLECT["rate_limit_cooldown"]

job_list_api = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json"
job_detail_api = "https://www.zhipin.com/wapi/zpgeek/job/detail.json"
output_csv = os.path.join(PROJECT_DIR, "output", "boss_jobs.csv")
progress_file = os.path.join(PROJECT_DIR, "output", "city_progress.txt")
city_codes_file = os.path.join(PROJECT_DIR, "data", "city_codes.json")

# ==========================================
# 加载城市列表
# ==========================================
with open(city_codes_file, "r", encoding="utf-8") as f:
    CITY_CODES = json.load(f)

CITY_CODES = {k: v for k, v in CITY_CODES.items() if len(k) == 9 and k.startswith("101")}
city_list = [(code, name) for code, name in CITY_CODES.items()]
city_list.sort(key=lambda x: x[1])

# ==========================================
# 工具函数（不依赖浏览器）
# ==========================================
def safe_get(job, key, default=""):
    return job.get(key, default) if job.get(key) not in [None, "null"] else default

def safe_list(job, key):
    v = job.get(key)
    if isinstance(v, list):
        return ",".join(map(str, v))
    return ""

def safe_gps(job, field):
    gps = job.get("gps") or {}
    return gps.get(field, "")

def is_rate_limited(result):
    if not result:
        return False
    code = result.get("code", 0)
    msg = result.get("message", "")
    return code == 31 or "频繁" in msg or "稍后" in msg

def is_need_login(result):
    if not result:
        return False
    code = result.get("code", 0)
    msg = result.get("message", "")
    return code == 3 or "登录" in msg or "未登录" in msg

def collect_jobs_from_page(data, all_jobs):
    """从一页数据中提取岗位"""
    new_count = 0
    job_list = data["zpData"]["jobList"]
    for job in job_list:
        sid = safe_get(job, "securityId")
        if sid and sid not in all_jobs:
            all_jobs[sid] = {
                "securityId": sid,
                "encryptJobId": safe_get(job, "encryptJobId"),
                "jobName": safe_get(job, "jobName"),
                "salaryDesc": safe_get(job, "salaryDesc"),
                "skills": safe_list(job, "skills"),
                "welfareList": safe_list(job, "welfareList"),
                "jobExperience": safe_get(job, "jobExperience"),
                "jobDegree": safe_get(job, "jobDegree"),
                "cityName": safe_get(job, "cityName"),
                "areaDistrict": safe_get(job, "areaDistrict"),
                "businessDistrict": safe_get(job, "businessDistrict"),
                "longitude": safe_gps(job, "longitude"),
                "latitude": safe_gps(job, "latitude"),
                "brandName": safe_get(job, "brandName"),
                "brandStageName": safe_get(job, "brandStageName"),
                "brandIndustry": safe_get(job, "brandIndustry"),
                "brandScaleName": safe_get(job, "brandScaleName"),
            }
            new_count += 1
    return new_count

def build_and_save_csv(all_jobs, path):
    """用当前 all_jobs 构建 DataFrame 并保存"""
    job_items = list(all_jobs.values())
    df = pd.DataFrame(job_items)
    if "postDescription" not in df.columns:
        sec_idx = df.columns.get_loc("securityId")
        df.insert(sec_idx + 1, "postDescription", "")
        df.insert(sec_idx + 2, "activeTimeDesc", "")
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return df

# ==========================================
# 登录检测
# ==========================================
def wait_for_login(tab, url):
    tab.listen.start(targets=job_list_api)
    tab.get(url)
    try:
        res = tab.listen.wait(timeout=10)
        data = res.response.body
        if data and "zpData" in data and "jobList" in data["zpData"]:
            print("  检测到已登录")
            return data
    except Exception:
        pass

    print("  ⚠ 未登录或登录已过期，请在弹出的浏览器中登录")
    print("    登录成功后程序将自动检测并继续...")
    while True:
        try:
            res = tab.listen.wait()
            data = res.response.body
            if data and "zpData" in data and "jobList" in data["zpData"]:
                print("  检测到登录成功")
                return data
        except Exception:
            continue

def scrape_city(tab, city_code, city_name, all_jobs, first_page_data=None,
                max_pages=MAX_PAGES, base_delay=BASE_DELAY,
                max_retries=MAX_RETRIES, rate_limit_cooldown=RATE_LIMIT_COOLDOWN):
    """采集单个城市的所有分页岗位，返回 (新增岗位数, 状态)。
    若传入 first_page_data 则直接使用，不再请求第一页。"""
    search_url = f"https://www.zhipin.com/web/geek/jobs?city={city_code}&{URL_FILTERS}&query={KEYWORD}"

    if first_page_data:
        city_added = collect_jobs_from_page(first_page_data, all_jobs)
    else:
        try:
            tab.listen.stop()
        except Exception:
            pass
        tab.listen.start(targets=job_list_api)
        tab.get(search_url)
        try:
            res = tab.listen.wait(timeout=15)
            data = res.response.body
            if data and "zpData" in data and "jobList" in data["zpData"]:
                city_added = collect_jobs_from_page(data, all_jobs)
            else:
                return 0, "失败"
        except Exception:
            return 0, "失败"

    page = 1
    consecutive_errors = 0
    new_count = 0

    while page < max_pages:
        for attempt in range(1, max_retries + 1):
            try:
                tab.scroll.to_bottom()
                res = tab.listen.wait(timeout=15)
                data = res.response.body

                if is_rate_limited(data):
                    print(f"    ⚠ 限流，冷却 {rate_limit_cooldown}s...")
                    time.sleep(rate_limit_cooldown)
                    continue

                if is_need_login(data):
                    print("    ⚠ 登录过期，等待重新登录...")
                    wait_for_login(tab, search_url)
                    continue

                if not data or "zpData" not in data or "jobList" not in data["zpData"]:
                    time.sleep(base_delay * attempt)
                    continue

                new_count = collect_jobs_from_page(data, all_jobs)
                page += 1
                consecutive_errors = 0

                if new_count == 0:
                    break
                break

            except Exception as e:
                print(f"    ⚠ 重试 {attempt}/{max_retries}：{e}")
                time.sleep(base_delay * attempt)
                consecutive_errors += 1
        else:
            consecutive_errors += 1

        if new_count == 0 or consecutive_errors >= 5:
            break

    if consecutive_errors >= 5:
        status = "部分"
    else:
        status = "完成"

    return city_added, status


# ==========================================
# 核心：非交互式采集入口
# ==========================================
def run_collector(cities, output_csv_path=None, progress_file_path=None,
                  max_pages=None, city_delay=None, base_delay=None,
                  max_retries=None, rate_limit_cooldown=None, tab=None):
    """非交互式采集：给定城市列表，采集岗位列表+详情。

    Args:
        cities: [(city_code, city_name), ...]
        output_csv_path: 输出 CSV 路径（默认 ../output/boss_jobs.csv）
        progress_file_path: 进度文件路径（默认 ../output/city_progress.txt）
        max_pages: 每城市最大页数（默认使用 config 值）
        tab: 可复用的浏览器 tab（默认创建新浏览器）

    Returns:
        (DataFrame, output_csv_path)
    """
    mp = max_pages if max_pages is not None else MAX_PAGES
    cd = city_delay if city_delay is not None else CITY_DELAY
    bd = base_delay if base_delay is not None else BASE_DELAY
    mr = max_retries if max_retries is not None else MAX_RETRIES
    rc = rate_limit_cooldown if rate_limit_cooldown is not None else RATE_LIMIT_COOLDOWN

    out_csv = output_csv_path or output_csv
    prog_file = progress_file_path or progress_file

    own_browser = tab is None
    if own_browser:
        browser = Chromium()
        tab = browser.latest_tab

    try:
        # 加载已有数据
        all_jobs = {}
        if os.path.exists(out_csv):
            existing = pd.read_csv(out_csv)
            for _, row in existing.iterrows():
                sid = str(row["securityId"])
                all_jobs[sid] = row.to_dict()
            print(f"已加载 {len(all_jobs)} 条已有岗位数据")

        completed_cities = {}
        if os.path.exists(prog_file):
            with open(prog_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split("|")
                    if len(parts) >= 2:
                        completed_cities[parts[0]] = parts[1]
                    else:
                        completed_cities[parts[0]] = "完成"
            print(f"已加载 {len(completed_cities)} 条城市进度")

        # 阶段一：逐城市采集
        print("=" * 50)
        print(f"阶段一：逐城市采集（{len(cities)} 个城市，每城 {mp} 页）")
        print("=" * 50)

        pending_cities = [(c, n) for c, n in cities if completed_cities.get(c) != "完成"]
        if not pending_cities:
            print("所有城市已完成采集，直接进入阶段二")
            login_data = None
        else:
            first_code, first_name = pending_cities[0]
            first_url = f"https://www.zhipin.com/web/geek/jobs?city={first_code}&{URL_FILTERS}&query={KEYWORD}"
            login_data = wait_for_login(tab, first_url)

        total_city_jobs = 0
        login_used = False

        for idx, (city_code, city_name) in enumerate(cities):
            prev_status = completed_cities.get(city_code, "")
            if prev_status == "完成":
                continue
            if prev_status:
                print(f"\n[{idx + 1}/{len(cities)}] {city_name} ({city_code}) — 上次状态「{prev_status}」，重新采集")

            print(f"\n[{idx + 1}/{len(cities)}] {city_name} ({city_code})", end="")

            first_page = login_data if not login_used else None
            login_used = True
            city_added, status = scrape_city(
                tab, city_code, city_name, all_jobs, first_page_data=first_page,
                max_pages=mp, base_delay=bd, max_retries=mr, rate_limit_cooldown=rc)
            total_city_jobs += city_added

            print(f" → +{city_added} 条({status})，累计 {len(all_jobs)} 条")

            completed_cities[city_code] = status
            tmp = prog_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                for code, st in completed_cities.items():
                    f.write(f"{code}|{st}\n")
            os.replace(tmp, prog_file)

            build_and_save_csv(all_jobs, out_csv)
            time.sleep(cd)

        print(f"\n阶段一完成，累计 {len(all_jobs)} 个岗位\n")

        # 阶段二：采集岗位详情
        print("=" * 50)
        print("阶段二：采集岗位详情（逐条保存，可随时中断）...")
        print("=" * 50)

        df = build_and_save_csv(all_jobs, out_csv)
        sec_idx = df.columns.get_loc("securityId")
        if "postDescription" not in df.columns:
            df.insert(sec_idx + 1, "postDescription", "")
        if "activeTimeDesc" not in df.columns:
            df.insert(sec_idx + 2, "activeTimeDesc", "")

        df["postDescription"] = df["postDescription"].astype(str).replace("nan", "")
        df["activeTimeDesc"] = df["activeTimeDesc"].astype(str).replace("nan", "")
        job_items = df.to_dict("records")
        pending_jobs = [j for j in job_items if j.get("postDescription") == "" or j.get("activeTimeDesc") == ""]
        print(f"待获取详情：{len(pending_jobs)} / {len(job_items)} 个岗位")

        consecutive_detail_errors = 0

        for i, job in enumerate(pending_jobs):
            sid = job["securityId"]

            if i % 5 == 0:
                tab.get("https://www.zhipin.com/")

            desc = ""
            active_time = ""
            ok = False

            for attempt in range(1, mr + 1):
                try:
                    tab.listen.start(targets=job_detail_api)
                    tab.get(f"{job_detail_api}?securityId={sid}")
                    res = tab.listen.wait(timeout=15)
                    data = res.response.body

                    if is_rate_limited(data):
                        print(f"  ⚠ 触发限流，冷却 {rc}s...")
                        time.sleep(rc)
                        continue

                    if is_need_login(data):
                        first_url = f"https://www.zhipin.com/web/geek/jobs?city={cities[0][0]}&{URL_FILTERS}&query={KEYWORD}"
                        wait_for_login(tab, first_url)
                        continue

                    if not data or "zpData" not in data:
                        raise Exception("响应数据为空或格式异常")

                    desc = data.get("zpData", {}).get("jobInfo", {}).get("postDescription", "")
                    active_time = data.get("zpData", {}).get("bossInfo", {}).get("activeTimeDesc", "")
                    ok = True
                    break

                except Exception as e:
                    print(f"  ⚠ 重试 {attempt}/{mr}：{e}")
                    time.sleep(bd * attempt)

            if ok:
                df.loc[df["securityId"] == sid, "postDescription"] = desc
                df.loc[df["securityId"] == sid, "activeTimeDesc"] = active_time
                df.to_csv(out_csv, index=False, encoding="utf-8-sig")
                consecutive_detail_errors = 0
                print(f"[{i + 1}/{len(pending_jobs)}] {job.get('jobName', '')} @ {job.get('brandName', '')} — OK")
            else:
                df.loc[df["securityId"] == sid, "postDescription"] = ""
                df.loc[df["securityId"] == sid, "activeTimeDesc"] = ""
                df.to_csv(out_csv, index=False, encoding="utf-8-sig")
                consecutive_detail_errors += 1
                print(f"[{i + 1}/{len(pending_jobs)}] {sid} — 最终失败")

            if consecutive_detail_errors >= 10:
                print("连续失败过多，可能账号异常，中止详情采集")
                break

            time.sleep(bd)

        print(f"\n全部完成，共 {len(df)} 条记录 → {out_csv}")
        return df, out_csv

    finally:
        if own_browser:
            browser.quit()


# ==========================================
# 交互式入口
# ==========================================
if __name__ == "__main__":
    browser = Chromium()
    tab = browser.latest_tab

    print(f"\n已加载 {len(city_list)} 个城市")
    print("输入要采集的城市（逗号分隔，如：深圳,广州,杭州）")
    print("输入「全部」或直接回车 → 采集所有城市")
    user_input = input("> ").strip()

    if not user_input or user_input == "全部":
        selected_cities = city_list
    else:
        selected_cities = []
        name_to_code = {name: code for code, name in city_list}
        for part in user_input.split(","):
            part = part.strip()
            if not part:
                continue
            if part in name_to_code:
                selected_cities.append((name_to_code[part], part))
                continue
            matches = [(code, name) for code, name in city_list if part in name]
            if len(matches) == 1:
                selected_cities.append(matches[0])
            elif len(matches) > 1:
                print(f"  「{part}」匹配到多个：{[m[1] for m in matches]}")
                print(f"  请用更精确的名称，跳过此项")
            else:
                print(f"  「{part}」未匹配到任何城市，跳过")

    if not selected_cities:
        print("没有选中任何城市，退出")
        exit(0)

    print(f"选中 {len(selected_cities)} 个城市：{[name for _, name in selected_cities[:10]]}{'...' if len(selected_cities) > 10 else ''}")

    run_collector(selected_cities, tab=tab)
    browser.quit()
