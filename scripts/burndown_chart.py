"""Перегенерация burndown-графика спринта 4 из docs/burndown-data.csv.

Запуск из корня репозитория: python scripts/burndown_chart.py
Срез по понедельникам: строка добавляется в CSV (kind=actual по факту,
kind=plan до подтверждения на синхре), затем график перегенерируется.
"""

import csv
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.font_manager as fm

for font in (
    "/usr/share/fonts/truetype/chinese/NotoSansSC-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
):
    if Path(font).exists():
        fm.fontManager.addfont(font)

import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Noto Sans SC"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs" / "burndown-data.csv"
OUT = ROOT / "docs" / "burndown.png"

rows = []
with DATA.open(encoding="utf-8") as f:
    for r in csv.DictReader(f):
        rows.append(
            {
                "date": datetime.strptime(r["date"], "%Y-%m-%d"),
                "hours": float(r["remaining_hours"]),
                "kind": r["kind"].strip(),
            }
        )

rows.sort(key=lambda r: r["date"])
start, end = rows[0], rows[-1]
total = rows[0]["hours"]
actual = [r for r in rows if r["kind"] == "actual"]
plan = [r for r in rows if r["kind"] == "plan"]

fig, ax = plt.subplots(figsize=(9.5, 5.2), dpi=150, constrained_layout=True)

# Идеальная линия: от полного борда к нулю равномерно по всему спринту
ax.plot(
    [start["date"], end["date"]],
    [total, 0],
    linestyle="--",
    color="#8a8a8a",
    linewidth=1.6,
    label="Идеальная линия",
)

# Факт: сплошная линия и заполненные точки
if actual:
    ax.plot(
        [r["date"] for r in actual],
        [r["hours"] for r in actual],
        color="#1f6feb",
        marker="o",
        markersize=7,
        linewidth=2.4,
        label="Факт (срезы)",
    )

# План срезов: пунктир от последнего факта и полые точки
if plan:
    px = ([actual[-1]["date"]] if actual else []) + [r["date"] for r in plan]
    py = ([actual[-1]["hours"]] if actual else []) + [r["hours"] for r in plan]
    ax.plot(px, py, color="#1f6feb", linestyle=":", linewidth=2)
    ax.plot(
        [r["date"] for r in plan],
        [r["hours"] for r in plan],
        marker="o",
        markersize=7,
        markerfacecolor="white",
        markeredgecolor="#1f6feb",
        linestyle="none",
        label="План срезов (подтверждается по факту)",
    )

# Вертикальные линии по понедельникам (синхры/срезы)
d = start["date"].replace(hour=0)
while d <= end["date"]:
    if d.weekday() == 0:
        ax.axvline(d, color="#d9d9d9", linewidth=0.8, zorder=0)
    d += timedelta(days=1)

ax.annotate(
    "срез 1 (факт):\nблокер M-0 — одобренные\nPR #5-#7 не смёржены",
    xy=(actual[-1]["date"], actual[-1]["hours"]) if actual else (start["date"], total),
    xytext=(datetime(2026, 11, 12), total * 0.80),
    fontsize=8.5,
    color="#333333",
    arrowprops={"arrowstyle": "->", "color": "#666666", "linewidth": 1},
)

ax.set_title(
    "Burndown спринта 4 — ВКР-трекер (03.11-30.11.2026, борд 93 ч)",
    fontsize=12,
    pad=10,
)
ax.set_ylabel("Осталось работы, ч")
ax.set_xlabel("Дата (срезы по понедельникам)")
ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
ax.set_ylim(0, total * 1.14)
ax.set_xlim(start["date"] - timedelta(days=1), end["date"] + timedelta(days=1))
ax.grid(True, axis="y", alpha=0.3)
ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1), frameon=False)

fig.savefig(OUT)
print(f"OK: {OUT} ({OUT.stat().st_size} bytes)")
print(
    f"Срезы: факт {len(actual)}, план {len(plan)}; борд {total} ч; на конец {rows[-1]['hours']} ч"
)
