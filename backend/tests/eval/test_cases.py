"""
Agent 评估测试用例

每个用例定义：
- 输入参数（城市、天数、偏好等）
- 期望标准（最少景点数、必须包含的关键词、期望的景点类型）
"""

TEST_CASES = [
    {
        "name": "北京2日历史文化",
        "request": {
            "city": "北京",
            "start_date": "2025-07-01",
            "end_date": "2025-07-02",
            "travel_days": 2,
            "transportation": "公共交通",
            "accommodation": "经济型酒店",
            "preferences": ["历史文化"],
            "free_text_input": "",
        },
        "expected": {
            "min_attractions": 4,        # 2天 × 2个景点/天
            "min_meals_per_day": 3,       # 早中晚
            "keywords": ["故宫", "博物馆", "历史", "文化", "宫", "寺", "胡同"],
            "preference_keywords": ["历史", "文化", "古", "博物", "故宫"],
            "max_budget": 5000,
            "min_budget": 100,
        },
    },
    {
        "name": "杭州2日自然风光",
        "request": {
            "city": "杭州",
            "start_date": "2025-08-10",
            "end_date": "2025-08-11",
            "travel_days": 2,
            "transportation": "自驾",
            "accommodation": "民宿",
            "preferences": ["自然风光"],
            "free_text_input": "",
        },
        "expected": {
            "min_attractions": 4,
            "min_meals_per_day": 3,
            "keywords": ["西湖", "灵隐", "龙井", "千岛湖", "西溪", "雷峰", "运河"],
            "preference_keywords": ["湖", "山", "自然", "风景", "林", "泉", "茶园"],
            "max_budget": 5000,
            "min_budget": 100,
        },
    },
    {
        "name": "成都3日美食之旅",
        "request": {
            "city": "成都",
            "start_date": "2025-09-15",
            "end_date": "2025-09-17",
            "travel_days": 3,
            "transportation": "公共交通",
            "accommodation": "舒适型酒店",
            "preferences": ["美食", "休闲"],
            "free_text_input": "想去本地人常去的馆子",
        },
        "expected": {
            "min_attractions": 6,        # 3天 × 2个景点
            "min_meals_per_day": 3,
            "keywords": ["宽窄", "锦里", "春熙", "武侯", "都江堰", "青城", "大熊猫", "文殊院"],
            "preference_keywords": ["美食", "小吃", "火锅", "茶馆", "休闲"],
            "max_budget": 8000,
            "min_budget": 200,
        },
    },
    {
        "name": "上海1日购物",
        "request": {
            "city": "上海",
            "start_date": "2025-10-01",
            "end_date": "2025-10-01",
            "travel_days": 1,
            "transportation": "步行",
            "accommodation": "豪华酒店",
            "preferences": ["购物", "艺术"],
            "free_text_input": "",
        },
        "expected": {
            "min_attractions": 2,        # 1天 × 2个景点
            "min_meals_per_day": 3,
            "keywords": ["南京路", "外滩", "陆家嘴", "新天地", "田子坊", "淮海路", "美术馆"],
            "preference_keywords": ["购物", "艺术", "商场", "美术馆", "博物馆", "画廊"],
            "max_budget": 10000,
            "min_budget": 200,
        },
    },
]
