# 分析 scheduler_test.log：每个按键相邻两次触发的时间差统计
import sys
from collections import defaultdict

log_path = sys.argv[1]
expected = {}  # key -> (interval, random)
for arg in sys.argv[2:]:
    k, iv, rnd = arg.split(":")
    expected[k] = (int(iv), int(rnd))

fires = defaultdict(list)
with open(log_path, encoding="utf-8") as f:
    for line in f:
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit():
            fires[parts[1]].append(int(parts[0]))

print(f"{'按键':<10}{'触发次数':>6}{'最小':>8}{'最大':>8}{'平均':>9}  期望范围")
ok = True
for k, ts in sorted(fires.items()):
    diffs = [b - a for a, b in zip(ts, ts[1:])]
    if not diffs:
        print(f"{k:<10}{len(ts):>6}  (触发不足 2 次)")
        ok = False
        continue
    iv, rnd = expected.get(k, (0, 0))
    if rnd:
        lo, hi = round(iv * 0.85), round(iv * 1.15)
    else:
        lo, hi = iv, iv
    # 调度节拍 10ms + Windows 计时器粒度 ~16ms，允许 30ms 容差
    passed = all(lo - 30 <= d <= hi + 30 for d in diffs)
    ok = ok and passed
    print(f"{k:<10}{len(ts):>6}{min(diffs):>8}{max(diffs):>8}{sum(diffs)/len(diffs):>9.1f}  {lo}-{hi}  {'PASS' if passed else 'FAIL'}")

sys.exit(0 if ok else 1)
