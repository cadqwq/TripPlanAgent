"""
Agent 评估框架 — 自动评估旅行计划质量

用法:
    cd backend
    python tests/eval/eval_runner.py

评估维度:
    1. 结构完整性 (0-20%) — 必填字段是否齐全
    2. 景点覆盖率 (0-25%) — 每天至少2个景点
    3. 偏好匹配度 (0-25%) — 景点名称是否匹配用户偏好
    4. 地理合理性 (0-15%) — 经纬度是否在目标城市范围内
    5. 预算合理性 (0-15%) — 预算是否在合理范围内

输出:
    每个测试用例的评分明细 + 汇总统计表
"""

import sys
import os
import json
import time
from typing import Dict, List, Any

# 设置路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from app.models.schemas import TripRequest, TripPlan
from app.agents.trip_planner_agent import get_trip_planner_agent

# ============================================================
# 城市经纬度参考范围（用于地理合理性检查）
# ============================================================
CITY_BOUNDS = {
    "北京": {"lng": (115.4, 117.5), "lat": (39.4, 41.1)},
    "杭州": {"lng": (118.3, 120.8), "lat": (29.2, 30.6)},
    "成都": {"lng": (102.9, 104.9), "lat": (30.0, 31.5)},
    "上海": {"lng": (120.8, 122.0), "lat": (30.6, 31.9)},
}


# ============================================================
# 评分器
# ============================================================

class PlanScorer:
    """对生成的旅行计划逐维度打分"""

    def __init__(self, expected: dict, city: str):
        self.expected = expected
        self.city = city
        self.bounds = CITY_BOUNDS.get(city)

    def score(self, plan: TripPlan) -> dict:
        """综合评分，返回各维度得分和总分"""
        scores = {
            "结构完整性": self._score_structure(plan),
            "景点覆盖率": self._score_coverage(plan),
            "偏好匹配度": self._score_preference(plan),
            "地理合理性": self._score_geography(plan),
            "预算合理性": self._score_budget(plan),
        }

        weights = {
            "结构完整性": 0.20,
            "景点覆盖率": 0.25,
            "偏好匹配度": 0.25,
            "地理合理性": 0.15,
            "预算合理性": 0.15,
        }

        total = sum(scores[k] * weights[k] for k in scores)
        return {
            "scores": scores,
            "total": round(total, 2),
            "weights": weights,
        }

    def _score_structure(self, plan: TripPlan) -> float:
        """检查必填字段是否齐全"""
        score = 1.0
        deductions = []

        if not plan.city:
            deductions.append("缺少城市名")
            score -= 0.5
        if not plan.start_date or not plan.end_date:
            deductions.append("缺少日期")
            score -= 0.5
        if not plan.days:
            deductions.append("缺少每日行程")
            return 0.0

        for i, day in enumerate(plan.days):
            if not day.attractions:
                deductions.append(f"第{i+1}天无景点")
                score -= 0.3
            if len(day.meals) < 3:
                deductions.append(f"第{i+1}天不足三餐")

        return max(0.0, score)

    def _score_coverage(self, plan: TripPlan) -> float:
        """检查景点数量是否达标"""
        total_attractions = sum(len(d.attractions) for d in plan.days)
        expected_min = self.expected.get("min_attractions", len(plan.days) * 2)

        if total_attractions >= expected_min * 1.5:
            return 1.0
        elif total_attractions >= expected_min:
            return 0.8
        elif total_attractions >= expected_min * 0.5:
            return 0.5
        else:
            return 0.2

    def _score_preference(self, plan: TripPlan) -> float:
        """检查景点名称是否匹配用户偏好关键词"""
        keywords = self.expected.get("preference_keywords", [])
        if not keywords:
            return 0.8  # 没有偏好要求，给基础分

        all_attraction_names = []
        for day in plan.days:
            for attr in day.attractions:
                all_attraction_names.append(attr.name)
                all_attraction_names.append(attr.description or "")
                all_attraction_names.append(attr.category or "")

        full_text = " ".join(all_attraction_names)

        matches = sum(1 for kw in keywords if kw in full_text)
        match_rate = matches / len(keywords)

        if match_rate >= 0.6:
            return 1.0
        elif match_rate >= 0.3:
            return 0.7
        elif match_rate >= 0.1:
            return 0.4
        else:
            return 0.1

    def _score_geography(self, plan: TripPlan) -> float:
        """检查经纬度是否在目标城市范围内"""
        if not self.bounds:
            return 0.8  # 没有参考范围，给基础分

        total_attractions = 0
        in_bounds = 0

        for day in plan.days:
            for attr in day.attractions:
                total_attractions += 1
                loc = attr.location
                if loc and self.bounds["lng"][0] <= loc.longitude <= self.bounds["lng"][1] \
                        and self.bounds["lat"][0] <= loc.latitude <= self.bounds["lat"][1]:
                    in_bounds += 1

        if total_attractions == 0:
            return 0.5

        rate = in_bounds / total_attractions
        if rate >= 0.8:
            return 1.0
        elif rate >= 0.5:
            return 0.7
        else:
            return 0.3

    def _score_budget(self, plan: TripPlan) -> float:
        """检查预算是否合理"""
        budget = plan.budget
        if not budget:
            return 0.5

        total = budget.total
        expected_total = (
            budget.total_attractions
            + budget.total_hotels
            + budget.total_meals
            + budget.total_transportation
        )

        score = 1.0

        # 检查各项加总是否正确（允许 10 的误差）
        if abs(total - expected_total) > 10:
            score -= 0.3

        # 检查是否在合理范围内
        min_budget = self.expected.get("min_budget", 50)
        max_budget = self.expected.get("max_budget", 10000)

        if total < min_budget:
            score -= 0.3
        if total > max_budget:
            score = max(0.0, score - 0.2)

        return max(0.0, score)


# ============================================================
# 评估主流程
# ============================================================

HEADER = """
╔══════════════════════════════════════════════════════════════╗
║           TripPlanAgent — Agent 评估报告                    ║
╚══════════════════════════════════════════════════════════════╝"""


def run_evaluation(test_cases: List[dict], use_real_llm: bool = True):
    """
    运行评估。

    Args:
        test_cases: 测试用例列表
        use_real_llm: True=调用真实LLM, False=仅校验结构（用于快速回归）
    """
    print(HEADER)
    print(f"测试用例数: {len(test_cases)}")
    print(f"模式: {'真实LLM调用' if use_real_llm else '结构校验模式'}")
    print()

    if use_real_llm:
        print("初始化 Agent...")
        agent = get_trip_planner_agent()
        print()

    results = []
    total_time = 0

    for i, tc in enumerate(test_cases):
        name = tc["name"]
        req_data = tc["request"]
        expected = tc["expected"]

        print(f"[{i+1}/{len(test_cases)}] {name} ... ", end="", flush=True)

        try:
            request = TripRequest(**req_data)

            if use_real_llm:
                start = time.time()
                plan = agent.plan_trip(request, trace_id=f"eval_{i+1:02d}")
                elapsed = time.time() - start
                total_time += elapsed
            else:
                # 结构校验模式：不调LLM，直接校验JSON schema
                plan = None
                elapsed = 0

            if plan:
                scorer = PlanScorer(expected, req_data["city"])
                result = scorer.score(plan)
                result["case"] = name
                result["elapsed"] = elapsed
                result["attractions"] = sum(len(d.attractions) for d in plan.days)
                results.append(result)

                total = result["total"]
                status = "PASS" if total >= 0.7 else "FAIL"
                print(f"评分 {total:.0%} ({status}) | {elapsed:.0f}s | {result['attractions']}个景点")
            else:
                print("跳过（结构校验模式）")

        except Exception as e:
            print(f"❌ 失败: {e}")
            results.append({
                "case": name,
                "total": 0.0,
                "error": str(e),
                "scores": {},
                "elapsed": 0,
                "attractions": 0,
            })

    # ---- 汇总报告 ----
    print()
    print("=" * 70)
    print("评估汇总")
    print("=" * 70)

    passed = sum(1 for r in results if r.get("total", 0) >= 0.7)
    failed = len(results) - passed
    avg_score = sum(r.get("total", 0) for r in results) / max(len(results), 1)

    print(f"通过: {passed}/{len(results)} | 失败: {failed} | 平均分: {avg_score:.0%}")
    if total_time > 0:
        print(f"总耗时: {total_time:.0f}s | 平均: {total_time/len(results):.0f}s/用例")
    print()

    # 明细表
    print(f"{'用例':<20} {'结构':>5} {'覆盖':>5} {'偏好':>5} {'地理':>5} {'预算':>5} {'总分':>6}")
    print("-" * 56)
    for r in results:
        name = r.get("case", "?")
        s = r.get("scores", {})
        total = r.get("total", 0)
        print(f"{name:<20} {s.get('结构完整性',0):.0%}  {s.get('景点覆盖率',0):.0%}  "
              f"{s.get('偏好匹配度',0):.0%}  {s.get('地理合理性',0):.0%}  "
              f"{s.get('预算合理性',0):.0%}  {total:>5.0%}")

    print()
    print("评估完成。")

    return results


# ============================================================
# CLI 入口
# ============================================================

if __name__ == "__main__":
    from test_cases import TEST_CASES

    # 检查环境变量
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    amap_key = os.getenv("AMAP_API_KEY")

    use_real = bool(api_key and amap_key)

    if not use_real:
        print("⚠️  未检测到 API Key，使用结构校验模式")
        print("   如需真实评估，请先配置 backend/.env")
        print()

    run_evaluation(TEST_CASES, use_real_llm=use_real)
