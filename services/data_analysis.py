# -*- coding: utf-8 -*-
"""Data analysis module"""

import json
import numpy as np
from config import get_db

# ========== 数据分析模块 ==========

def _extract_nested_field(data, field_path):
    """递归提取嵌套字段值，支持点分路径如 demographics.年龄"""
    parts = field_path.split('.', 1)
    if not isinstance(data, dict):
        return None
    val = data.get(parts[0])
    if len(parts) == 1:
        return val
    return _extract_nested_field(val, parts[1])


def _collect_field_paths(data, prefix=''):
    """递归收集JSON中所有叶子字段路径"""
    paths = []
    if isinstance(data, dict):
        for k, v in data.items():
            if k in ('confidence',):
                continue
            full = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                paths.extend(_collect_field_paths(v, full))
            elif isinstance(v, list):
                if v and isinstance(v[0], dict):
                    paths.extend(_collect_field_paths(v[0], full + '[]'))
                else:
                    paths.append(full)
            else:
                paths.append(full)
    return paths


def _is_numeric(val):
    """判断值是否可转换为数值"""
    if val is None:
        return False
    try:
        float(val)
        return True
    except (ValueError, TypeError):
        return False


def analyze_structured_data(record_ids, fields, analysis_type='descriptive'):
    """对选中记录的结构化数据进行统计分析，返回统计量和ECharts配置"""
    conn = get_db()
    c = conn.cursor()
    placeholders = ','.join(['?'] * len(record_ids))
    c.execute(f'SELECT extracted_data, create_time FROM medical_records WHERE id IN ({placeholders})',
              record_ids)
    rows = c.fetchall()
    conn.close()

    # 收集每个字段的数值
    field_values = {f: [] for f in fields}
    time_series = {f: [] for f in fields}

    for row in rows:
        if not row['extracted_data']:
            continue
        data = json.loads(row['extracted_data'])
        create_time = row['create_time'] or ''
        for field in fields:
            val = _extract_nested_field(data, field)
            if _is_numeric(val):
                field_values[field].append(float(val))
                time_series[field].append({'time': create_time, 'value': float(val)})

    # 计算统计量
    stats = {}
    for field, values in field_values.items():
        if not values:
            stats[field] = {'count': 0, 'msg': '无有效数值'}
            continue
        arr = np.array(values)
        stats[field] = {
            'count': len(values),
            'mean': round(float(np.mean(arr)), 2),
            'median': round(float(np.median(arr)), 2),
            'std': round(float(np.std(arr)), 2),
            'min': round(float(np.min(arr)), 2),
            'max': round(float(np.max(arr)), 2),
            'q1': round(float(np.percentile(arr, 25)), 2),
            'q3': round(float(np.percentile(arr, 75)), 2)
        }

    # 生成ECharts配置
    chart_configs = []
    valid_fields = [f for f in fields if field_values[f]]

    if analysis_type == 'descriptive' and valid_fields:
        # 柱状图：各字段均值对比
        chart_configs.append({
            'title': {'text': '字段均值对比', 'left': 'center'},
            'tooltip': {'trigger': 'axis'},
            'xAxis': {'type': 'category', 'data': [f.split('.')[-1] for f in valid_fields],
                       'axisLabel': {'rotate': 30}},
            'yAxis': {'type': 'value', 'name': '均值'},
            'series': [{
                'data': [stats[f]['mean'] for f in valid_fields],
                'type': 'bar',
                'itemStyle': {'color': '#2563eb'},
                'label': {'show': True, 'position': 'top'}
            }],
            'grid': {'bottom': 80}
        })

        # 箱线图：分布概览
        if len(valid_fields) <= 8:
            boxplot_data = []
            for f in valid_fields:
                s = stats[f]
                boxplot_data.append([s['min'], s['q1'], s['median'], s['q3'], s['max']])
            chart_configs.append({
                'title': {'text': '数据分布（箱线图）', 'left': 'center'},
                'tooltip': {'trigger': 'item'},
                'xAxis': {'type': 'category', 'data': [f.split('.')[-1] for f in valid_fields],
                           'axisLabel': {'rotate': 30}},
                'yAxis': {'type': 'value'},
                'series': [{
                    'type': 'boxplot',
                    'data': boxplot_data,
                    'itemStyle': {'color': '#dbeafe', 'borderColor': '#2563eb'}
                }],
                'grid': {'bottom': 80}
            })

    elif analysis_type == 'trend' and valid_fields:
        # 折线图：按时间趋势
        series_list = []
        colors = ['#2563eb', '#059669', '#d97706', '#dc2626', '#7c3aed']
        for i, f in enumerate(valid_fields):
            sorted_ts = sorted(time_series[f], key=lambda x: x['time'])
            series_list.append({
                'name': f.split('.')[-1],
                'type': 'line',
                'data': [item['value'] for item in sorted_ts],
                'smooth': True,
                'itemStyle': {'color': colors[i % len(colors)]}
            })
        all_times = sorted(set(
            item['time'] for f in valid_fields for item in time_series[f]
        ))
        chart_configs.append({
            'title': {'text': '时间趋势分析', 'left': 'center'},
            'tooltip': {'trigger': 'axis'},
            'legend': {'data': [f.split('.')[-1] for f in valid_fields], 'bottom': 0},
            'xAxis': {'type': 'category', 'data': all_times, 'axisLabel': {'rotate': 45}},
            'yAxis': {'type': 'value'},
            'series': series_list,
            'grid': {'bottom': 80}
        })

    elif analysis_type == 'distribution' and valid_fields:
        # 直方图：频次分布（取第一个字段）
        f = valid_fields[0]
        values = field_values[f]
        n_bins = min(10, max(3, len(values) // 2))
        hist_counts, bin_edges = np.histogram(values, bins=n_bins)
        bin_labels = [f"{bin_edges[i]:.1f}-{bin_edges[i+1]:.1f}" for i in range(len(hist_counts))]
        chart_configs.append({
            'title': {'text': f'{f.split(".")[-1]} 频次分布', 'left': 'center'},
            'tooltip': {'trigger': 'axis'},
            'xAxis': {'type': 'category', 'data': bin_labels, 'axisLabel': {'rotate': 30}},
            'yAxis': {'type': 'value', 'name': '频次'},
            'series': [{
                'data': [int(c) for c in hist_counts],
                'type': 'bar',
                'itemStyle': {'color': '#059669'}
            }],
            'grid': {'bottom': 80}
        })

        # 饼图：分段占比
        if len(valid_fields) == 1:
            pie_data = [{'name': bin_labels[i], 'value': int(hist_counts[i])}
                        for i in range(len(hist_counts)) if hist_counts[i] > 0]
            chart_configs.append({
                'title': {'text': f'{f.split(".")[-1]} 分段占比', 'left': 'center'},
                'tooltip': {'trigger': 'item', 'formatter': '{b}: {c} ({d}%)'},
                'series': [{
                    'type': 'pie',
                    'radius': ['40%', '70%'],
                    'data': pie_data,
                    'label': {'formatter': '{b}\n{d}%'}
                }]
            })

    return {'statistics': stats, 'charts': chart_configs}


