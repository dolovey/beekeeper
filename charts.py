import flet as ft

from constants import WOOD_LIGHT

NONE_HIVE_COLOR = "#888888"
NONE_HIVE_KEY = "__none__"


def make_weight_chart(measurements, hives_map=None, chart_w=560, chart_h=260):
    hives_map = hives_map or {}

    if not measurements:
        return ft.Container(
            height=chart_h, alignment=ft.alignment.center,
            content=ft.Column([
                ft.Icon(ft.Icons.SHOW_CHART, size=48, color="#CCCCCC"),
                ft.Text("Нет данных для графика", color="#666666"),
            ], alignment=ft.MainAxisAlignment.CENTER,
               horizontal_alignment=ft.CrossAxisAlignment.CENTER))

    # 1. Общая ось дат (все замеры всех ульев)
    all_dates = sorted({m.get("date", "") for m in measurements
                        if m.get("date")})
    if not all_dates:
        return ft.Container(
            height=chart_h, alignment=ft.alignment.center,
            content=ft.Text("Нет валидных дат", color="#666666"))
    dates_index = {d: i for i, d in enumerate(all_dates)}

    # 2. Группировка замеров по улью
    groups = {}
    for m in measurements:
        date = m.get("date", "")
        if not date:
            continue
        hid = m.get("hive_id") or NONE_HIVE_KEY
        groups.setdefault(hid, []).append(
            (dates_index[date], float(m.get("weight", 0))))

    # 3. Диапазон Y по всем весам
    all_weights = [float(m.get("weight", 0)) for m in measurements]
    min_w = min(all_weights)
    max_w = max(all_weights)
    pad = max(1.0, (max_w - min_w) * 0.1)
    y_min = max(0, min_w - pad)
    y_max = max_w + pad

    # 4. По одной серии на улей (сначала улья по порядку, потом "без улья")
    series = []
    legend_items = []

    ordered_keys = list(hives_map.keys())
    if NONE_HIVE_KEY in groups:
        ordered_keys.append(NONE_HIVE_KEY)

    for key in ordered_keys:
        if key not in groups:
            continue
        pts = sorted(groups[key])
        if not pts:
            continue

        if key == NONE_HIVE_KEY:
            color = NONE_HIVE_COLOR
            label = "Без улья"
        else:
            hive = hives_map.get(key) or {}
            color = hive.get("color") or WOOD_LIGHT
            label = f"№{hive.get('number', '?')}"

        data_points = [ft.LineChartDataPoint(x, y) for x, y in pts]
        series.append(ft.LineChartData(
            data_points=data_points,
            stroke_width=3,
            color=color,
            curved=True,
            stroke_cap_round=True,
        ))
        legend_items.append((color, label))

    # 5. Подписи по оси X
    bottom_labels = []
    step = max(1, len(all_dates) // 6)
    for i in range(0, len(all_dates), step):
        d = all_dates[i]
        short = d[5:] if len(d) >= 10 else d
        bottom_labels.append(ft.ChartAxisLabel(
            value=i,
            label=ft.Container(
                ft.Text(short, size=9, color="#666666"),
                padding=ft.padding.only(top=4))))

    chart = ft.LineChart(
        data_series=series,
        border=ft.border.all(1, "#E0E0E0"),
        horizontal_grid_lines=ft.ChartGridLines(color="#EEEEEE", width=1),
        vertical_grid_lines=ft.ChartGridLines(color="#EEEEEE", width=1),
        left_axis=ft.ChartAxis(
            labels_size=44,
            title=ft.Text("кг", size=11, color="#666666"),
            title_size=20,
            labels=[
                ft.ChartAxisLabel(
                    value=y_min,
                    label=ft.Text(f"{y_min:.1f}", size=10,
                                  color="#666666")),
                ft.ChartAxisLabel(
                    value=(y_min + y_max) / 2,
                    label=ft.Text(f"{(y_min + y_max) / 2:.1f}", size=10,
                                  color="#666666")),
                ft.ChartAxisLabel(
                    value=y_max,
                    label=ft.Text(f"{y_max:.1f}", size=10,
                                  color="#666666")),
            ]),
        bottom_axis=ft.ChartAxis(labels=bottom_labels, labels_size=28),
        min_y=y_min, max_y=y_max,
        min_x=0, max_x=max(1, len(all_dates) - 1),
        tooltip_bgcolor="#000000CC",
    )

    chart_container = ft.Container(content=chart,
                                    height=chart_h, width=chart_w)

    # 6. Легенда — только если ульев несколько
    if len(legend_items) > 1:
        legend = ft.Row(
            [ft.Row([
                ft.Container(width=12, height=12, bgcolor=c, border_radius=3),
                ft.Text(lbl, size=11, color="#333333"),
            ], spacing=4, tight=True)
             for c, lbl in legend_items],
            wrap=True, spacing=12, run_spacing=6)
        return ft.Column([legend, chart_container],
                         spacing=6, tight=True)

    return chart_container