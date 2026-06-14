#!/usr/bin/env python3
"""
空间天气与短波传播可视化分析
生成多维度图表展示空间天气参数与无线电传播的关系
"""

import json
import datetime
import argparse
from typing import List, Dict, Optional
import os

# 数据库连接配置
DEFAULT_DB_CONFIG = {
    "host": "ham.vlsc.net",
    "port": 9030,
    "user": "root",
    "password": "",
    "database": "pskreporter"
}


class SpaceWeatherVisualizer:
    """空间天气可视化生成器"""
    
    def __init__(self, db_config: dict = None, output_dir: str = "visualizations"):
        self.db_config = db_config or DEFAULT_DB_CONFIG
        self.output_dir = output_dir
        self._ensure_output_dir()
    
    def _ensure_output_dir(self):
        """确保输出目录存在"""
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
    
    def _query_database(self, sql: str) -> List[Dict]:
        """执行数据库查询"""
        try:
            import mysql.connector
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql)
            results = cursor.fetchall()
            cursor.close()
            conn.close()
            return results
        except Exception as e:
            print(f"数据库查询错误: {e}")
            return []
    
    def generate_html_report(self, days: int = 30) -> str:
        """
        生成综合分析HTML报告
        包含多个图表和关键指标
        """
        print(f"\n生成空间天气分析报告（过去 {days} 天）...")
        
        # 获取数据
        solar_data = self._get_solar_activity(days)
        geomag_data = self._get_geomagnetic_data(days)
        propagation_data = self._get_propagation_stats(days)
        
        # 生成HTML
        html_content = self._build_html_report(solar_data, geomag_data, propagation_data, days)
        
        # 保存文件
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"space_weather_report_{timestamp}.html"
        filepath = os.path.join(self.output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"报告已保存: {filepath}")
        return filepath
    
    def _get_solar_activity(self, days: int) -> List[Dict]:
        """获取太阳活动数据"""
        sql = f"""
        SELECT 
            observation_date,
            sunspot_number,
            f107_flux,
            data_source
        FROM solar_activity
        WHERE observation_date >= DATE_SUB(CURDATE(), INTERVAL {days} DAY)
        ORDER BY observation_date
        """
        return self._query_database(sql)
    
    def _get_geomagnetic_data(self, days: int) -> List[Dict]:
        """获取地磁活动数据"""
        sql = f"""
        SELECT 
            measurement_date,
            kp_value,
            dst_value,
            storm_level,
            storm_description
        FROM geomagnetic_indices
        WHERE measurement_date >= DATE_SUB(CURDATE(), INTERVAL {days} DAY)
        GROUP BY measurement_date
        ORDER BY measurement_date
        """
        return self._query_database(sql)
    
    def _get_propagation_stats(self, days: int) -> List[Dict]:
        """获取传播统计数据"""
        sql = f"""
        SELECT 
            DATE(q.qso_time) as qso_date,
            q.band,
            COUNT(*) as qso_count,
            AVG(q.snr) as avg_snr,
            AVG(q.distance) as avg_distance,
            COUNT(DISTINCT q.callsign) as unique_callsigns
        FROM qso_log q
        WHERE q.qso_time >= DATE_SUB(CURDATE(), INTERVAL {days} DAY)
        GROUP BY DATE(q.qso_time), q.band
        ORDER BY qso_date, FIELD(q.band, '160m', '80m', '40m', '30m', '20m', '17m', '15m', '12m', '10m', '6m')
        """
        return self._query_database(sql)
    
    def _build_html_report(self, solar_data: List[Dict], 
                          geomag_data: List[Dict], 
                          propagation_data: List[Dict],
                          days: int) -> str:
        """构建HTML报告"""
        
        # 准备图表数据
        solar_json = json.dumps(solar_data)
        geomag_json = json.dumps(geomag_data)
        propagation_json = json.dumps(propagation_data)
        
        # 计算关键指标
        latest_solar = solar_data[-1] if solar_data else {}
        latest_geomag = geomag_data[-1] if geomag_data else {}
        
        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>空间天气与短波传播分析报告</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #fff;
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        h1 {{
            text-align: center;
            margin-bottom: 10px;
            font-size: 2.5em;
            background: linear-gradient(45deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        .subtitle {{
            text-align: center;
            color: #888;
            margin-bottom: 30px;
        }}
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .metric-card {{
            background: rgba(255, 255, 255, 0.05);
            border-radius: 16px;
            padding: 20px;
            border: 1px solid rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
        }}
        .metric-label {{
            font-size: 0.9em;
            color: #888;
            margin-bottom: 8px;
        }}
        .metric-value {{
            font-size: 2em;
            font-weight: bold;
            color: #fff;
        }}
        .metric-status {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8em;
            margin-top: 8px;
        }}
        .status-good {{ background: #28a745; }}
        .status-moderate {{ background: #ffc107; color: #000; }}
        .status-poor {{ background: #dc3545; }}
        .chart-container {{
            background: rgba(255, 255, 255, 0.05);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 20px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}
        .chart-title {{
            font-size: 1.3em;
            margin-bottom: 15px;
            color: #ddd;
        }}
        .chart-wrapper {{
            position: relative;
            height: 300px;
        }}
        .grid-2 {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 20px;
        }}
        .info-section {{
            background: rgba(255, 255, 255, 0.03);
            border-radius: 12px;
            padding: 20px;
            margin-top: 20px;
        }}
        .info-section h3 {{
            color: #667eea;
            margin-bottom: 15px;
        }}
        .info-section ul {{
            list-style: none;
            padding-left: 0;
        }}
        .info-section li {{
            padding: 8px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }}
        .info-section li:before {{
            content: "▸";
            color: #667eea;
            margin-right: 10px;
        }}
        .band-legend {{
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            margin-top: 15px;
        }}
        .band-item {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .band-color {{
            width: 20px;
            height: 20px;
            border-radius: 4px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>空间天气与短波传播分析报告</h1>
        <p class="subtitle">分析时段: 过去 {days} 天 | 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        
        <!-- 关键指标卡片 -->
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-label">太阳黑子数 (SSN)</div>
                <div class="metric-value">{latest_solar.get('sunspot_number', 'N/A')}</div>
                <span class="metric-status {'status-good' if (latest_solar.get('sunspot_number') or 0) > 50 else 'status-moderate' if (latest_solar.get('sunspot_number') or 0) > 20 else 'status-poor'}">
                    {'高' if (latest_solar.get('sunspot_number') or 0) > 100 else '中' if (latest_solar.get('sunspot_number') or 0) > 50 else '低'}
                </span>
            </div>
            <div class="metric-card">
                <div class="metric-label">F10.7 通量</div>
                <div class="metric-value">{latest_solar.get('f107_flux', 'N/A')}</div>
                <span class="metric-status {'status-good' if (latest_solar.get('f107_flux') or 0) > 100 else 'status-moderate' if (latest_solar.get('f107_flux') or 0) > 70 else 'status-poor'}">
                    {'高' if (latest_solar.get('f107_flux') or 0) > 150 else '中' if (latest_solar.get('f107_flux') or 0) > 100 else '低'}
                </span>
            </div>
            <div class="metric-card">
                <div class="metric-label">Kp 指数</div>
                <div class="metric-value">{latest_geomag.get('kp_value', 'N/A')}</div>
                <span class="metric-status {'status-good' if (latest_geomag.get('kp_value') or 0) < 3 else 'status-moderate' if (latest_geomag.get('kp_value') or 0) < 5 else 'status-poor'}">
                    {latest_geomag.get('storm_description', '平静')}
                </span>
            </div>
            <div class="metric-card">
                <div class="metric-label">Dst 指数</div>
                <div class="metric-value">{latest_geomag.get('dst_value', 'N/A')} nT</div>
                <span class="metric-status {'status-good' if (latest_geomag.get('dst_value') or 0) > -20 else 'status-moderate' if (latest_geomag.get('dst_value') or 0) > -50 else 'status-poor'}">
                    {'平静' if (latest_geomag.get('dst_value') or 0) > -20 else '扰动' if (latest_geomag.get('dst_value') or 0) > -50 else '磁暴'}
                </span>
            </div>
        </div>
        
        <!-- 图表区域 -->
        <div class="grid-2">
            <div class="chart-container">
                <div class="chart-title">太阳活动趋势</div>
                <div class="chart-wrapper">
                    <canvas id="solarChart"></canvas>
                </div>
            </div>
            <div class="chart-container">
                <div class="chart-title">地磁活动指数</div>
                <div class="chart-wrapper">
                    <canvas id="geomagChart"></canvas>
                </div>
            </div>
        </div>
        
        <div class="chart-container">
            <div class="chart-title">各波段 QSO 数量分布</div>
            <div class="chart-wrapper">
                <canvas id="bandChart"></canvas>
            </div>
        </div>
        
        <div class="chart-container">
            <div class="chart-title">传播质量综合评分</div>
            <div class="chart-wrapper">
                <canvas id="scoreChart"></canvas>
            </div>
        </div>
        
        <!-- 说明信息 -->
        <div class="info-section">
            <h3>传播条件解读</h3>
            <ul>
                <li><strong>太阳黑子数 (SSN)</strong>: 反映太阳活动水平。>100为高活动期，高频段(20m/15m/10m)传播良好；<50为低活动期，低波段(40m/80m)更可靠。</li>
                <li><strong>F10.7 通量</strong>: 10.7cm射电辐射强度，与EUV辐射高度相关。>150为优秀，>100为良好，<70为较差。</li>
                <li><strong>Kp 指数</strong>: 3小时地磁活动指数。<3为平静，3-4为活跃，>5为磁暴期，高纬路径受影响。</li>
                <li><strong>Dst 指数</strong>: 环电流强度，负值表示磁暴。>-20nT为平静，-50至-100为中等磁暴，<-100为强磁暴。</li>
            </ul>
        </div>
        
        <div class="info-section">
            <h3>波段传播特性</h3>
            <div class="band-legend">
                <div class="band-item"><div class="band-color" style="background:#ff6b6b"></div><span>160m - 夜间/冬季</span></div>
                <div class="band-item"><div class="band-color" style="background:#f9ca24"></div><span>80m - 夜间/本地</span></div>
                <div class="band-item"><div class="band-color" style="background:#6c5ce7"></div><span>40m - 全天候</span></div>
                <div class="band-item"><div class="band-color" style="background:#a29bfe"></div><span>30m - 数字模式</span></div>
                <div class="band-item"><div class="band-color" style="background:#74b9ff"></div><span>20m - DX主力</span></div>
                <div class="band-item"><div class="band-color" style="background:#00b894"></div><span>17m -  openings</span></div>
                <div class="band-item"><div class="band-color" style="background:#55efc4"></div><span>15m - 高太阳活动</span></div>
                <div class="band-item"><div class="band-color" style="background:#ffeaa7"></div><span>12m - 太阳峰年</span></div>
                <div class="band-item"><div class="band-color" style="background:#fd79a8"></div><span>10m - 太阳活动</span></div>
                <div class="band-item"><div class="band-color" style="background:#e17055"></div><span>6m - 突发传播</span></div>
            </div>
        </div>
    </div>
    
    <script>
        // 数据
        const solarData = {solar_json};
        const geomagData = {geomag_json};
        const propagationData = {propagation_json};
        
        // 图表配置
        Chart.defaults.color = '#888';
        Chart.defaults.borderColor = 'rgba(255, 255, 255, 0.1)';
        
        // 太阳活动图表
        const solarCtx = document.getElementById('solarChart').getContext('2d');
        new Chart(solarCtx, {{
            type: 'line',
            data: {{
                labels: solarData.map(d => d.observation_date),
                datasets: [
                    {{
                        label: '太阳黑子数',
                        data: solarData.map(d => d.sunspot_number),
                        borderColor: '#ff6b6b',
                        backgroundColor: 'rgba(255, 107, 107, 0.1)',
                        tension: 0.4,
                        yAxisID: 'y'
                    }},
                    {{
                        label: 'F10.7 通量',
                        data: solarData.map(d => d.f107_flux),
                        borderColor: '#f9ca24',
                        backgroundColor: 'rgba(249, 202, 36, 0.1)',
                        tension: 0.4,
                        yAxisID: 'y1'
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                interaction: {{ mode: 'index', intersect: false }},
                scales: {{
                    y: {{
                        type: 'linear',
                        display: true,
                        position: 'left',
                        title: {{ display: true, text: '太阳黑子数' }}
                    }},
                    y1: {{
                        type: 'linear',
                        display: true,
                        position: 'right',
                        title: {{ display: true, text: 'F10.7 (sfu)' }},
                        grid: {{ drawOnChartArea: false }}
                    }}
                }}
            }}
        }});
        
        // 地磁活动图表
        const geomagCtx = document.getElementById('geomagChart').getContext('2d');
        new Chart(geomagCtx, {{
            type: 'line',
            data: {{
                labels: geomagData.map(d => d.measurement_date),
                datasets: [
                    {{
                        label: 'Kp 指数',
                        data: geomagData.map(d => d.kp_value),
                        borderColor: '#6c5ce7',
                        backgroundColor: 'rgba(108, 92, 231, 0.1)',
                        tension: 0.4,
                        yAxisID: 'y'
                    }},
                    {{
                        label: 'Dst 指数',
                        data: geomagData.map(d => d.dst_value),
                        borderColor: '#00b894',
                        backgroundColor: 'rgba(0, 184, 148, 0.1)',
                        tension: 0.4,
                        yAxisID: 'y1'
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                interaction: {{ mode: 'index', intersect: false }},
                scales: {{
                    y: {{
                        type: 'linear',
                        display: true,
                        position: 'left',
                        min: 0,
                        max: 9,
                        title: {{ display: true, text: 'Kp 指数' }}
                    }},
                    y1: {{
                        type: 'linear',
                        display: true,
                        position: 'right',
                        title: {{ display: true, text: 'Dst (nT)' }},
                        grid: {{ drawOnChartArea: false }}
                    }}
                }}
            }}
        }});
        
        // 波段QSO图表
        const bandData = {{}};
        propagationData.forEach(d => {{
            if (!bandData[d.band]) bandData[d.band] = [];
            bandData[d.band].push({{ x: d.qso_date, y: d.qso_count }});
        }});
        
        const bandColors = {{
            '160m': '#ff6b6b', '80m': '#f9ca24', '40m': '#6c5ce7',
            '30m': '#a29bfe', '20m': '#74b9ff', '17m': '#00b894',
            '15m': '#55efc4', '12m': '#ffeaa7', '10m': '#fd79a8', '6m': '#e17055'
        }};
        
        const bandCtx = document.getElementById('bandChart').getContext('2d');
        new Chart(bandCtx, {{
            type: 'bar',
            data: {{
                datasets: Object.keys(bandData).map(band => ({{
                    label: band,
                    data: bandData[band],
                    backgroundColor: bandColors[band] || '#888'
                }}))
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                    x: {{ type: 'category' }},
                    y: {{ beginAtZero: true, title: {{ display: true, text: 'QSO 数量' }} }}
                }}
            }}
        }});
        
        // 传播评分图表（综合）
        const scoreCtx = document.getElementById('scoreChart').getContext('2d');
        
        // 计算综合评分
        const scores = solarData.map((solar, idx) => {{
            const geomag = geomagData[idx] || {{}};
            const solarScore = Math.min((solar.f107_flux || 70) / 5, 40);
            const geomagScore = (geomag.kp_value || 0) < 3 ? 40 : Math.max(0, 40 - (geomag.kp_value - 3) * 10);
            return {{
                x: solar.observation_date,
                y: Math.round(solarScore + geomagScore)
            }};
        }});
        
        new Chart(scoreCtx, {{
            type: 'line',
            data: {{
                datasets: [{{
                    label: '传播条件评分',
                    data: scores,
                    borderColor: '#667eea',
                    backgroundColor: (ctx) => {{
                        const gradient = ctx.chart.ctx.createLinearGradient(0, 0, 0, 300);
                        gradient.addColorStop(0, 'rgba(102, 126, 234, 0.5)');
                        gradient.addColorStop(1, 'rgba(102, 126, 234, 0)');
                        return gradient;
                    }},
                    fill: true,
                    tension: 0.4
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                    y: {{
                        min: 0,
                        max: 80,
                        title: {{ display: true, text: '综合评分 (0-80)' }}
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>
'''
        return html
    
    def generate_json_export(self, days: int = 30) -> str:
        """生成JSON格式的数据导出"""
        print(f"\n导出空间天气数据（过去 {days} 天）...")
        
        # 获取综合数据
        sql = f"""
        SELECT 
            sa.observation_date as date,
            sa.sunspot_number,
            sa.f107_flux,
            gi.kp_value,
            gi.dst_value,
            gi.storm_level,
            COUNT(DISTINCT q.id) as qso_count,
            AVG(q.snr) as avg_snr,
            AVG(q.distance) as avg_distance
        FROM solar_activity sa
        LEFT JOIN geomagnetic_indices gi ON sa.observation_date = gi.measurement_date
        LEFT JOIN qso_log q ON sa.observation_date = DATE(q.qso_time)
        WHERE sa.observation_date >= DATE_SUB(CURDATE(), INTERVAL {days} DAY)
        GROUP BY sa.observation_date
        ORDER BY sa.observation_date
        """
        
        data = self._query_database(sql)
        
        # 保存JSON
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"space_weather_data_{timestamp}.json"
        filepath = os.path.join(self.output_dir, filename)
        
        export_data = {
            'generated_at': datetime.datetime.now().isoformat(),
            'days': days,
            'record_count': len(data),
            'data': data
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
        
        print(f"数据已导出: {filepath}")
        return filepath


def main():
    parser = argparse.ArgumentParser(
        description='空间天气与短波传播可视化分析工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --html --days 30          # 生成30天HTML报告
  %(prog)s --json --days 90          # 导出90天JSON数据
  %(prog)s --html --json --days 7    # 同时生成两种格式
        """
    )
    
    parser.add_argument('--html', action='store_true',
                        help='生成HTML可视化报告')
    parser.add_argument('--json', action='store_true',
                        help='导出JSON数据')
    parser.add_argument('--days', type=int, default=30,
                        help='分析天数 (默认: 30)')
    parser.add_argument('--output', type=str, default='visualizations',
                        help='输出目录 (默认: visualizations)')
    
    args = parser.parse_args()
    
    if not args.html and not args.json:
        parser.print_help()
        return
    
    # 创建可视化器
    visualizer = SpaceWeatherVisualizer(output_dir=args.output)
    
    # 生成报告
    if args.html:
        visualizer.generate_html_report(args.days)
    
    if args.json:
        visualizer.generate_json_export(args.days)
    
    print(f"\n完成！输出目录: {os.path.abspath(args.output)}")


if __name__ == '__main__':
    main()
