import time
import json
import pandas as pd
from DrissionPage import Chromium
import os

browser = Chromium()
tab = browser.latest_tab

# ==========================================
# 加载配置
# ==========================================
with open("../config.json", "r", encoding="utf-8") as f:
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
output_csv = "../output/boss_jobs.csv"
progress_file = "../output/city_progress.txt"
city_codes_file = "../data/city_codes.json"

# ==========================================
# 加载城市列表
# ==========================================
with open(city_codes_file, "r", encoding="utf-8") as f:
    CITY_CODES = json.load(f)

# 排除"全国"和非标准代码
CITY_CODES = {k: v for k, v in CITY_CODES.items() if len(k) == 9 and k.startswith("101")}

city_list = [(code, name) for code, name in CITY_CODES.items()]
city_list.sort(key=lambda x: x[1])  # 按名称排序

# ==========================================
# 选择城市：输入城市名（逗号分隔）或输入"全部"
# ==========================================
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
        # 精确匹配
        if part in name_to_code:
            selected_cities.append((name_to_code[part], part))
            continue
        # 模糊匹配
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

# ==========================================
# 安全取值函数
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

# ==========================================
# 登录检测（首次进入搜索页时调用）
# ==========================================
def wait_for_login(url):
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

# ==========================================
# 加载已有数据和进度
# ==========================================
all_jobs = {}
if os.path.exists(output_csv):
    existing = pd.read_csv(output_csv)
    for _, row in existing.iterrows():
        sid = str(row["securityId"])
        all_jobs[sid] = row.to_dict()
    print(f"已加载 {len(all_jobs)} 条已有岗位数据")

completed_cities = {}  # city_code -> status
if os.path.exists(progress_file):
    with open(progress_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            if len(parts) >= 2:
                completed_cities[parts[0]] = parts[1]
            else:
                completed_cities[parts[0]] = "完成"  # 兼容旧格式
    print(f"已加载 {len(completed_cities)} 条城市进度")

# ==========================================
# 工具：采集单个城市的岗位列表
# ==========================================
def collect_jobs_from_page(data):
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

def scrape_city(city_code, city_name):
    """采集单个城市的所有分页岗位，返回 (新增岗位数, 状态)"""
    search_url = f"https://www.zhipin.com/web/geek/jobs?city={city_code}&{URL_FILTERS}&query={KEYWORD}"
    tab.listen.stop()
    tab.listen.start(targets=job_list_api)
    tab.get(search_url)

    # 等待第一页
    try:
        res = tab.listen.wait(timeout=15)
        data = res.response.body
        if data and "zpData" in data and "jobList" in data["zpData"]:
            city_added = collect_jobs_from_page(data)
        else:
            return 0, "失败"
    except Exception:
        return 0, "失败"

    page = 1
    consecutive_errors = 0
    new_count = 0  # 初始化为 0，MAX_PAGES=0 时不进循环也能用

    while page < MAX_PAGES:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                tab.scroll.to_bottom()
                res = tab.listen.wait(timeout=15)
                data = res.response.body

                if is_rate_limited(data):
                    print(f"    ⚠ 限流，冷却 {RATE_LIMIT_COOLDOWN}s...")
                    time.sleep(RATE_LIMIT_COOLDOWN)
                    continue

                if is_need_login(data):
                    print("    ⚠ 登录过期，等待重新登录...")
                    wait_for_login(search_url)
                    continue

                if not data or "zpData" not in data or "jobList" not in data["zpData"]:
                    time.sleep(BASE_DELAY * attempt)
                    continue

                new_count = collect_jobs_from_page(data)
                page += 1
                consecutive_errors = 0

                if new_count == 0:
                    break
                break  # success

            except Exception as e:
                print(f"    ⚠ 重试 {attempt}/{MAX_RETRIES}：{e}")
                time.sleep(BASE_DELAY * attempt)
                consecutive_errors += 1
        else:
            consecutive_errors += 1

        if new_count == 0 or consecutive_errors >= 5:
            break

    # new_count==0 → 自然无多余数据，完整；其他一律视为遗漏
    if new_count == 0:
        status = "完成"
    else:
        status = "部分"

    return city_added, status

# ==========================================
# 工具：保存 CSV
# ==========================================
def build_and_save_csv():
    """用当前 all_jobs 构建 DataFrame 并保存"""
    job_items = list(all_jobs.values())
    df = pd.DataFrame(job_items)
    if "postDescription" not in df.columns:
        sec_idx = df.columns.get_loc("securityId")
        df.insert(sec_idx + 1, "postDescription", "")
        df.insert(sec_idx + 2, "activeTimeDesc", "")
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    return df

# ==========================================
# 阶段一：逐城市采集岗位列表
# ==========================================
print("=" * 50)
print(f"阶段一：逐城市采集（{len(selected_cities)} 个城市，每城 {MAX_PAGES} 页）")
print("=" * 50)

# 首次登录
first_city_code, first_city_name = selected_cities[0]
first_url = f"https://www.zhipin.com/web/geek/jobs?city={first_city_code}&{URL_FILTERS}&query={KEYWORD}"
wait_for_login(first_url)

total_city_jobs = 0
need_login = False

for idx, (city_code, city_name) in enumerate(selected_cities):
    prev_status = completed_cities.get(city_code, "")
    if prev_status == "完成":
        continue
    if prev_status:
        print(f"\n[{idx + 1}/{len(selected_cities)}] {city_name} ({city_code}) — 上次状态「{prev_status}」，重新采集")

    print(f"\n[{idx + 1}/{len(selected_cities)}] {city_name} ({city_code})", end="")

    city_added, status = scrape_city(city_code, city_name)
    total_city_jobs += city_added

    print(f" → +{city_added} 条({status})，累计 {len(all_jobs)} 条")

    # 记录进度（每次全量写入，避免重复行）
    completed_cities[city_code] = status
    with open(progress_file, "w", encoding="utf-8") as f:
        for code, st in completed_cities.items():
            f.write(f"{code}|{st}\n")

    # 每个城市保存一次
    build_and_save_csv()

    time.sleep(CITY_DELAY)

print(f"\n阶段一完成，累计 {len(all_jobs)} 个岗位\n")

# ==========================================
# 阶段二：逐个获取岗位详情
# ==========================================
print("=" * 50)
print("阶段二：采集岗位详情（逐条保存，可随时中断）...")
print("=" * 50)

df = build_and_save_csv()
if "postDescription" not in df.columns:
    sec_idx = df.columns.get_loc("securityId")
    df.insert(sec_idx + 1, "postDescription", "")

# 筛选尚未获取详情的岗位
job_items = df.to_dict("records")
df["postDescription"] = df["postDescription"].astype(str).replace("nan", "")
if "activeTimeDesc" in df.columns:
    df["activeTimeDesc"] = df["activeTimeDesc"].astype(str).replace("nan", "")
pending_jobs = [j for j in job_items if str(j.get("postDescription")) == ""]
print(f"待获取详情：{len(pending_jobs)} / {len(job_items)} 个岗位")

consecutive_detail_errors = 0

for i, job in enumerate(pending_jobs):
    sid = job["securityId"]

    if i % 5 == 0:
        tab.get("https://www.zhipin.com/")

    desc = ""
    ok = False

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            tab.listen.start(targets=job_detail_api)
            tab.get(f"{job_detail_api}?securityId={sid}")
            res = tab.listen.wait(timeout=15)
            data = res.response.body

            if is_rate_limited(data):
                print(f"  ⚠ 触发限流，冷却 {RATE_LIMIT_COOLDOWN}s...")
                time.sleep(RATE_LIMIT_COOLDOWN)
                continue

            if is_need_login(data):
                first_url = f"https://www.zhipin.com/web/geek/jobs?city=101010100&{URL_FILTERS}&query={KEYWORD}"
                wait_for_login(first_url)
                continue

            if not data or "zpData" not in data:
                raise Exception("响应数据为空或格式异常")

            desc = data.get("zpData", {}).get("jobInfo", {}).get("postDescription", "")
            active_time = data.get("zpData", {}).get("bossInfo", {}).get("activeTimeDesc", "")
            ok = True
            break

        except Exception as e:
            print(f"  ⚠ 重试 {attempt}/{MAX_RETRIES}：{e}")
            time.sleep(BASE_DELAY * attempt)

    if ok:
        df.loc[df["securityId"] == sid, "postDescription"] = desc
        df.loc[df["securityId"] == sid, "activeTimeDesc"] = active_time
        df.to_csv(output_csv, index=False, encoding="utf-8-sig")
        consecutive_detail_errors = 0
        print(f"[{i + 1}/{len(pending_jobs)}] {job.get('jobName', '')} @ {job.get('brandName', '')} — OK")
    else:
        df.loc[df["securityId"] == sid, "postDescription"] = ""
        df.loc[df["securityId"] == sid, "activeTimeDesc"] = ""
        df.to_csv(output_csv, index=False, encoding="utf-8-sig")
        consecutive_detail_errors += 1
        print(f"[{i + 1}/{len(pending_jobs)}] {sid} — 最终失败")

    if consecutive_detail_errors >= 10:
        print("连续失败过多，可能账号异常，中止详情采集")
        break

    time.sleep(BASE_DELAY)

print(f"\n全部完成，共 {len(df)} 条记录 → {output_csv}")
