"""情绪与画像的规则判断（A 分工）。

这里是**规则**，不是训练出来的识别能力，报告里必须这样写。

两套标签是分开的，不能互相推导：

- 内部演示 6 类：``neutral/happy/sad/anxious/angry/unknown``，用于 ``CoreReply.emotion``；
- 官方 16 类：``joy/gratitude/...``，用于 ``OfficialPrediction.emotion_label``。

总约定的情绪→表情映射也只作用于演示路径：
``happy → smile``；``sad/anxious → concern``；``angry → listening``；
``neutral/unknown → neutral``。非法情绪归 ``unknown``、表情归 ``neutral``。
"""
from __future__ import annotations

from typing import Any, Iterable

from . import official_spec

DEMO_EMOTIONS: tuple[str, ...] = ("neutral", "happy", "sad", "anxious", "angry", "unknown")

EMOTION_TO_EXPRESSION: dict[str, str] = {
    "happy": "smile",
    "sad": "concern",
    "anxious": "concern",
    "angry": "listening",
    "neutral": "neutral",
    "unknown": "neutral",
}

# 顺序有意义：先匹配到的先返回，所以把更具体的情绪放在前面。
# 没有任何关键词命中时视为 neutral（用户只是平铺直叙），
# 只有空输入才归 unknown。
_DEMO_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("anxious", ("紧张", "焦虑", "担心", "害怕", "慌", "睡不着", "失眠", "压力", "忐忑", "不安", "怕", "慌得")),
    ("angry", ("生气", "气死", "烦死", "讨厌", "火大", "凭什么", "太过分", "恼火")),
    ("sad", ("难过", "伤心", "失落", "委屈", "想哭", "低落", "沮丧", "没意思", "郁闷")),
    ("happy", ("开心", "高兴", "太好了", "顺利", "成功", "赢了", "进步", "爽", "满意", "轻松")),
)

_OFFICIAL_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("gratitude", ("谢谢", "感谢", "多谢", "谢谢你", "帮了我", "感激")),
    ("pride", ("自豪", "骄傲", "我做到了", "拿了第一", "获奖", "得奖", "冠军")),
    ("joy", ("开心", "高兴", "太好了", "兴奋", "爽", "愉快", "笑得")),
    ("relaxed", ("放松", "轻松", "踏实", "松了口气", "舒服", "安心")),
    ("loneliness", ("孤独", "没人", "一个人", "没人懂", "孤单", "被孤立", "没人理")),
    ("anxiety", ("紧张", "焦虑", "担心", "害怕", "忐忑", "不安", "睡不着", "心慌", "悬着")),
    ("fear", ("恐惧", "很怕", "怕得要死", "惊恐", "不敢想", "毛骨悚然")),
    ("helplessness", ("没办法", "无能为力", "不知道怎么办", "没辙", "救不了", "只能这样")),
    ("shame", ("丢人", "羞愧", "不好意思", "自卑", "没脸", "后悔死了")),
    ("disgust", ("恶心", "厌恶", "反胃", "受不了他", "讨厌死")),
    ("anger", ("生气", "气死", "火大", "恼火", "凭什么", "太过分", "愤怒")),
    ("sadness", ("难过", "伤心", "失落", "委屈", "想哭", "低落", "沮丧", "郁闷")),
    ("care", ("关心", "在意", "照顾", "陪着我", "会不会", "还好吗")),
    ("surprise", ("没想到", "居然", "竟然", "意外", "吓一跳", "突然")),
    ("mixed", ("又开心又", "既高兴又", "矛盾", "说不清", "复杂")),
)

_INTEREST_RULES: dict[str, tuple[str, ...]] = {
    "study_exam": ("考试", "考研", "期末", "复习", "绩点", "作业", "论文", "四六级", "高数", "线代", "上课", "保研"),
    "programming_technology": ("代码", "编程", "程序", "算法", "报错", "debug", "项目", "服务器", "数据库"),
    "reading_writing": ("看书", "读书", "小说", "写东西", "写作", "散文"),
    "film_animation": ("电影", "追剧", "番", "动漫", "剧", "纪录片"),
    "music": ("音乐", "歌", "耳机", "演唱会", "吉他", "钢琴"),
    "games": ("游戏", "开黑", "打排位", "手游", "steam"),
    "sports_fitness": ("跑步", "健身", "打球", "篮球", "羽毛球", "游泳", "锻炼"),
    "travel_outdoor": ("旅游", "出去玩", "爬山", "露营", "骑行", "晚霞", "拍照"),
    "pets": ("猫", "狗", "宠物", "养了只"),
    "social": ("室友", "朋友", "聚会", "社团", "舍友", "同学"),
    "career_development": ("实习", "面试", "简历", "找工作", "秋招", "offer", "职业"),
    "art_design": ("画画", "设计", "摄影", "手绘", "手工"),
}

_STYLE_RULES: dict[str, tuple[str, ...]] = {
    "brief": ("简短点", "简短", "说短点", "别太长", "长话短说"),
    "detailed": ("详细", "多说点", "展开说"),
    "colloquial": ("咋", "啥", "挺", "呗", "嘛", "啊这"),
    "formal": ("您好", "请问", "麻烦您"),
    "direct": ("直接说", "别绕", "直说"),
    "indirect": ("可能", "好像", "也许", "大概"),
    "humorous": ("哈哈", "笑死", "梗", "开玩笑"),
    "rational": ("分析", "逻辑", "原因", "理性"),
    "high_emotional_expression": ("！！！", "好烦啊", "太难受了", "崩了"),
    "low_emotional_expression": ("还行", "就那样", "无所谓"),
    "emoji_user": ("😊", "😂", "🥲", "😭", "🙂"),
}

_TRAIT_RULES: dict[str, tuple[str, ...]] = {
    "extroverted": ("和朋友", "大家", "聚会", "热闹"),
    "introverted": ("一个人待着", "不想社交", "独处", "安静"),
    "open": ("想试试", "新鲜", "好奇", "没试过"),
    "conservative": ("稳妥", "不想变", "按老办法"),
    "high_conscientiousness": ("计划", "安排", "提前准备", "打卡", "坚持每天"),
    "casual": ("随便", "都行", "无所谓", "拖延"),
    "agreeable": ("不好意思拒绝", "怕麻烦别人", "配合"),
    "assertive": ("我就要", "我决定", "必须", "不同意"),
    "emotionally_stable": ("还好", "能接受", "没那么严重"),
    "sensitive": ("很在意", "放不下", "想很多", "敏感", "一直在想"),
}


def _match(text: str, rules: Iterable[tuple[str, tuple[str, ...]]]) -> str | None:
    for label, keywords in rules:
        for keyword in keywords:
            if keyword in text:
                return label
    return None


def estimate_demo_emotion(text: str) -> str:
    """演示路径的 6 类情绪估计。

    空输入归 ``unknown``；非空但没有情绪关键词时归 ``neutral``（平铺直叙）。
    这是规则判断，不是训练出来的识别能力。
    """
    if not isinstance(text, str) or not text.strip():
        return "unknown"
    return _match(text, _DEMO_RULES) or "neutral"


def estimate_official_emotion(text: str, fallback: str = "neutral") -> str:
    """官方路径的 16 类情绪估计；无法判断时返回 neutral（合法枚举）。"""
    if not isinstance(text, str) or not text.strip():
        return fallback
    label = _match(text, _OFFICIAL_RULES)
    if label is None or label not in official_spec.EMOTION_SET:
        return fallback
    return label


def map_expression(emotion: str) -> str:
    """总约定的情绪→表情映射；非法情绪一律 neutral。"""
    return EMOTION_TO_EXPRESSION.get(emotion, "neutral")


def _collect(text: str, rules: dict[str, tuple[str, ...]], limit: int) -> list[str]:
    hits: list[str] = []
    for label, keywords in rules.items():
        if any(keyword in text for keyword in keywords):
            hits.append(label)
    return hits[:limit]


def infer_profile(history: Iterable[Any], *, limit: int = 3) -> dict[str, list[str]]:
    """从历史文本里按关键词推断画像；没有证据的组返回空数组。

    只输出官方 schema 允许的枚举值，绝不编造。这是规则推断，
    不是训练出来的画像识别能力。
    """
    parts: list[str] = []
    for turn in history:
        content = turn.get("content") if isinstance(turn, dict) else getattr(turn, "content", None)
        if isinstance(content, str):
            parts.append(content)
    text = "\n".join(parts)

    profile = {
        "personality_traits": _collect(text, _TRAIT_RULES, limit),
        "interests": _collect(text, _INTEREST_RULES, limit),
        "style": _collect(text, _STYLE_RULES, limit),
    }
    # 兜底保证三组都在，且都是合法枚举、无重复
    clean: dict[str, list[str]] = {}
    for group in official_spec.PROFILE_GROUP_NAMES:
        allowed = official_spec.PROFILE_SETS[group]
        seen: list[str] = []
        for value in profile.get(group, []):
            if value in allowed and value not in seen:
                seen.append(value)
        clean[group] = seen
    return clean