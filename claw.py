import time
import pandas as pd
from DrissionPage import Chromium
import os

# 指定用户数据目录，cookie 持久化，一次登录后续自动有效
browser = Chromium()
tab = browser.latest_tab

# ==========================================
# 配置：城市和关键词
# ==========================================
CITY_CODE = "101280700"        # 城市代码
KEYWORD = "大数据"               # 搜索关键词
MAX_PAGES = 30                  # 最大翻页数（防止无限滚动）
MAX_RETRIES = 3                 # 单次请求最大重试次数
BASE_DELAY = 10                 # 正常请求间隔（秒）
RATE_LIMIT_COOLDOWN = 90        # 触发限流后冷却时间（秒）

search_url = f"https://www.zhipin.com/web/geek/jobs?city={CITY_CODE}&query={KEYWORD}"
job_list_api = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json"
job_detail_api = "https://www.zhipin.com/wapi/zpgeek/job/detail.json"
output_csv = "boss_jobs.csv"

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
    """检测 API 返回是否触发限流"""
    if not result:
        return False
    code = result.get("code", 0)
    msg = result.get("message", "")
    return code == 31 or "频繁" in msg or "稍后" in msg

def is_need_login(result):
    """检测是否登录过期"""
    if not result:
        return False
    code = result.get("code", 0)
    msg = result.get("message", "")
    return code == 3 or "登录" in msg or "未登录" in msg

# ==========================================
# 自动检测登录状态
# ==========================================
def wait_for_login():
    """
    尝试等待第一页数据。
    短时间内拿到 → 已登录，直接返回数据。
    超时 → 需要登录，提示用户，然后无限等待直到拿到数据。
    """
    tab.listen.start(targets=job_list_api)
    tab.get(search_url)

    try:
        # 先尝试 10 秒内是否能拿到数据（已登录的情况）
        res = tab.listen.wait(timeout=10)
        data = res.response.body
        if data and "zpData" in data and "jobList" in data["zpData"]:
            print("检测到已登录，直接开始采集\n")
            return data
    except Exception:
        pass

    # 没有拿到数据，需要登录
    print("=" * 50)
    print("⚠ 未登录或登录已过期，请在弹出的浏览器中登录")
    print("  登录成功后程序将自动检测并继续...")
    print("=" * 50)

    # 无限等待，直到拿到有效数据
    while True:
        try:
            res = tab.listen.wait()
            data = res.response.body
            if data and "zpData" in data and "jobList" in data["zpData"]:
                print("检测到登录成功，开始采集\n")
                return data
        except Exception:
            continue

# ==========================================
# 阶段一：滚动翻页，采集岗位列表
# ==========================================
print("=" * 50)
print("阶段一：采集岗位列表...")
print("=" * 50)

# 等待登录（如果需要），拿到第一页数据
first_page_data = wait_for_login()

all_jobs = {}
page = 0

def collect_jobs(data):
    """从 API 返回数据中提取岗位，返回新增数量"""
    global all_jobs
    new_count = 0
    job_list = data["zpData"]["jobList"]
    for job in job_list:
        sid = safe_get(job, "securityId")
        if sid and sid not in all_jobs:
            all_jobs[sid] = {
                "securityId": sid,
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

# 处理第一页
new_count = collect_jobs(first_page_data)
page += 1
print(f"第 {page} 页：新增 {new_count} 条，累计 {len(all_jobs)} 条")

# 滚动翻页
consecutive_errors = 0

while page < MAX_PAGES:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            tab.scroll.to_bottom()
            res = tab.listen.wait(timeout=15)
            data = res.response.body

            if is_rate_limited(data):
                print(f"  ⚠ 触发限流，冷却 {RATE_LIMIT_COOLDOWN}s...")
                time.sleep(RATE_LIMIT_COOLDOWN)
                continue

            if is_need_login(data):
                print("  ⚠ 登录已过期，请在弹出的浏览器中重新登录")
                wait_for_login()
                continue

            if not data or "zpData" not in data or "jobList" not in data["zpData"]:
                print(f"  ⚠ 第 {page + 1} 页接口异常，重试 {attempt}/{MAX_RETRIES}")
                time.sleep(BASE_DELAY * attempt)
                continue

            new_count = collect_jobs(data)
            page += 1
            consecutive_errors = 0
            print(f"第 {page} 页：新增 {new_count} 条，累计 {len(all_jobs)} 条")

            if new_count == 0:
                print("没有新数据，翻页结束")
            break  # 成功，跳出重试循环

        except Exception as e:
            print(f"  ⚠ 第 {page + 1} 页异常，重试 {attempt}/{MAX_RETRIES}：{e}")
            time.sleep(BASE_DELAY * attempt)
            consecutive_errors += 1
    else:
        # 所有重试均失败
        print(f"❌ 第 {page + 1} 页最终失败，跳过")
        consecutive_errors += 1

    if new_count == 0 or consecutive_errors >= 5:
        print("连续异常过多或无新数据，翻页结束")
        break

tab.listen.stop()
print(f"\n阶段一完成，共采集 {len(all_jobs)} 个岗位\n")

# 阶段一完成后立即保存一份 CSV（postDescription 为空，后续逐条填充）
job_items = list(all_jobs.values())
df = pd.DataFrame(job_items)
sec_idx = df.columns.get_loc("securityId")
df.insert(sec_idx + 1, "postDescription", "")

def save_csv():
    """实时保存当前 DataFrame 到 CSV"""
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")

save_csv()
print(f"阶段一数据已保存 → {output_csv}\n")

# ==========================================
# 阶段二：逐个获取岗位详情（每获取一条就实时保存）
# ==========================================
print("=" * 50)
print("阶段二：采集岗位详情（逐条保存，可随时中断）...")
print("=" * 50)

consecutive_detail_errors = 0

for i, job in enumerate(job_items):
    sid = job["securityId"]

    # 每 5 次刷新主页保持 cookie
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
                print("  ⚠ 登录已过期，请在弹出的浏览器中重新登录")
                wait_for_login()
                continue

            if not data or "zpData" not in data:
                raise Exception("响应数据为空或格式异常")

            desc = data.get("zpData", {}).get("jobInfo", {}).get("postDescription", "")
            ok = True
            break

        except Exception as e:
            print(f"  ⚠ 重试 {attempt}/{MAX_RETRIES}：{e}")
            time.sleep(BASE_DELAY * attempt)

    if ok:
        df.loc[df["securityId"] == sid, "postDescription"] = desc
        save_csv()
        consecutive_detail_errors = 0
        print(f"[{i + 1}/{len(job_items)}] {job['jobName']} @ {job['brandName']} — OK")
    else:
        df.loc[df["securityId"] == sid, "postDescription"] = ""
        save_csv()
        consecutive_detail_errors += 1
        print(f"[{i + 1}/{len(job_items)}] {sid} — 最终失败")

    if consecutive_detail_errors >= 10:
        print("连续失败过多，可能账号异常，中止详情采集")
        break

    time.sleep(BASE_DELAY)

print(f"\n全部完成，共 {len(df)} 条记录 → {output_csv}")
