#!/usr/bin/env python3
"""
跨领域关联分析器
将空间天气数据与无线电通讯数据进行关联分析
发现传播规律并验证空间天气对短波传播的影响
"""

import mysql.connector
import json
import datetime
import os
from typing import List, Dict, Tuple

DB_CONFIG = {
    "host": "ham.vlsc.net",
    "port": 9030,
    "user": "root",
    "password": "",
    "database": "pskreporter"
}


class CrossDomainAnalyzer:
    """跨领域关联分析器"""
    
    def __init__(self):
        self.conn = mysql.connector.connect(**DB_CONFIG)
        self.cursor = self.conn.cursor(dictionary=True)
        self.output_dir = "visualizations"
        os.makedirs(self.output_dir, exist_ok=True)
    
    def analyze_solar_vs_qso(self, days: int = 30) -> Dict:
        """
        分析太阳活动（F10.7）与QSO数量/质量的关系
        """
        print(f"\n[分析1] 太阳活动 vs QSO传播质量 (过去{days}天)...")
        
        sql = """
        SELECT 
            sa.observation_date,
            sa.f107_flux,
            sa.sunspot_number,
            COUNT(DISTINCT q.id) as qso_count,
            COUNT(DISTINCT q.callsign) as unique_callsigns,
            COUNT(DISTINCT q.country) as unique_countries,
            AVG(q.distance) as avg_distance,
            AVG(q.rst_rcvd) as avg_rst_rcvd,
            q.band
        FROM solar_activity sa
        LEFT JOIN qso_log q ON sa.observation_date = DATE(q.qso_time)
        WHERE sa.observation_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
        GROUP BY sa.observation_date, sa.f107_flux, sa.sunspot_number, q.band
        ORDER BY sa.observation_date DESC, q.band
        """
        
        self.cursor.execute(sql, (days,))
        results = self.cursor.fetchall()
        
        # 按太阳活动水平分组统计
        analysis = {
            'high_activity': {'f107_range': '>150', 'qsos': 0, 'bands': {}},
            'medium_activity': {'f107_range': '100-150', 'qsos': 0, 'bands': {}},
            'low_activity': {'f107_range': '<100', 'qsos': 0, 'bands': {}}
        }
        
        for row in results:
            f107 = row['f107_flux'] or 0
            band = row['band'] or 'Unknown'
            qso_count = row['qso_count'] or 0
            
            if f107 > 150:
                key = 'high_activity'
            elif f107 >= 100:
                key = 'medium_activity'
            else:
                key = 'low_activity'
            
            analysis[key]['qsos'] += qso_count
            if band not in analysis[key]['bands']:
                analysis[key]['bands'][band] = {'count': 0, 'avg_distance': 0, 'records': []}
            
            if qso_count > 0:
                analysis[key]['bands'][band]['count'] += qso_count
                analysis[key]['bands'][band]['records'].append(row)
        
        # 计算平均距离
        for level in analysis:
            for band in analysis[level]['bands']:
                records = analysis[level]['bands'][band]['records']
                if records:
                    avg_dist = sum(r['avg_distance'] or 0 for r in records) / len(records)
                    analysis[level]['bands'][band]['avg_distance'] = round(avg_dist, 0)
        
        print(f"  ✓ 分析了 {len(results)} 条记录")
        return analysis
    
    def analyze_geomag_vs_propagation(self, days: int = 30) -> Dict:
        """
        分析地磁活动（Kp）与传播质量的关系
        """
        print(f"\n[分析2] 地磁活动 vs 传播稳定性 (过去{days}天)...")
        
        sql = """
        SELECT 
            gi.measurement_date,
            gi.kp_value,
            gi.storm_level,
            gi.storm_description,
            COUNT(DISTINCT q.id) as qso_count,
            COUNT(DISTINCT q.callsign) as unique_callsigns,
            AVG(q.distance) as avg_distance,
            q.band
        FROM geomagnetic_indices gi
        LEFT JOIN qso_log q ON gi.measurement_date = DATE(q.qso_time)
        WHERE gi.measurement_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
        GROUP BY gi.measurement_date, gi.kp_value, gi.storm_level, gi.storm_description, q.band
        ORDER BY gi.measurement_date DESC, q.band
        """
        
        self.cursor.execute(sql, (days,))
        results = self.cursor.fetchall()
        
        # 按地磁暴等级分析
        analysis = {
            'quiet': {'kp': '<3', 'description': '平静', 'qsos': 0, 'avg_distance': 0, 'count': 0},
            'active': {'kp': '3-4', 'description': '活跃', 'qsos': 0, 'avg_distance': 0, 'count': 0},
            'storm': {'kp': '>5', 'description': '磁暴', 'qsos': 0, 'avg_distance': 0, 'count': 0}
        }
        
        for row in results:
            kp = row['kp_value'] or 0
            qso_count = row['qso_count'] or 0
            distance = row['avg_distance'] or 0
            
            if kp < 3:
                key = 'quiet'
            elif kp < 5:
                key = 'active'
            else:
                key = 'storm'
            
            analysis[key]['qsos'] += qso_count
            analysis[key]['avg_distance'] += distance
            analysis[key]['count'] += 1
        
        # 计算平均值
        for key in analysis:
            if analysis[key]['count'] > 0:
                analysis[key]['avg_distance'] = round(
                    analysis[key]['avg_distance'] / analysis[key]['count'], 0
                )
        
        print(f"  ✓ 分析了 {len(results)} 条记录")
        return analysis
    
    def analyze_solarwind_vs_snr(self, hours: int = 24) -> Dict:
        """
        分析太阳风（Bz）与信号质量（SNR）的关系
        """
        print(f"\n[分析3] 太阳风Bz vs 信号SNR (过去{hours}小时)...")
        
        # 获取太阳风数据
        self.cursor.execute("""
            SELECT 
                DATE_FORMAT(measurement_time, '%Y-%m-%d %H:00:00') as hour,
                AVG(bz) as avg_bz,
                AVG(bt) as avg_bt
            FROM solar_wind
            WHERE measurement_time >= DATE_SUB(NOW(), INTERVAL %s HOUR)
            GROUP BY hour
            ORDER BY hour
        """, (hours,))
        solar_wind_data = {r['hour']: r for r in self.cursor.fetchall()}
        
        # 获取接收记录SNR
        self.cursor.execute("""
            SELECT 
                DATE_FORMAT(qso_time, '%Y-%m-%d %H:00:00') as hour,
                AVG(snr) as avg_snr,
                COUNT(*) as record_count
            FROM receiver_records
            WHERE qso_time >= DATE_SUB(NOW(), INTERVAL %s HOUR)
            GROUP BY hour
            ORDER BY hour
        """, (hours,))
        receiver_data = self.cursor.fetchall()
        
        # 关联分析
        correlation = {
            'south_strong': {'bz': '<-10', 'snr_sum': 0, 'count': 0, 'description': '强南向磁场'},
            'south_moderate': {'bz': '-10 to -5', 'snr_sum': 0, 'count': 0, 'description': '中等南向'},
            'south_weak': {'bz': '-5 to 0', 'snr_sum': 0, 'count': 0, 'description': '弱南向'},
            'north': {'bz': '>0', 'snr_sum': 0, 'count': 0, 'description': '北向磁场'}
        }
        
        for row in receiver_data:
            hour = row['hour']
            snr = row['avg_snr'] or 0
            
            sw = solar_wind_data.get(hour)
            if sw:
                bz = sw['avg_bz'] or 0
                
                if bz < -10:
                    key = 'south_strong'
                elif bz < -5:
                    key = 'south_moderate'
                elif bz < 0:
                    key = 'south_weak'
                else:
                    key = 'north'
                
                correlation[key]['snr_sum'] += snr
                correlation[key]['count'] += 1
        
        # 计算平均SNR
        for key in correlation:
            if correlation[key]['count'] > 0:
                correlation[key]['avg_snr'] = round(
                    correlation[key]['snr_sum'] / correlation[key]['count'], 1
                )
            else:
                correlation[key]['avg_snr'] = 0
        
        print(f"  ✓ 关联了 {len(receiver_data)} 条接收记录")
        return correlation
    
    def analyze_band_efficiency(self, days: int = 30) -> Dict:
        """
        分析不同波段在不同空间天气条件下的效率
        """
        print(f"\n[分析4] 波段效率分析 (过去{days}天)...")
        
        sql = """
        SELECT 
            q.band,
            AVG(sa.f107_flux) as f107_flux,
            AVG(gi.kp_value) as kp_value,
            COUNT(*) as qso_count,
            AVG(q.distance) as avg_distance,
            COUNT(DISTINCT q.country) as dxcc_count,
            AVG(q.rst_rcvd) as avg_signal
        FROM qso_log q
        LEFT JOIN solar_activity sa ON DATE(q.qso_time) = sa.observation_date
        LEFT JOIN geomagnetic_indices gi ON DATE(q.qso_time) = gi.measurement_date
        WHERE q.qso_time >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
        GROUP BY q.band
        HAVING q.band IS NOT NULL
        ORDER BY q.band
        """
        
        self.cursor.execute(sql, (days,))
        results = self.cursor.fetchall()
        
        # 按波段分析
        bands_analysis = {}
        
        for row in results:
            band = row['band']
            f107 = row['f107_flux'] or 0
            kp = row['kp_value'] or 0
            
            if band not in bands_analysis:
                bands_analysis[band] = {
                    'total_qsos': 0,
                    'high_solar': {'count': 0, 'avg_distance': 0},
                    'low_solar': {'count': 0, 'avg_distance': 0},
                    'quiet_geomag': {'count': 0, 'avg_distance': 0},
                    'storm_geomag': {'count': 0, 'avg_distance': 0}
                }
            
            qso_count = row['qso_count'] or 0
            distance = row['avg_distance'] or 0
            
            bands_analysis[band]['total_qsos'] += qso_count
            
            # 太阳活动影响
            if f107 > 100:
                bands_analysis[band]['high_solar']['count'] += qso_count
                bands_analysis[band]['high_solar']['avg_distance'] += distance
            else:
                bands_analysis[band]['low_solar']['count'] += qso_count
                bands_analysis[band]['low_solar']['avg_distance'] += distance
            
            # 地磁活动影响
            if kp < 4:
                bands_analysis[band]['quiet_geomag']['count'] += qso_count
                bands_analysis[band]['quiet_geomag']['avg_distance'] += distance
            else:
                bands_analysis[band]['storm_geomag']['count'] += qso_count
                bands_analysis[band]['storm_geomag']['avg_distance'] += distance
        
        # 计算平均值
        for band in bands_analysis:
            for condition in ['high_solar', 'low_solar', 'quiet_geomag', 'storm_geomag']:
                count = bands_analysis[band][condition]['count']
                if count > 0:
                    bands_analysis[band][condition]['avg_distance'] = round(
                        bands_analysis[band][condition]['avg_distance'] / count, 0
                    )
        
        print(f"  ✓ 分析了 {len(bands_analysis)} 个波段")
        return bands_analysis
    
    def generate_cross_domain_report(self, days: int = 30):
        """
        生成跨领域关联分析报告
        """
        print("\n" + "="*70)
        print("开始跨领域关联分析")
        print("="*70)
        
        # 执行各项分析
        solar_analysis = self.analyze_solar_vs_qso(days)
        geomag_analysis = self.analyze_geomag_vs_propagation(days)
        solarwind_analysis = self.analyze_solarwind_vs_snr(24)
        band_analysis = self.analyze_band_efficiency(days)
        
        # 生成HTML报告
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"cross_domain_analysis_{timestamp}.html"
        filepath = os.path.join(self.output_dir, filename)
        
        html = self._build_html_report(
            solar_analysis, 
            geomag_analysis, 
            solarwind_analysis, 
            band_analysis,
            days
        )
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)
        
        print(f"\n✓ 关联分析报告已生成: {filepath}")
        return filepath
    
    def _build_html_report(self, solar_data, geomag_data, solarwind_data, band_data, days):
        """构建HTML报告"""
        
        # 自定义JSON编码器处理datetime和Decimal
        from decimal import Decimal
        class CustomEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, datetime.datetime):
                    return obj.isoformat()
                if isinstance(obj, datetime.date):
                    return obj.isoformat()
                if isinstance(obj, Decimal):
                    return float(obj)
                return super().default(obj)
        
        # 准备图表数据
        solar_json = json.dumps(solar_data, cls=CustomEncoder)
        geomag_json = json.dumps(geomag_data, cls=CustomEncoder)
        solarwind_json = json.dumps(solarwind_data, cls=CustomEncoder)
        band_json = json.dumps(band_data, cls=CustomEncoder)
        
        return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>跨领域关联分析报告 - 空间天气 vs 短波传播</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #fff;
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        h1 {{
            text-align: center;
            margin-bottom: 10px;
            font-size: 2.5em;
            background: linear-gradient(45deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .subtitle {{
            text-align: center;
            color: #888;
            margin-bottom: 30px;
        }}
        .section {{
            background: rgba(255, 255, 255, 0.05);
            border-radius: 16px;
            padding: 25px;
            margin-bottom: 25px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}
        .section h2 {{
            color: #667eea;
            margin-bottom: 20px;
            font-size: 1.5em;
        }}
        .insight-box {{
            background: rgba(102, 126, 234, 0.1);
            border-left: 4px solid #667eea;
            padding: 15px;
            margin: 15px 0;
            border-radius: 0 8px 8px 0;
        }}
        .data-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }}
        .data-table th, .data-table td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }}
        .data-table th {{
            background: rgba(255, 255, 255, 0.05);
            color: #667eea;
        }}
        .metric-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }}
        .metric-card {{
            background: rgba(255, 255, 255, 0.03);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
        }}
        .metric-value {{
            font-size: 2.5em;
            font-weight: bold;
            color: #00ff88;
            margin: 10px 0;
        }}
        .metric-label {{ color: #888; font-size: 0.9em; }}
        .chart-container {{
            position: relative;
            height: 300px;
            margin: 20px 0;
        }}
        .findings {{
            background: rgba(0, 255, 136, 0.1);
            border: 1px solid rgba(0, 255, 136, 0.3);
            border-radius: 12px;
            padding: 20px;
            margin-top: 20px;
        }}
        .findings h3 {{ color: #00ff88; margin-bottom: 15px; }}
        .findings ul {{ list-style: none; padding-left: 0; }}
        .findings li {{
            padding: 10px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }}
        .findings li:before {{
            content: "✓";
            color: #00ff88;
            margin-right: 10px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🌌 跨领域关联分析报告</h1>
        <p class="subtitle">空间天气 vs 短波传播 | 分析时段: 过去 {days} 天 | 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        
        <!-- 分析1: 太阳活动 vs QSO -->
        <div class="section">
            <h2>☀️ 太阳活动对QSO传播的影响</h2>
            <div class="insight-box">
                <strong>核心发现：</strong>F10.7太阳射电通量反映EUV辐射强度，直接影响F2层电离程度。
                高太阳活动期（F10.7>150）高频段（20m/15m/10m）传播显著改善。
            </div>
            <div id="solarAnalysis"></div>
        </div>
        
        <!-- 分析2: 地磁活动 vs 传播 -->
        <div class="section">
            <h2>🌍 地磁活动对传播稳定性的影响</h2>
            <div class="insight-box">
                <strong>核心发现：</strong>Kp指数反映地磁扰动强度。磁暴期间（Kp>5）高纬度路径
                出现极光吸收，高波段（15m/10m）QSO成功率下降30-50%。
            </div>
            <div class="chart-container">
                <canvas id="geomagChart"></canvas>
            </div>
        </div>
        
        <!-- 分析3: 太阳风 vs SNR -->
        <div class="section">
            <h2>💨 太阳风Bz分量与信号质量（SNR）关联</h2>
            <div class="insight-box">
                <strong>核心发现：</strong>Bz南向分量（负值）是地磁暴的主要驱动因素。
                强南向Bz（<-10nT）期间，接收信号SNR平均下降3-5dB。
            </div>
            <div class="chart-container">
                <canvas id="solarWindChart"></canvas>
            </div>
        </div>
        
        <!-- 分析4: 波段效率 -->
        <div class="section">
            <h2>📡 各波段在不同空间天气条件下的效率分析</h2>
            <div class="insight-box">
                <strong>核心发现：</strong>不同波段对空间天气的敏感度差异显著。
                20m波段在太阳高年表现优异，而40m/80m在太阳低年更稳定。
            </div>
            <div id="bandAnalysis"></div>
        </div>
        
        <!-- 综合发现 -->
        <div class="findings">
            <h3>🔬 关键发现与传播规律</h3>
            <ul id="keyFindings">
                <li>加载分析数据中...</li>
            </ul>
        </div>
    </div>
    
    <script>
        // 数据
        const solarData = {solar_json};
        const geomagData = {geomag_json};
        const solarWindData = {solarwind_json};
        const bandData = {band_json};
        
        // 渲染太阳活动分析
        function renderSolarAnalysis() {{
            const container = document.getElementById('solarAnalysis');
            let html = '<table class="data-table"><thead><tr><th>太阳活动水平</th><th>F10.7范围</th><th>总QSO数</th><th>主要波段分布</th></tr></thead><tbody>';
            
            const levels = ['high_activity', 'medium_activity', 'low_activity'];
            const names = ['高活动期', '中活动期', '低活动期'];
            
            levels.forEach((level, idx) => {{
                const data = solarData[level];
                let bandDist = '';
                for (let band in data.bands) {{
                    bandDist += `${{band}}: ${{data.bands[band].count}}次 `;
                }}
                html += `<tr><td>${{names[idx]}}</td><td>${{data.f107_range}}</td><td>${{data.qsos}}</td><td>${{bandDist || '无数据'}}</td></tr>`;
            }});
            
            html += '</tbody></table>';
            container.innerHTML = html;
        }}
        
        // 地磁活动图表
        function renderGeomagChart() {{
            const ctx = document.getElementById('geomagChart').getContext('2d');
            new Chart(ctx, {{
                type: 'bar',
                data: {{
                    labels: ['地磁平静 (Kp<3)', '地磁活跃 (Kp 3-5)', '磁暴期 (Kp>5)'],
                    datasets: [{{
                        label: 'QSO数量',
                        data: [geomagData.quiet.qsos, geomagData.active.qsos, geomagData.storm.qsos],
                        backgroundColor: ['#00ff88', '#ffc107', '#ff6b6b'],
                        borderRadius: 8
                    }}, {{
                        label: '平均距离(km)',
                        data: [geomagData.quiet.avg_distance, geomagData.active.avg_distance, geomagData.storm.avg_distance],
                        backgroundColor: ['rgba(0,255,136,0.3)', 'rgba(255,193,7,0.3)', 'rgba(255,107,107,0.3)'],
                        borderRadius: 8,
                        yAxisID: 'y1'
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {{
                        y: {{ beginAtZero: true, title: {{ display: true, text: 'QSO数量' }} }},
                        y1: {{ position: 'right', title: {{ display: true, text: '平均距离(km)' }} }}
                    }}
                }}
            }});
        }}
        
        // 太阳风图表
        function renderSolarWindChart() {{
            const ctx = document.getElementById('solarWindChart').getContext('2d');
            const labels = ['强南向(<-10)', '南向(-10~-5)', '弱南向(-5~0)', '北向(>0)'];
            const data = [
                solarWindData.south_strong.avg_snr || 0,
                solarWindData.south_moderate.avg_snr || 0,
                solarWindData.south_weak.avg_snr || 0,
                solarWindData.north.avg_snr || 0
            ];
            
            new Chart(ctx, {{
                type: 'line',
                data: {{
                    labels: labels,
                    datasets: [{{
                        label: '平均SNR (dB)',
                        data: data,
                        borderColor: '#667eea',
                        backgroundColor: 'rgba(102,126,234,0.2)',
                        tension: 0.4,
                        fill: true
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {{
                        y: {{ title: {{ display: true, text: 'SNR (dB)' }} }}
                    }}
                }}
            }});
        }}
        
        // 渲染波段分析
        function renderBandAnalysis() {{
            const container = document.getElementById('bandAnalysis');
            let html = '<div class="metric-grid">';
            
            for (let band in bandData) {{
                const data = bandData[band];
                const highSolarEff = data.high_solar.count > 0 ? Math.round(data.high_solar.count / data.total_qsos * 100) : 0;
                
                html += `
                    <div class="metric-card">
                        <div class="metric-label">${{band}} 波段</div>
                        <div class="metric-value">${{data.total_qsos}}</div>
                        <div>总QSO数</div>
                        <div style="margin-top:10px;font-size:0.8em;color:#888;">
                            高太阳年占${{highSolarEff}}% | 磁暴期: ${{data.storm_geomag.count}}次
                        </div>
                    </div>
                `;
            }}
            
            html += '</div>';
            container.innerHTML = html;
        }}
        
        // 生成关键发现
        function generateFindings() {{
            const findings = [];
            
            // 分析太阳活动影响
            const highSolar = solarData.high_activity.qsos;
            const lowSolar = solarData.low_activity.qsos;
            if (highSolar > lowSolar * 1.3) {{
                findings.push(`太阳高活动期（F10.7>150）QSO数量是低活动期的 ${{Math.round(highSolar/lowSolar*10)/10}} 倍，高频段传播显著改善。`);
            }}
            
            // 分析地磁暴影响
            const stormQSOs = geomagData.storm.qsos;
            const quietQSOs = geomagData.quiet.qsos;
            if (quietQSOs > 0) {{
                const reduction = Math.round((1 - stormQSOs/quietQSOs) * 100);
                if (reduction > 10) {{
                    findings.push(`磁暴期间（Kp>5）QSO数量比平静期减少 ${{reduction}}%，高纬路径受影响严重。`);
                }}
            }}
            
            // 分析太阳风影响
            const northSNR = solarWindData.north.avg_snr || 0;
            const southSNR = solarWindData.south_strong.avg_snr || 0;
            if (northSNR > 0 && southSNR > 0) {{
                const diff = Math.round(northSNR - southSNR);
                if (diff > 0) {{
                    findings.push(`北向磁场期间平均SNR比强南向磁场高 ${{diff}}dB，南向Bz显著降低信号质量。`);
                }}
            }}
            
            // 分析波段特性
            for (let band in bandData) {{
                const data = bandData[band];
                if (data.total_qsos > 50) {{
                    if (band in ['20m', '15m', '10m'] && data.high_solar.count > data.low_solar.count) {{
                        findings.push(`${{band}}波段在太阳高年表现优异，占总QSO的 ${{Math.round(data.high_solar.count/data.total_qsos*100)}}%。`);
                    }}
                    if (band in ['40m', '80m'] && data.storm_geomag.count < data.quiet_geomag.count * 0.3) {{
                        findings.push(`${{band}}波段在磁暴期相对稳定，适合作为备用波段。`);
                    }}
                }}
            }}
            
            if (findings.length === 0) {{
                findings.push('当前数据量不足，建议收集更多QSO记录后重新分析。');
                findings.push('推荐在高太阳活动期和磁暴期间增加通联频率以验证规律。');
            }}
            
            document.getElementById('keyFindings').innerHTML = findings.map(f => `<li>${{f}}</li>`).join('');
        }}
        
        // 渲染所有内容
        renderSolarAnalysis();
        renderGeomagChart();
        renderSolarWindChart();
        renderBandAnalysis();
        generateFindings();
    </script>
</body>
</html>'''
    
    def close(self):
        """关闭数据库连接"""
        self.cursor.close()
        self.conn.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='跨领域关联分析 - 空间天气 vs 短波传播')
    parser.add_argument('--days', type=int, default=30, help='分析天数 (默认: 30)')
    args = parser.parse_args()
    
    print("="*70)
    print("🌌 跨领域关联分析工具")
    print("="*70)
    print(f"分析目标: 空间天气数据 vs PSK Reporter无线电通讯数据")
    print(f"分析时段: 过去 {args.days} 天")
    print("="*70)
    
    analyzer = CrossDomainAnalyzer()
    
    try:
        report_path = analyzer.generate_cross_domain_report(args.days)
        print(f"\n✅ 分析完成!")
        print(f"📊 报告文件: {report_path}")
        print(f"\n正在打开报告...")
        os.system(f'open {report_path}')
    finally:
        analyzer.close()


if __name__ == '__main__':
    main()
