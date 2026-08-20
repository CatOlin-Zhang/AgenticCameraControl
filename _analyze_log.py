"""临时脚本：分析设备日志中的内存趋势"""
import re
from pathlib import Path

log_path = Path(r"C:\Users\阿根达斯\PycharmProjects\AgenticCameraControl\log_0_392_00.log")

mem_pattern = re.compile(
    r"the mem is: total (\d+)KB vaild (\d+)KB free (\d+)KB buffer (\d+)kB? cache (\d+)KB add (\d+)kB? cpu is ([\d.]+) temp (\d+)"
)

flush_count = 0
frame_nosync_count = 0
mem_samples = []
alarm_count = 0
rtsp_session_count = 0
error_keywords = {}

print("=== 开始分析日志 ===\n")
print(f"文件: {log_path}")
print(f"大小: {log_path.stat().st_size / 1024 / 1024:.1f} MB\n")

with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
    for line_no, line in enumerate(f, 1):
        # 内存采样
        m = mem_pattern.search(line)
        if m:
            mem_samples.append({
                "line": line_no,
                "total": int(m.group(1)),
                "valid": int(m.group(2)),
                "free": int(m.group(3)),
                "buffer": int(m.group(4)),
                "cache": int(m.group(5)),
                "add": int(m.group(6)),
                "cpu": float(m.group(7)),
                "temp": int(m.group(8)),
            })

        # flushData 统计
        if "flushData" in line:
            flush_count += 1

        # frame do not sync 统计
        if "frame do not sync" in line:
            frame_nosync_count += 1

        # 报警事件
        if "send alarm" in line or "sk_api_ai_xpt_send_alarm" in line:
            alarm_count += 1

        # RTSP 会话
        if "handleReq_Play" in line or "RtspSession" in line and "flushData" not in line and "frame do not sync" not in line:
            rtsp_session_count += 1

        # 关键词错误统计
        if "[{E}" in line:
            # 提取模块
            m2 = re.search(r"\[(\w+\.cpp:\d+)\]", line)
            if m2:
                key = m2.group(1)
                error_keywords[key] = error_keywords.get(key, 0) + 1

print(f"总行数: {line_no}")
print(f"\n--- 消息类型统计 ---")
print(f"flushData 消息数:       {flush_count} ({flush_count/line_no*100:.1f}%)")
print(f"frame do not sync 数:   {frame_nosync_count} ({frame_nosync_count/line_no*100:.1f}%)")
print(f"报警事件数:             {alarm_count}")
print(f"RTSP 会话相关:          {rtsp_session_count}")

print(f"\n--- 内存采样点（共 {len(mem_samples)} 个）---")
if mem_samples:
    # 打印前10个和后10个
    print(f"\n前10个采样点:")
    print(f"{'行号':>10} {'total':>8} {'valid':>8} {'free':>8} {'buffer':>7} {'cache':>7} {'add':>7} {'cpu':>6} {'temp':>5}")
    for s in mem_samples[:10]:
        print(f"{s['line']:>10} {s['total']:>7}KB {s['valid']:>7}KB {s['free']:>7}KB {s['buffer']:>6}KB {s['cache']:>6}KB {s['add']:>6}KB {s['cpu']:>5.1f}% {s['temp']:>4}°C")

    print(f"\n后10个采样点:")
    print(f"{'行号':>10} {'total':>8} {'valid':>8} {'free':>8} {'buffer':>7} {'cache':>7} {'add':>7} {'cpu':>6} {'temp':>5}")
    for s in mem_samples[-10:]:
        print(f"{s['line']:>10} {s['total']:>7}KB {s['valid']:>7}KB {s['free']:>7}KB {s['buffer']:>6}KB {s['cache']:>6}KB {s['add']:>6}KB {s['cpu']:>5.1f}% {s['temp']:>4}°C")

    # 内存趋势
    first_free = [s["free"] for s in mem_samples[:20]]
    last_free = [s["free"] for s in mem_samples[-20:]]
    avg_first = sum(first_free) / len(first_free) if first_free else 0
    avg_last = sum(last_free) / len(last_free) if last_free else 0

    min_free_sample = min(mem_samples, key=lambda x: x["free"])
    max_free_sample = max(mem_samples, key=lambda x: x["free"])

    print(f"\n--- 内存趋势分析 ---")
    print(f"初始平均 free (前20点):   {avg_first:.0f} KB ({avg_first/1024:.1f} MB)")
    print(f"末尾平均 free (后20点):   {avg_last:.0f} KB ({avg_last/1024:.1f} MB)")
    print(f"变化:                     {avg_last - avg_first:+.0f} KB")
    print(f"free 最低点:              {min_free_sample['free']} KB @ 行 {min_free_sample['line']}")
    print(f"free 最高点:              {max_free_sample['free']} KB @ 行 {max_free_sample['line']}")
    print(f"total 内存:               {mem_samples[0]['total']} KB ({mem_samples[0]['total']/1024:.1f} MB)")

    # CPU 趋势
    first_cpu = [s["cpu"] for s in mem_samples[:20]]
    last_cpu = [s["cpu"] for s in mem_samples[-20:]]
    avg_cpu_first = sum(first_cpu) / len(first_cpu) if first_cpu else 0
    avg_cpu_last = sum(last_cpu) / len(last_cpu) if last_cpu else 0
    max_cpu_sample = max(mem_samples, key=lambda x: x["cpu"])

    print(f"\n--- CPU 趋势 ---")
    print(f"初始平均 CPU (前20点):    {avg_cpu_first:.1f}%")
    print(f"末尾平均 CPU (后20点):    {avg_cpu_last:.1f}%")
    print(f"CPU 最高点:               {max_cpu_sample['cpu']}% @ 行 {max_cpu_sample['line']}")

print(f"\n--- 高频错误来源 TOP 15 ---")
sorted_errors = sorted(error_keywords.items(), key=lambda x: -x[1])[:15]
for src, cnt in sorted_errors:
    print(f"  {src:<45} {cnt:>6} 次")

# 检测 flushData 的 poller 分布
print(f"\n--- flushData poller 分布 ---")
poller_dist = {}
with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        if "flushData" in line:
            m = re.search(r"event poller (\d+):flushData", line)
            if m:
                p = m.group(1)
                poller_dist[p] = poller_dist.get(p, 0) + 1
for p, cnt in sorted(poller_dist.items(), key=lambda x: -x[1]):
    print(f"  poller {p}: {cnt:>8} 次")
