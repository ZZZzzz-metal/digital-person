#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确定性合成会话数据生成脚本（A 分工：数据整理 / A2）。

用途
    为中文情感陪伴对话模型生成 200 条**虚构**多轮会话训练样本。
    全部人名、事件均为虚构，仅使用固定人名池，不含真实可识别个人信息。

确定性
    固定随机种子（默认 20261012）+ 「片段池随机组合」。所有随机数来自
    random.Random(str) 派生的独立实例（Python 对 str 种子使用 sha512，不受
    PYTHONHASHSEED 影响），因此同一解释器下重复运行输出逐字节一致。

依赖
    仅标准库：argparse / hashlib / json / random / re / pathlib / sys。

用法（相对路径按仓库根目录解析）
    python data/training/make_synthetic_sessions.py
    python data/training/make_synthetic_sessions.py --out data/training/raw/sessions.jsonl

输出格式（每行一个 JSON object，UTF-8，ensure_ascii=False）
    {"session_id": "syn-<8位十六进制>-<4位序号>", "category": ..., "title": ...,
     "source": "synthetic_auto_generated",
     "license": "internal-fictional-no-real-personal-data",
     "messages": [{"role": "user"|"assistant", "content": "..."}, ...],
     "memory_context": [{"text": "...", "kind": "fact"|"event"|"preference"}, ...]}
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = "data/training/raw/sessions.jsonl"
DEFAULT_SEED = 20261012
TOTAL_SESSIONS = 200

SOURCE = "synthetic_auto_generated"
LICENSE = "internal-fictional-no-real-personal-data"

CATEGORIES = ["学习压力", "宿舍相处", "日常倾诉", "积极分享", "记忆引用与纠正", "话题切换"]
# 200 = 34+34+33+33+33+33，每类均 >= 25
CATEGORY_TARGETS = [
    ("学习压力", 34),
    ("宿舍相处", 34),
    ("日常倾诉", 33),
    ("积极分享", 33),
    ("记忆引用与纠正", 33),
    ("话题切换", 33),
]

NAMES = ["小然", "小林", "小舟", "小雨", "阿哲", "小满"]

MEMORY_KINDS = ("fact", "event", "preference")
CORRECTION_MARKERS = ("说错", "记错", "更正", "说反")
SWITCH_MARKERS = ("换个话题", "说点别的", "个别的事", "先放放", "算了不说", "先不提", "不说这个了")

USER_MIN, USER_MAX = 8, 60
ASSISTANT_MIN, ASSISTANT_MAX = 25, 110
MSG_MIN, MSG_MAX = 6, 14

FORBIDDEN_PHRASES = [
    "抑郁症", "确诊", "我是医生", "建议你服药", "一定能治好",
    "焦虑症", "双相", "精神分裂", "药物治疗", "处方",
]
FORBIDDEN_PATTERNS = [
    (re.compile(r"1[3-9]\d{9}"), "疑似真实手机号"),
    (re.compile(r"\d{15,18}"), "疑似身份证号"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "疑似邮箱"),
    (re.compile(r"\d+\s*[.、)]\s*\S"), "疑似编号清单"),
]

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
SESSION_ID_RE = re.compile(r"^syn-[0-9a-f]{8}-\d{4}$")


def cjk_len(text: str) -> int:
    return len(CJK_RE.findall(text))


# --------------------------------------------------------------------------- #
# 通用片段池
# --------------------------------------------------------------------------- #

PLACES = ["图书馆", "自习室", "教室", "宿舍", "食堂", "咖啡馆", "教学楼", "操场"]
TIMES = ["今天", "昨天", "这两天", "这几天", "上周末", "昨晚", "今天晚上"]
PERSONS = ["室友", "同班同学", "朋友", "学长", "学姐", "组里的同学"]

ACK_GENERAL = [
    "听起来这阵子确实挺累的",
    "嗯，我听到了",
    "这事儿搁谁身上都挺烦",
    "我大概明白你现在什么感觉",
    "难怪你会这么想",
    "这么一说，确实挺熬人的",
    "感觉你是被这件事卡住了",
    "你说的这些我都记下了",
    "能感觉出来你挺不容易的",
    "这事儿确实不轻松",
    "我陪你把这事儿捋一捋",
    "嗯，这种状态我懂",
    "你这么说，我一点都不意外",
    "听你讲完，我也跟着有点紧",
    "这确实是个会让人反复想的事",
    "先谢谢你愿意跟我说这些",
    "嗯，这份心情挺真实的",
    "你说的那个点我注意到了",
    "这样啊，那确实挺磨人的",
    "感觉你已经硬撑了一阵子",
    "嗯，我明白你在意的不是小事",
    "你这几句话信息量还挺大的",
    "好，那我们一点点看",
    "我听着呢，你慢慢说",
    "这事儿说起来简单，做起来真难",
    "嗯，换我可能也会烦",
    "看得出来你花了不少心思",
    "你现在的反应挺正常的",
    "明白了，怪不得你会这么讲",
    "嗯，这种来回拉扯最耗人",
    "你这么一讲，我更能理解你了",
    "嗯，先别急着给自己打分",
]

LINK_GENERAL = [
    "其实你已经做得挺多了",
    "不过也别把自己逼太紧",
    "这事急不来",
    "有时候状态就是会起伏",
    "你愿意说出来本身就挺好",
    "换个角度想，也不全是坏消息",
    "但眼下先照顾好身体更要紧",
    "我猜你心里其实有数",
    "这种时候更要给自己留点余地",
    "你不是一个人在扛这个",
    "先分清哪些是你真能控制的",
    "别急着给自己下结论",
    "慢慢来，节奏可以自己定",
    "有些事拖一拖也不会更糟",
    "你已经在往好的方向走了",
    "这事值得你认真，但不值得你熬坏自己",
    "哪怕今天只做了一点点也算进度",
    "心里堵着的时候别硬扛",
    "累了就歇会儿，这没什么",
    "你不欠任何人一个完美结果",
]

SOFT_GENERAL = [
    "要是想说，我就在这儿听着",
    "先喝口水，缓一缓",
    "要不要跟我说说最卡的那一步",
    "今天先歇一会儿也行",
    "需要我陪你顺一遍吗",
    "想聊到哪就聊到哪，不用勉强",
    "什么时候想说，我都在",
    "先别急着解决，放一放也没事",
    "要不要先去走走，回来再说",
    "你可以先挑一件最轻的做",
    "要不今晚早点睡，明天再想",
    "想吐槽两句也可以，我听着",
    "要不要我帮你记着这件事",
    "这事我们慢慢来，不赶时间",
    "你要是愿意，可以再讲细一点",
    "先照顾一下自己的情绪吧",
    "要不要找个人一起吃个饭",
    "需要我陪你把话说完吗",
    "先按你舒服的节奏来",
    "累了就先停一下，真的没关系",
    "你想安静一会儿也行，我不催你",
    "要不要把明天要做的事写下来",
    "想说什么就说什么，别有负担",
    "你决定就好，我都支持",
    "先给自己留一口气",
    "要不要先做点别的换换脑子",
    "这种事，说出来会轻一点",
    "你要是不想聊这个，我们换个话题",
    "先别管结果，做一点是一点",
    "我陪你想，不着急",
]

TAIL_GENERAL = [
    "你现在最担心的是哪一步？",
    "这两天睡得还好吗？",
    "这事儿是从什么时候开始的？",
    "你打算怎么安排接下来几天？",
    "有没有谁能帮你分担一点？",
    "你自己心里更倾向哪种？",
    "最让你难受的是哪一句？",
    "那你现在最想做什么？",
    "需要我做点什么吗？",
    "要不要先说说今天的进展？",
    "这事儿跟你之前想的一样吗？",
    "你现在是想解决，还是想先说说？",
]

EXTENSIONS = [
    "你不必一个人扛着",
    "先照顾好自己",
    "我陪着你慢慢来",
    "这会儿先松口气也行",
    "别的先放一放",
    "慢慢来就好",
    "我在这儿呢",
    "不用急着回答我",
    "不用马上想明白",
    "我陪着你",
    "先把这口气缓过来",
    "有我在呢",
    "不着急，慢慢说",
    "你先按自己的来",
    "这一步不用走太快",
    "什么时候说都行",
]

# 用户消息的补充小句（跟在主干后面，用于扩大表达变化）
TAGS_NEUTRAL = [
    "我也不知道该怎么说",
    "反正就是这样",
    "跟你说说能轻松点",
    "这两天都这样",
    "我也不太清楚怎么回事",
    "你别嫌我啰嗦",
    "我是不是想太多了",
    "想起来就有点堵",
    "我心里有点没底",
    "也不知道接下来怎么办",
    "就想找个人说说",
    "反正挺折腾的",
    "我自己也说不上来",
    "大概就是这么个情况",
    "最近事情确实有点多",
    "我这两天一直在想这个",
    "有时候挺矛盾的",
    "跟你说完我再琢磨琢磨",
    "先跟你说说",
    "我自己也没想清楚",
    "感觉一直在原地打转",
    "反正心里不太舒服",
    "就这样吧",
    "我也不知道该不该说",
]
TAGS_POSITIVE = [
    "现在想起来还想笑",
    "我都没想到会成",
    "今天真是难得",
    "我跟你说完更开心了",
    "我准备了好久的",
    "我到现在还有点飘",
    "就想找人分享一下",
    "这算不算运气好",
    "我要把这个记下来",
    "他们也都替我高兴",
    "我今晚要好好庆祝一下",
    "感觉最近顺起来了",
    "希望以后也这样",
    "我当时都愣住了",
    "反正今天特别爽",
    "我一会儿还要跟家里说",
    "这种时候真难得",
    "我得趁热打铁",
    "我都有点舍不得结束这一天",
    "你说我是不是有点傻",
]
TAGS_EXTRA = {
    "学习压力": ["越到后面越慌", "就怕时间不够用", "跟同学比更没底"],
    "宿舍相处": ["说重了怕伤感情", "我现在回宿舍都有点别扭", "其他人都跟没事一样"],
    "日常倾诉": ["晚上特别容易胡思乱想", "白天还好，晚上就不行", "就感觉心里空落落的"],
    "积极分享": ["我到现在手还有点抖", "这事儿我惦记挺久了", "今天运气真不错"],
    "记忆引用与纠正": ["我这两天一直在折腾这个", "心里有点乱", "先这样吧"],
    "话题切换": ["反正最近都这样", "说起来还挺有意思的", "我也不知道为什么"],
}
TAGS_FOR = {
    name: (TAGS_POSITIVE if name == "积极分享" else TAGS_NEUTRAL) + TAGS_EXTRA[name]
    for name in CATEGORIES
}

# 按语气分组的助手片段池：problem=在诉苦，joy=报喜，warm=轻松聊爱好
ACK_JOY = [
    "看你这语气，我都替你高兴",
    "这事儿听着就让人开心",
    "这确实是个好消息",
    "能感觉出你现在心情特别好",
    "这么顺的事，值得高兴一下",
    "听你这么说，我也跟着乐了",
    "你这运气可以啊",
    "这消息挺提气的",
    "感觉你今天是真开心",
    "这事儿办得漂亮",
    "难为你还想着来跟我说",
    "听起来今天过得很不错",
    "你说的这个我听着都来劲",
    "这种时候就得好好高兴一下",
    "看得出来你挺得意的",
    "嗯，你这高兴劲儿都传过来了",
    "这事儿值得你乐一乐",
    "难怪你忍不住想说",
    "听着就很爽",
    "这算得上今天的高光了吧",
]
LINK_JOY = [
    "这份高兴多留一会儿",
    "该高兴就高兴，别不好意思",
    "你之前确实花了不少功夫",
    "这种好运气值得记下来",
    "别急着收心，先享受一下",
    "你也该有这么一天",
    "这事儿够你回味好几天",
    "可以给自己一点奖励",
    "趁着这股劲，好好放松一下",
    "这么一来，前面那些辛苦也值了",
    "开心的事说出来会加倍",
    "你这状态一看就不一样",
    "这种时候不用想太多",
    "把今天记牢一点",
]
SOFT_JOY = [
    "要不要买点好吃的庆祝一下",
    "记得拍张照留着",
    "今晚可以早点收工，好好歇着",
    "想跟谁说就赶紧去说",
    "要不要发个朋友圈",
    "这种时候别自己憋着乐",
    "回头跟我讲讲细节",
    "给自己放个小假吧",
    "想吃点什么就去吃",
    "把这份好心情存起来",
    "要不要出去走走，趁天还没黑",
    "今晚可以睡个好觉了",
    "想怎么庆祝都行",
    "把这次的经历记两句",
    "有机会再跟我说说后续",
    "好好享受一下今天",
]
TAIL_JOY = [
    "你当时什么反应？",
    "这事儿是怎么成的？",
    "准备怎么庆祝？",
    "你准备了多久？",
    "还有谁知道了？",
    "接下来还有什么安排？",
    "你现在最想做什么？",
    "要不要说说细节？",
]
ACK_WARM = [
    "听起来你挺喜欢这个的",
    "这事儿听着就有意思",
    "嗯，能感觉出你挺投入",
    "说到这个你语气都亮了",
    "这个爱好挺好的",
    "你还挺会找乐子的",
    "听你说这个我也觉得轻松一点",
    "换个话题确实好一些",
    "这样聊着舒服多了",
    "嗯，这个方向听着就自在",
    "你讲这个的时候明显轻快",
    "有意思，你可以多说说",
    "这算是你的小爱好吧",
    "难得听你聊点轻松的",
    "嗯，这个比刚才那事好聊",
    "看你愿意聊这个，挺好",
    "这事儿听着不累人",
    "你这兴致一上来就不一样了",
]
LINK_WARM = [
    "有点自己的爱好挺好的",
    "这种时候就该聊点开心的",
    "别老想着那些烦人的事",
    "有件事能让自己放松就不错",
    "这样的时间多一点好",
    "看得出来你是真喜欢",
    "偶尔换个话题也挺解压",
    "这算是给自己充电了",
    "这种小事最能让人缓过来",
    "你能找到喜欢的事挺好",
]
SOFT_WARM = [
    "想聊多久都行",
    "你想细说我就听着",
    "要不要下次带我了解一下",
    "多聊聊这个挺好的",
    "想怎么聊都行",
    "这个可以慢慢说",
    "愿意的话多讲两句",
    "有兴致就多说点",
    "聊这个比刚才轻松",
    "你继续，我听着",
    "这个话题听着就舒服",
]
TAIL_WARM = [
    "这个是怎么开始的？",
    "你什么时候开始弄这个的？",
    "还有别的爱好吗？",
    "最近还玩点什么？",
    "这事儿有什么好玩的？",
    "你一般什么时候弄这个？",
]
TONE_POOLS = {
    "problem": (ACK_GENERAL, LINK_GENERAL, SOFT_GENERAL, TAIL_GENERAL),
    "joy": (ACK_JOY, LINK_JOY, SOFT_JOY, TAIL_JOY),
    "warm": (ACK_WARM, LINK_WARM, SOFT_WARM, TAIL_WARM),
}
# 分类附加片段只在对应语气下启用
BLUEPRINT_EXTRAS_TONE = {
    "学习压力": "problem",
    "宿舍相处": "problem",
    "日常倾诉": "problem",
    "记忆引用与纠正": "problem",
    "积极分享": "joy",
    "话题切换": "warm",
}

# --------------------------------------------------------------------------- #
# 分类蓝图
# --------------------------------------------------------------------------- #

BLUEPRINTS: dict[str, dict] = {}

BLUEPRINTS["学习压力"] = {
    "topics": [
        ("线性代数考试", "线代复习"),
        ("高数期中", "高数期中"),
        ("英语四级", "四级备考"),
        ("六级听力", "六级听力"),
        ("概率论小测", "概率论小测"),
        ("数据结构上机作业", "数据结构上机"),
        ("操作系统实验报告", "操作系统实验"),
        ("数据库课程设计", "课程设计"),
        ("课程论文查重", "论文查重"),
        ("考研数学", "考研复习"),
        ("保研材料", "保研材料"),
        ("实习笔试", "实习笔试"),
        ("建模竞赛论文", "建模竞赛"),
        ("小组pre", "小组展示"),
        ("专业课答辩", "答辩准备"),
        ("教资笔试", "教资备考"),
        ("计算机二级", "计算机二级"),
        ("期末复习计划", "期末复习"),
        ("奖学金申请材料", "奖学金材料"),
        ("英语作文批改", "英语作文"),
    ],
    "open": [
        "最近一直在弄{t}，感觉快扛不住了",
        "为了{t}这几天我基本没睡好",
        "我跟你说，一想到{t}我就有点慌",
        "这周全耗在{t}上了，还是没什么进展",
        "因为{t}，我这两天心情特别差",
        "{t}这事儿我完全没头绪",
        "我最近在弄{t}，越弄越觉得自己不行",
        "今天为了{t}跟同学争论了半天，也没结论",
    ],
    "develop": [
        "今天在{pl}待了一下午，该看的还是没看完",
        "一想到{t}我就心慌，晚上翻来覆去睡不着",
        "老师讲得挺快，我一节课下来全是问号",
        "明明前一天看懂了，第二天又忘了",
        "我做了两套题，错的地方都差不多",
        "别人都准备完一轮了，我才刚开始",
        "我妈打电话问我准备得怎么样，我没敢细说",
        "有时候真想摆烂，可又不甘心就这么放着",
        "我列了个计划，结果一栏都没动",
        "为了抢{pl}的位置，我六点多就起来了",
        "看着进度我就开始怀疑自己是不是不适合这个专业",
        "一打开资料就走神，手机一刷就一个小时",
        "关于{t}，我连从哪儿下手都不知道",
    ],
    "close": [
        "算了，我先去{pl}再看两眼",
        "谢谢你听我说这些，我去缓一缓",
        "我先去吃饭，晚点还得弄{t}",
        "说出来好像轻了一点，我去洗漱了",
        "我去把{t}的资料再翻翻，先这样",
        "今天就到这儿吧，我早点睡",
    ],
    "memory": [
        ("{n}在读大二", "fact"),
        ("{n}这学期课不算轻松", "fact"),
        ("{n}最近在为{t}发愁", "event"),
        ("{n}这周一直在准备{t}", "event"),
        ("{n}习惯把计划写在便签上", "preference"),
    ],
    "ack_extra": [
        "{t}这种事确实是慢功夫",
        "听你这么说，{t}真把你磨得够呛",
        "弄{t}本来就容易反复",
        "嗯，{t}最考人心态",
    ],
    "soft_extra": [
        "要不要把{t}拆成几小块来做",
        "先挑{t}里最简单的一块试试",
        "要不要找同学对一下笔记",
        "今天先离开{pl}换个地方待会儿",
    ],
    "tail_extra": [
        "你打算从哪一块开始？",
        "这事儿是什么时候来着？",
        "你们班进度都这样吗？",
        "要不要先睡一觉明天再弄{t}？",
    ],
}

BLUEPRINTS["宿舍相处"] = {
    "topics": [
        ("半夜开麦打游戏", "宿舍作息"),
        ("空调温度", "空调温度"),
        ("卫生轮值", "卫生轮值"),
        ("借了东西不还", "借东西"),
        ("电费怎么分摊", "电费分摊"),
        ("室友的朋友常来", "外人串门"),
        ("作息差太多", "作息差异"),
        ("柜子和桌子被占", "地方被占"),
        ("洗澡排队", "洗澡排队"),
        ("带饭的小事", "带饭小事"),
        ("室友养的猫", "宿舍养猫"),
        ("说话太直", "说话方式"),
        ("点外卖的分歧", "点外卖"),
        ("群里没人回消息", "宿舍群"),
        ("公共卫生没人管", "公共卫生"),
        ("晚归关门声大", "晚归动静"),
        ("门卡丢了", "门卡丢了"),
        ("老借充电器", "借充电器"),
    ],
    "open": [
        "我们宿舍最近因为{t}有点别扭",
        "我被{t}搞得挺烦，又不好直接说",
        "跟你说个事，{t}这事我和室友看法完全不一样",
        "昨天因为{t}，气氛一下子就冷了",
        "我这两天一直在忍，{t}这事让我挺难受的",
        "{t}这事，我不知道该不该开口",
        "因为{t}，我现在回宿舍都有点不想说话",
        "{t}让我挺矛盾的，怕说了伤感情",
    ],
    "develop": [
        "我提过一次，对方当时答应了，第二天还是老样子",
        "我不想显得自己事多，就一直没再提",
        "其他室友好像都不在意，就我一个人别扭",
        "我怕说重了以后几年都不好相处",
        "晚上躺床上就忍不住想这件事",
        "我试着用开玩笑的方式说，结果对方没接住",
        "其实也不是大事，可攒多了就压得慌",
        "我甚至想过换宿舍，又觉得太夸张",
        "我妈让我多担待，可我心里还是不舒服",
        "有时候我也怀疑是不是自己太计较了",
        "今天又碰上一次，我当场就没忍住板着脸",
        "在群里说这事更尴尬，我就没在群里发",
        "我现在回宿舍前都要先做下心理准备",
    ],
    "close": [
        "算了，我先回宿舍了，谢谢你听我说",
        "我去买点吃的，回头再想办法",
        "先这样吧，我晚上还得面对他们",
        "说出来舒服多了，我去洗个澡",
        "我先去上课，这事我再想想",
        "谢谢你，我回去试着好好说一次",
    ],
    "memory": [
        ("{n}住在学校宿舍", "fact"),
        ("{n}这学期和三个室友一起住", "fact"),
        ("{n}最近因为{t}和室友有点不愉快", "event"),
        ("{n}昨天又碰上{t}的事", "event"),
        ("{n}不太喜欢跟人起冲突", "preference"),
        ("{n}喜欢有话直说", "preference"),
    ],
    "ack_extra": [
        "宿舍里{t}这种事最磨人",
        "住一起难免有{t}这类摩擦",
        "天天要面对的{t}，确实不好受",
        "嗯，{t}听着不大，天天碰上就难受",
    ],
    "soft_extra": [
        "要不要先想清楚你最在意哪一点",
        "可以挑只有你们俩的时候说",
        "先别憋着，也别急着摊牌",
        "要不要我陪你把话捋一遍",
    ],
    "tail_extra": [
        "你们之前聊过这事吗？",
        "对方平时好沟通吗？",
        "你最希望变成什么样？",
        "要不要先从小事试一次？",
    ],
}

BLUEPRINTS["日常倾诉"] = {
    "topics": [
        ("想家", "想家的晚上"),
        ("一直感冒", "感冒难受"),
        ("总睡不好", "睡不好"),
        ("外卖连着踩雷", "外卖踩雷"),
        ("快递丢了", "快递丢了"),
        ("手机屏幕摔了", "手机摔了"),
        ("早八上得很难受", "早八"),
        ("洗衣排队排了半小时", "排队洗衣"),
        ("每天挤公交", "通勤"),
        ("头发剪坏了", "剪坏的头发"),
        ("食堂新窗口不太好吃", "食堂新窗口"),
        ("社团开会开到十点", "社团开会"),
        ("跟家里通完电话有点难受", "家里电话"),
        ("总觉得累", "莫名的累"),
        ("一个人过了个周末", "一个人的周末"),
        ("天天下雨", "下雨天"),
        ("图书馆冷气太足", "冷气"),
        ("钱花超了", "花超了"),
    ],
    "open": [
        "今天不知道怎么了，就是有点提不起劲",
        "想跟你说说话，也不是什么大事",
        "最近{t}，我整个人都有点蔫",
        "我在食堂坐着，突然就觉得有点空",
        "这两天{t}，干什么都没心情",
        "跟你说个小事，我最近{t}，有点烦",
        "晚上一个人待着的时候，情绪就有点低",
        "我也说不上来，就是{t}让我心里堵得慌",
    ],
    "develop": [
        "也没什么具体的原因，就是提不起精神",
        "白天还能撑，到了晚上就有点绷不住",
        "我不想跟家里说，怕他们担心",
        "朋友都在忙，我也不好意思打扰",
        "有时候吃个饭都觉得费劲",
        "刷手机刷到半夜，也不知道在看什么",
        "我试着出去走了走，好像也没用",
        "这种状态断断续续好几天了",
        "我不想让别人觉得我矫情",
        "今天上课走神了一整节",
        "我给自己买了杯奶茶，好一点点",
        "其实说出来好一些，就是不知道跟谁说",
    ],
    "close": [
        "我跟你说说就好多了，去睡了",
        "谢谢你，我去洗个脸",
        "先这样吧，我去吃点东西",
        "有人听着真好，我先去忙了",
        "我去楼下走两圈，回来说不定就好",
        "谢谢你陪我聊这几句",
    ],
    "memory": [
        ("{n}一个人在外地上学", "fact"),
        ("{n}家离学校挺远", "fact"),
        ("{n}最近{t}", "event"),
        ("{n}昨天情绪有点低", "event"),
        ("{n}不太喜欢麻烦别人", "preference"),
        ("{n}睡前爱听一会儿歌", "preference"),
    ],
    "ack_extra": [
        "嗯，这种没来由的低落最磨人",
        "听你这么说，我大概能懂那种空",
        "没事，说不清楚也可以说",
        "你愿意讲出来已经挺好了",
    ],
    "soft_extra": [
        "要不要先做点不用动脑的事",
        "今晚别太苛责自己",
        "想安静就安静一会儿",
        "要不要听点熟悉的歌",
    ],
    "tail_extra": [
        "你最近胃口怎么样？",
        "这种状态持续几天了？",
        "有没有哪件事能让你松一点？",
        "今晚打算几点睡？",
    ],
}

BLUEPRINTS["积极分享"] = {
    "topics": [
        ("抢到了演唱会门票", "抢到票"),
        ("跑完了五公里", "跑步打卡"),
        ("比赛拿了二等奖", "比赛获奖"),
        ("拿到了实习offer", "实习offer"),
        ("科目二过了", "考过科目二"),
        ("论文被老师夸了", "被老师夸"),
        ("小猫学会了握手", "猫的进步"),
        ("室友带了家乡特产", "特产"),
        ("攒钱买了把吉他", "买了吉他"),
        ("和喜欢的人一起吃了饭", "一起吃饭"),
        ("帮同学调通了代码", "帮上忙"),
        ("第一次自己做了饭", "第一次做饭"),
        ("宿舍一起看了电影", "宿舍电影夜"),
        ("口语课被点名表扬", "口语课"),
        ("健身坚持了一个月", "健身一个月"),
        ("朋友寄来了明信片", "明信片"),
        ("评上了奖学金", "奖学金"),
        ("加入了喜欢的社团", "入社团"),
    ],
    "open": [
        "跟你说个好消息，{t}",
        "我今天特别开心，{t}",
        "忍不住想跟你分享，{t}",
        "今天超顺，{t}",
        "我有个小成就想炫耀一下，{t}",
        "刚发生一件事，{t}，我现在还在傻乐",
        "今天真是难得的好日子，{t}",
        "想找个人说说，{t}",
    ],
    "develop": [
        "我其实没抱太大希望，结果真成了",
        "当时手都在抖，现在想起来还想笑",
        "我第一时间就想跟人说，就想到你了",
        "这个我准备了挺久的，总算没白费",
        "室友也跟着起哄，闹了半天",
        "我给自己加了个鸡腿，算是奖励",
        "晚上我打算出去走走，趁高兴劲儿",
        "有点不敢相信，还反复确认了两遍",
        "我妈知道了肯定要乐半天",
        "以前总觉得这事跟我没关系，没想到真轮到我",
        "我拍了张照片，存在相册里舍不得删",
        "希望这种运气能多来几次",
    ],
    "close": [
        "我先去跟他们吃饭庆祝了",
        "谢谢你听我嘚瑟，我去忙啦",
        "太开心了，我先去发个朋友圈",
        "好了，我去回味一下",
        "谢谢你陪我高兴一会儿",
        "我先把这事记下来，回头再聊",
    ],
    "memory": [
        ("{n}平时喜欢记点小事", "fact"),
        ("{n}这学期给自己定了几个小目标", "fact"),
        ("{n}最近{t}", "event"),
        ("{n}今天遇到一件开心事", "event"),
        ("{n}喜欢跟朋友分享好消息", "preference"),
        ("{n}习惯睡前写两句话", "preference"),
    ],
    "ack_extra": [
        "你这语气听着就让人高兴",
        "这事值得高兴一下",
        "能听出来你是真开心",
        "这消息挺提气的",
    ],
    "soft_extra": [
        "记得给自己留个纪念",
        "今天可以稍微放松一点",
        "要不要跟家里人也说说",
        "把这份高兴多留一会儿",
    ],
    "tail_extra": [
        "你当时什么反应？",
        "准备怎么庆祝一下？",
        "这事你准备了多久？",
        "要不要拍张照纪念一下？",
    ],
}

# 记忆引用与纠正： (旧值, 新值, 场景)
CORRECTION_PAIRS = [
    ("教师资格证", "计算机二级", "考证科目"),
    ("汉语言文学", "新闻传播", "专业方向"),
    ("图书馆四楼", "教学楼自习室", "复习地点"),
    ("下周三", "下周五", "考试时间"),
    ("摄影社", "话剧社", "社团"),
    ("拿铁", "美式", "饮品偏好"),
    ("小林", "小舟", "室友名字"),
    ("六点半", "七点半", "起床时间"),
    ("开卷", "闭卷", "考试形式"),
    ("两门课", "三门课", "选课数量"),
    ("本校", "外校", "目标院校"),
    ("考研", "考公", "毕业打算"),
    ("猫", "狗", "想养的宠物"),
    ("家教兼职", "便利店兼职", "兼职类型"),
    ("北方的城市", "南方的城市", "家乡方向"),
]

CORR_OPEN = [
    "我上次跟你说的是{old}，你还记得吧",
    "先跟你说一下，我之前提的是{old}",
    "我上次跟你提的{old}，这两天一直搁在心里",
    "还记得我跟你说过的{old}吗，最近有点变化",
    "关于{old}的事，我一直没细说",
]
CORR_DEVELOP = [
    "这件事我这两天一直在想",
    "我也不太确定自己弄得对不对",
    "白天忙起来还好，晚上就开始琢磨",
    "跟别人说我都有点不好意思",
    "我列了个计划，执行起来又是另一回事",
    "最近心里一直悬着这件事",
]
CORR_FIX = [
    "对了，之前说错了，不是{old}，是{new}",
    "我记错了，不是{old}，其实是{new}",
    "更正一下，我上次说反了，是{new}，不是{old}",
    "哎我上次说错了，跟{old}没关系，是{new}",
    "等等，我说错了，是{new}，{old}是我记岔的",
]
CORR_DEVELOP_NEW = [
    "既然改成{t}了，我这边也得跟着调整",
    "那就说{t}吧，其他的先放一放",
    "既然是{t}，那我之前安排的都得改",
    "{t}这事我先记着，回头再细说",
    "好，就按{t}来，我心里也清楚一点了",
]
CORR_CLOSE = [
    "谢谢你，我再去想想{t}的事",
    "先聊到这儿，{t}那边我还得处理",
    "说出来好多了，我去把{t}的事理一理",
    "我去问问{t}的事，回头再跟你说",
]
CORR_ACK_PRE = [
    "我记得你说的是{old}吧",
    "你之前提的{old}，现在怎么样了",
    "{old}这事儿确实费神",
]
CORR_ADOPT = [
    "那我以后就按{new}来记",
    "我更新成{new}了",
    "记下了，是{new}",
    "好，那这事就当是{new}",
]

BLUEPRINTS["记忆引用与纠正"] = {
    "ack_extra": CORR_ACK_PRE,
    "soft_extra": [
        "要不要把新的安排说给我听听",
        "换方向也不丢人",
        "慢慢重新理一遍也行",
    ],
    "tail_extra": [
        "那你现在打算从哪儿开始？",
        "时间还够用吗？",
    ],
}

# 话题切换
SWITCH_TOPICS_A = [
    ("课程作业", "课程作业"),
    ("实验报告", "实验报告"),
    ("小组合作", "小组合作"),
    ("早起上课", "早八"),
    ("社团的事情", "社团"),
    ("找实习", "找实习"),
    ("宿舍杂事", "宿舍杂事"),
    ("期末周", "期末周"),
]
SWITCH_TOPICS_B = [
    ("养花", "养花"),
    ("拼图", "拼图"),
    ("看展", "看展"),
    ("听播客", "听播客"),
    ("骑自行车", "骑车"),
    ("学做饭", "学做饭"),
    ("打羽毛球", "打羽毛球"),
    ("拍照", "拍照"),
    ("看剧", "看剧"),
    ("桌游", "桌游"),
    ("写手账", "手账"),
    ("撸猫", "撸猫"),
]
SWITCH_OPEN_A = [
    "我这两天一直在忙{a}，有点烦",
    "跟你说说{a}的事，我心里不太舒服",
    "最近{a}让我挺烦的",
    "我被{a}卡了好几天了",
    "一提到{a}我就有点上火",
    "{d}又为了{a}耗了一下午，还是没弄完",
    "为了{a}，我连{pl}都没怎么去",
    "{a}这事我谁都没说，先跟你说",
]
SWITCH_DEVELOP_A = [
    "一直拖着也不是办法，可我就是不想动",
    "我也知道急没用，但心里还是堵",
    "每天忙完就只想躺着",
    "这事儿说起来也不算大，就是烦",
    "{d}跟{p}聊了两句，越聊越没劲",
    "我本来想在{pl}安静弄一会儿，结果一直在刷手机",
    "我连{pl}都不想去了，只想躲着",
    "就这么拖着，我心里也不踏实",
]
SWITCH_LINE = [
    "对了，不说{a}了，我想说点别的",
    "哎，换个话题吧，说点轻松的",
    "先不提{a}了，我跟你说个别的事",
    "算了不说{a}了，我突然想聊{b}",
    "这个先放放，我换个事跟你说",
]
SWITCH_DEVELOP_B = [
    "其实我最近在琢磨{t}，挺有意思的",
    "就想跟你聊聊{t}，别的先不想",
    "说到{t}我就来劲，跟你说说",
    "我最近在{t}这事上花了不少时间，还挺开心",
    "换个话题聊聊{t}，我心情好多了",
    "最近迷上{t}了，你要不要听听",
]
SWITCH_CLOSE_B = [
    "谢谢你听我说这些，我先去忙了",
    "好，那我先去{t}，回头聊",
    "说出来轻松多了，我先去歇会儿",
    "谢谢你陪我聊{t}，我先去忙了",
    "那就先这样，我去弄点别的",
]

BLUEPRINTS["话题切换"] = {
    "memory": [
        ("{n}这学期事情挺多", "fact"),
        ("{n}最近被{t}占了不少时间", "event"),
        ("{n}喜欢找人说说话", "preference"),
        ("{n}平时爱好挺杂的", "fact"),
    ],
    "ack_extra": [
        "换个话题也好，聊聊轻松的",
        "行，那就听你说说{t}",
        "嗯，那就先把这个放一放",
        "好，那我们说点别的",
    ],
    "soft_extra": [
        "换个话题说不定能松一点",
        "想说哪个都行",
        "不用勉强聊刚才那件事",
        "想怎么聊都行",
    ],
    "tail_extra": [
        "这个是怎么开始的？",
        "你怎么想到要玩这个的？",
        "还有别的想聊的吗？",
        "最近还有什么新鲜事？",
    ],
}

# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #


def fmt(template: str, ctx: dict) -> str:
    return template.format(**ctx)


def take(rng: random.Random, pool: list, used: set) -> str:
    """从池中确定性取一个没在本会话用过的片段（用尽则重开）。"""
    avail = [item for item in pool if item not in used]
    if not avail:
        used.clear()
        avail = list(pool)
    choice = rng.choice(avail)
    used.add(choice)
    return choice


def choose_clause(rng: random.Random, pool: list, used: set, used_prefixes: set, prefix_len: int = 4) -> str:
    """优先挑前缀没在本会话出现过的小句，避免每轮同一句开场。"""
    avail = [item for item in pool if item not in used]
    if not avail:
        avail = list(pool)
    fresh = [item for item in avail if item[:prefix_len] not in used_prefixes]
    picked = rng.choice(fresh if fresh else avail)
    used.add(picked)
    used_prefixes.add(picked[:prefix_len])
    return picked


def _grams(text: str, n: int = 3) -> set:
    return {text[i:i + n] for i in range(max(len(text) - n + 1, 0))}


def choose_part(
    rng: random.Random,
    pool: list,
    used: set,
    parts: list,
    used_prefixes: set | None = None,
    prefix_len: int = 4,
) -> str:
    """挑一个小句：本会话未用过、且与已选小句没有三字重复（避免同义堆叠）。"""
    avail = [item for item in pool if item not in used] or list(pool)
    if used_prefixes is not None:
        fresh = [item for item in avail if item[:prefix_len] not in used_prefixes]
        avail = fresh or avail
    used_grams: set = set()
    for part in parts:
        used_grams |= _grams(part)
    distinct = [item for item in avail if not (_grams(item) & used_grams)]
    picked = rng.choice(distinct or avail)
    used.add(picked)
    if used_prefixes is not None:
        used_prefixes.add(picked[:prefix_len])
    return picked


def message_ctx(rng: random.Random, ctx: dict) -> dict:
    out = dict(ctx)
    out["pl"] = rng.choice(PLACES)
    out["d"] = rng.choice(TIMES)
    out["p"] = rng.choice(PERSONS)
    return out


def user_line(
    rng: random.Random,
    category: str,
    template: str,
    ctx: dict,
    state: dict,
    use_tag: bool = True,
) -> str:
    """按模板生成一条 user 消息，并可按概率追加补充小句以扩大表达变化。"""
    text = fmt(template, message_ctx(rng, ctx))
    if use_tag and rng.random() < 0.85:
        tag = take(rng, TAGS_FOR[category], state["used"]["tag"])
        text = text.rstrip("。！？") + "，" + tag
    return text


def join_parts(parts: list, question: bool) -> str:
    cleaned = [part.strip().rstrip("。！？?!，,") for part in parts if part.strip()]
    return "，".join(cleaned) + ("？" if question else "。")


def make_assistant(
    rng: random.Random,
    category: str,
    ctx: dict,
    state: dict,
    tone: str = "problem",
    adoption: str | None = None,
    closing: bool = False,
) -> str:
    bp = BLUEPRINTS[category]
    used = state["used"]
    ack_base, link_base, soft_base, tail_base = TONE_POOLS[tone]
    if BLUEPRINT_EXTRAS_TONE.get(category) == tone and not closing:
        ack_extra = bp.get("ack_extra", [])
        soft_extra = bp.get("soft_extra", [])
        tail_extra = bp.get("tail_extra", [])
    else:
        ack_extra, soft_extra, tail_extra = [], [], []
    if adoption is not None:
        # 纠正轮不再复述旧值，只承接并采用新值，保持训练目标清晰
        ack_extra = []
    ack_pool = [fmt(t, ctx) for t in ack_base + ack_extra]
    soft_pool = [fmt(t, ctx) for t in soft_base + soft_extra]
    link_pool = [fmt(t, ctx) for t in link_base]
    tail_pool = [fmt(t, ctx) for t in tail_base + tail_extra]
    ext_pool = [fmt(t, ctx) for t in EXTENSIONS]

    parts: list[str] = []
    is_question = False

    parts.append(choose_part(rng, ack_pool, used["ack"], parts, state["assistant_prefixes"]))

    if adoption is not None:
        parts.append(fmt(adoption, ctx))
        third = choose_part(rng, tail_pool, used["tail"], parts)
        parts.append(third)
        is_question = third.rstrip().endswith("？")
    else:
        structure = rng.choice(
            ["link_soft", "link_soft", "link_tail", "soft_tail", "soft", "soft_tail"])
        if structure == "soft":
            parts.append(choose_part(rng, soft_pool, used["soft"], parts))
        elif structure == "link_soft":
            parts.append(choose_part(rng, link_pool, used["link"], parts))
            parts.append(choose_part(rng, soft_pool, used["soft"], parts))
        elif structure == "soft_tail":
            parts.append(choose_part(rng, soft_pool, used["soft"], parts))
            tail = choose_part(rng, tail_pool, used["tail"], parts)
            parts.append(tail)
            is_question = tail.rstrip().endswith("？")
        elif structure == "link_tail":
            parts.append(choose_part(rng, link_pool, used["link"], parts))
            tail = choose_part(rng, tail_pool, used["tail"], parts)
            parts.append(tail)
            is_question = tail.rstrip().endswith("？")

    text = join_parts(parts, is_question)
    if cjk_len(text) < 25:
        # 需要补足长度时，把补充小句插在最后的问句之前，避免问句后面再跟陈述
        question_part = parts.pop() if is_question else None
        while len(parts) + (1 if question_part else 0) < 5 and cjk_len(join_parts(parts, False)) < 25:
            parts.append(choose_part(rng, ext_pool, used["ext"], parts))
        if question_part is not None:
            parts.append(question_part)
        text = join_parts(parts, is_question)
    return text


def build_memory(rng: random.Random, category: str, ctx: dict, stale_old: str | None) -> list[dict]:
    if category == "记忆引用与纠正":
        count = rng.choice([1, 2, 2, 3])
        items = [(f"{ctx['n']}上次说的是{stale_old}", "fact")]
        extra = [
            (f"{ctx['n']}前几天提到过{stale_old}", "event"),
            (f"{ctx['n']}习惯把计划写在便签上", "preference"),
            (f"{ctx['n']}不太喜欢麻烦别人", "preference"),
        ]
        rng.shuffle(extra)
        items.extend(extra[: count - 1])
    else:
        count = rng.choice([0, 1, 1, 2, 2, 3])
        pool = [(fmt(t, ctx), kind) for t, kind in BLUEPRINTS[category]["memory"]]
        rng.shuffle(pool)
        items = pool[:count]
    return [{"text": text, "kind": kind} for text, kind in items]


# --------------------------------------------------------------------------- #
# 会话构建
# --------------------------------------------------------------------------- #


def build_user_turns(
    rng: random.Random,
    category: str,
    ctx: dict,
    state: dict,
    turn_count: int,
) -> tuple[list[str], dict]:
    """返回 (user 文本列表, 结构标记)。文本均已完成 {slot} 替换。"""
    bp = BLUEPRINTS.get(category, {})
    used = state["used"]
    marks: dict = {}
    texts: list[str] = []

    if category == "记忆引用与纠正":
        old, new = ctx["old"], ctx["new"]
        pre_develops = 1 if turn_count <= 5 else 2
        texts.append(user_line(rng, category, take(rng, CORR_OPEN, used["open"]), ctx, state))
        for _ in range(pre_develops):
            texts.append(user_line(rng, category, take(rng, CORR_DEVELOP, used["develop"]), ctx, state))
        marks["correction_index"] = len(texts)
        texts.append(user_line(rng, category, take(rng, CORR_FIX, used["fix"]), ctx, state,
                               use_tag=False))
        post_develops = turn_count - pre_develops - 3
        ctx_after = dict(ctx)
        ctx_after["t"] = new
        for _ in range(post_develops):
            texts.append(user_line(rng, category, take(rng, CORR_DEVELOP_NEW, used["develop_new"]),
                                   ctx_after, state))
        texts.append(user_line(rng, category, take(rng, CORR_CLOSE, used["close"]), ctx_after, state))
        marks["old"], marks["new"] = old, new
        return texts, marks

    if category == "话题切换":
        topic_b = ctx["b"]
        texts.append(user_line(rng, category, take(rng, SWITCH_OPEN_A, used["open_a"]), ctx, state))
        texts.append(user_line(rng, category, take(rng, SWITCH_DEVELOP_A, used["develop_a"]),
                               ctx, state))
        marks["switch_index"] = len(texts)
        texts.append(user_line(rng, category, take(rng, SWITCH_LINE, used["switch"]), ctx, state))
        ctx_after = dict(ctx)
        ctx_after["t"] = topic_b
        post_develops = turn_count - 4
        for _ in range(post_develops):
            texts.append(user_line(rng, category, take(rng, SWITCH_DEVELOP_B, used["develop_b"]),
                                   ctx_after, state))
        texts.append(user_line(rng, category, take(rng, SWITCH_CLOSE_B, used["close_b"]),
                               ctx_after, state))
        marks["topic_b"] = topic_b
        return texts, marks

    texts.append(user_line(rng, category, take(rng, bp["open"], used["open"]), ctx, state,
                           use_tag=False))
    for _ in range(turn_count - 2):
        texts.append(user_line(rng, category, take(rng, bp["develop"], used["develop"]), ctx, state))
    texts.append(user_line(rng, category, take(rng, bp["close"], used["close"]), ctx, state))
    return texts, marks


def build_session(index: int, category: str, rng: random.Random) -> dict:
    state = {
        "used": {key: set() for key in
                 ("open", "develop", "close", "ack", "soft", "link", "tail", "ext", "tag",
                  "open_a", "develop_a", "switch", "develop_b", "close_b",
                  "fix", "develop_new")},
        "assistant_prefixes": set(),
    }
    name = rng.choice(NAMES)

    if category == "记忆引用与纠正":
        old, new, scene = rng.choice(CORRECTION_PAIRS)
        topic = old
        turn_count = rng.choice([4, 4, 5, 5, 5, 6, 7])
        title = f"{name}-{scene}更正"
        ctx = {"n": name, "t": old, "a": "", "b": "", "old": old, "new": new,
               "pl": "", "d": "", "p": ""}
    elif category == "话题切换":
        topic_a, scene_a = rng.choice(SWITCH_TOPICS_A)
        topic_b, scene_b = rng.choice(SWITCH_TOPICS_B)
        topic = topic_a
        turn_count = rng.choice([5, 5, 6, 6, 7])
        title = f"{name}-{scene_a}到{scene_b}"
        ctx = {"n": name, "t": topic_a, "a": topic_a, "b": topic_b, "old": topic_a,
               "new": "", "pl": "", "d": "", "p": ""}
    else:
        topic, scene = rng.choice(BLUEPRINTS[category]["topics"])
        turn_count = rng.choice([3, 3, 4, 4, 4, 5, 5, 5, 6, 7])
        title = f"{name}-{scene}"
        ctx = {"n": name, "t": topic, "a": topic, "b": "", "old": topic, "new": "",
               "pl": "", "d": "", "p": ""}

    user_texts, marks = build_user_turns(rng, category, ctx, state, turn_count)

    messages: list[dict] = []
    for pos, user_text in enumerate(user_texts):
        messages.append({"role": "user", "content": user_text})
        turn_ctx = dict(ctx)
        if category == "记忆引用与纠正" and pos > marks["correction_index"]:
            turn_ctx["t"] = marks["new"]
        if category == "话题切换" and pos >= marks["switch_index"]:
            turn_ctx["t"] = marks["topic_b"]
        adoption = None
        tone = "problem"
        if category == "积极分享":
            tone = "joy"
        elif category == "话题切换":
            tone = "problem" if pos <= marks["switch_index"] else "warm"
        if category == "记忆引用与纠正" and pos == marks["correction_index"]:
            adoption = rng.choice(CORR_ADOPT)
            turn_ctx["t"] = marks["new"]
        messages.append({"role": "assistant",
                         "content": make_assistant(rng, category, turn_ctx, state, tone, adoption,
                                                   closing=(pos == len(user_texts) - 1))})

    if category == "记忆引用与纠正":
        memory_context = build_memory(rng, category, ctx, marks["old"])
    else:
        memory_context = build_memory(rng, category, ctx, None)

    digest = hashlib.sha256(
        f"{DEFAULT_SEED}|{index}|{category}|{name}|{topic}|{turn_count}|{title}".encode("utf-8")
    ).hexdigest()[:8]

    return {
        "session_id": f"syn-{digest}-{index + 1:04d}",
        "category": category,
        "title": title,
        "source": SOURCE,
        "license": LICENSE,
        "messages": messages,
        "memory_context": memory_context,
    }


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #


def lengths_ok(session: dict) -> bool:
    """候选会话的长度与角色是否合规（不合规就换一次尝试，而不是直接失败）。"""
    messages = session["messages"]
    if not (MSG_MIN <= len(messages) <= MSG_MAX) or len(messages) % 2:
        return False
    for pos, message in enumerate(messages):
        text = message["content"]
        n = cjk_len(text)
        lo, hi = (USER_MIN, USER_MAX) if pos % 2 == 0 else (ASSISTANT_MIN, ASSISTANT_MAX)
        if not (lo <= n <= hi and lo <= len(text) <= hi):
            return False
    return True


def check_session(session: dict, index: int, seen_ids: set, seen_content: set) -> dict:
    where = f"第 {index + 1} 行"

    if list(session.keys()) != ["session_id", "category", "title", "source", "license",
                                "messages", "memory_context"]:
        raise AssertionError(f"{where}: 字段集合或顺序不符合约定: {list(session.keys())}")

    sid = session["session_id"]
    if not isinstance(sid, str) or not SESSION_ID_RE.match(sid):
        raise AssertionError(f"{where}: session_id 格式非法: {sid!r}")
    if sid in seen_ids:
        raise AssertionError(f"{where}: session_id 重复: {sid}")
    seen_ids.add(sid)

    category = session["category"]
    if category not in CATEGORIES:
        raise AssertionError(f"{where}: category 非法: {category!r}")

    if session["source"] != SOURCE or session["license"] != LICENSE:
        raise AssertionError(f"{where}: source/license 非法")

    if not isinstance(session["title"], str) or not session["title"].strip():
        raise AssertionError(f"{where}: title 为空非法")

    messages = session["messages"]
    if not isinstance(messages, list) or not (MSG_MIN <= len(messages) <= MSG_MAX):
        raise AssertionError(f"{where}: messages 条数非法: {len(messages)}")
    if len(messages) % 2 != 0:
        raise AssertionError(f"{where}: messages 条数应为偶数（user/assistant 成对）")

    local_content: list[str] = []
    for pos, message in enumerate(messages):
        if list(message.keys()) != ["role", "content"]:
            raise AssertionError(f"{where}: message 字段非法: {list(message.keys())}")
        expect_role = "user" if pos % 2 == 0 else "assistant"
        if message["role"] != expect_role:
            raise AssertionError(f"{where}: 第 {pos + 1} 条角色应为 {expect_role}，实为 {message['role']}")
        text = message["content"]
        if not isinstance(text, str) or not text.strip():
            raise AssertionError(f"{where}: 第 {pos + 1} 条 content 为空")
        clen = cjk_len(text)
        if expect_role == "user":
            if not (USER_MIN <= clen <= USER_MAX and USER_MIN <= len(text) <= USER_MAX):
                raise AssertionError(f"{where}: user 长度越界 cjk={clen} total={len(text)}: {text}")
        else:
            if not (ASSISTANT_MIN <= clen <= ASSISTANT_MAX
                    and ASSISTANT_MIN <= len(text) <= ASSISTANT_MAX):
                raise AssertionError(f"{where}: assistant 长度越界 cjk={clen} total={len(text)}: {text}")
        for phrase in FORBIDDEN_PHRASES:
            if phrase in text:
                raise AssertionError(f"{where}: 出现禁止表述 {phrase!r}: {text}")
        for pattern, label in FORBIDDEN_PATTERNS:
            if pattern.search(text):
                raise AssertionError(f"{where}: {label}: {text}")
        if text in local_content:
            raise AssertionError(f"{where}: 会话内 content 重复: {text}")
        local_content.append(text)

    if messages[0]["role"] != "user" or messages[-1]["role"] != "assistant":
        raise AssertionError(f"{where}: messages 必须以 user 开始、以 assistant 结束")

    assistant_prefixes = [m["content"][:4] for m in messages if m["role"] == "assistant"]
    if len(set(assistant_prefixes)) != len(assistant_prefixes):
        raise AssertionError(f"{where}: 同一会话内 assistant 开场重复: {assistant_prefixes}")

    # 助手回复不得出现编号清单
    for message in messages:
        if message["role"] == "assistant" and re.search(r"(^|[，。；\s])[0-9１-９]+[.、)]", message["content"]):
            raise AssertionError(f"{where}: assistant 出现编号清单: {message['content']}")

    memory_context = session["memory_context"]
    if not isinstance(memory_context, list) or not (0 <= len(memory_context) <= 3):
        raise AssertionError(f"{where}: memory_context 元素个数非法: {len(memory_context)}")
    for item in memory_context:
        if list(item.keys()) != ["text", "kind"]:
            raise AssertionError(f"{where}: memory_context 字段非法: {list(item.keys())}")
        if item["kind"] not in MEMORY_KINDS:
            raise AssertionError(f"{where}: memory kind 非法: {item['kind']!r}")
        if not isinstance(item["text"], str) or not item["text"].strip():
            raise AssertionError(f"{where}: memory text 为空")

    if category == "记忆引用与纠正":
        if not memory_context:
            raise AssertionError(f"{where}: 记忆引用与纠正类必须带 memory_context")
        old, new = None, None
        fix_index = None
        for pos, message in enumerate(messages):
            if message["role"] == "user" and any(k in message["content"] for k in CORRECTION_MARKERS):
                fix_index = pos
                break
        if fix_index is None or fix_index == 0:
            raise AssertionError(f"{where}: 未找到有效纠正轮次")
        fix_text = messages[fix_index]["content"]
        memory_text = "".join(item["text"] for item in memory_context)
        earlier = "".join(m["content"] for m in messages[:fix_index] if m["role"] == "user")
        candidates = [pair for pair in CORRECTION_PAIRS
                      if pair[1] in fix_text and pair[0] in earlier]
        if not candidates:
            raise AssertionError(f"{where}: 纠正轮缺少「先旧值后新值」结构: {fix_text}")
        old, new = candidates[0][0], candidates[0][1]
        if new not in messages[fix_index + 1]["content"]:
            raise AssertionError(f"{where}: 助手未采用新值 {new}: {messages[fix_index + 1]['content']}")
        if old not in memory_text and old not in earlier:
            raise AssertionError(f"{where}: 旧值未在记忆或前文出现")

    if category == "话题切换":
        switch_index = None
        for pos, message in enumerate(messages):
            if message["role"] == "user" and any(k in message["content"] for k in SWITCH_MARKERS):
                switch_index = pos
                break
        if switch_index is None or switch_index < 1 or switch_index >= len(messages) - 1:
            raise AssertionError(f"{where}: 未找到有效话题切换轮次")
        after = "".join(m["content"] for m in messages[switch_index + 1:] if m["role"] == "user")
        if not any(topic in after for topic, _ in SWITCH_TOPICS_B):
            raise AssertionError(f"{where}: 切换后未出现新话题: {after}")

    for text in local_content:
        if text in seen_content:
            raise AssertionError(f"{where}: content 与其他会话重复: {text}")
        seen_content.add(text)

    return {"category": category, "messages": messages, "memory_context": memory_context}


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #


def category_plan(rng: random.Random) -> list[str]:
    plan: list[str] = []
    remaining = {name: count for name, count in CATEGORY_TARGETS}
    order = [name for name, _ in CATEGORY_TARGETS]
    rng.shuffle(order)
    while len(plan) < TOTAL_SESSIONS:
        for name in order:
            if remaining[name] > 0:
                plan.append(name)
                remaining[name] -= 1
    return plan


def generate(seed: int) -> list[dict]:
    plan_rng = random.Random(f"{seed}|plan|{TOTAL_SESSIONS}")
    plan = category_plan(plan_rng)

    sessions: list[dict] = []
    seen_ids: set = set()
    seen_content: set = set()

    for index, category in enumerate(plan):
        session = None
        for attempt in range(500):
            rng = random.Random(f"{seed}|{category}|{index}|{attempt}")
            candidate = build_session(index, category, rng)
            contents = [m["content"] for m in candidate["messages"]]
            if len(set(contents)) != len(contents):
                continue
            if any(text in seen_content for text in contents):
                continue
            prefixes = [m["content"][:4] for m in candidate["messages"] if m["role"] == "assistant"]
            if len(set(prefixes)) != len(prefixes):
                continue
            if not lengths_ok(candidate):
                continue
            session = candidate
            break
        if session is None:
            raise RuntimeError(f"第 {index + 1} 行（{category}）在 500 次尝试内无法生成唯一内容")

        check_session(session, index, seen_ids, seen_content)
        sessions.append(session)
    return sessions


def write_sessions(sessions: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(s, ensure_ascii=False, separators=(",", ":")) for s in sessions]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def report(sessions: list[dict]) -> None:
    counts: dict[str, int] = {name: 0 for name in CATEGORIES}
    contents: list[str] = []
    user_lens: list[int] = []
    asst_lens: list[int] = []
    user_total = assistant_total = 0

    for session in sessions:
        counts[session["category"]] += 1
        for message in session["messages"]:
            contents.append(message["content"])
            length = cjk_len(message["content"])
            if message["role"] == "user":
                user_total += 1
                user_lens.append(length)
            else:
                assistant_total += 1
                asst_lens.append(length)

    duplicates = len(contents) - len(set(contents))
    all_lens = user_lens + asst_lens

    print(f"总行数: {len(sessions)}")
    print("每类别行数:")
    for name in CATEGORIES:
        print(f"  {name}: {counts[name]}")
    print(f"user 轮次总数: {user_total}")
    print(f"assistant 轮次总数: {assistant_total}")
    print(f"消息长度 min/max（汉字）: {min(all_lens)}/{max(all_lens)}")
    print(f"  user 长度 min/max（汉字）: {min(user_lens)}/{max(user_lens)}")
    print(f"  assistant 长度 min/max（汉字）: {min(asst_lens)}/{max(asst_lens)}")
    print(f"重复 content 条数: {duplicates}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="生成确定性的合成情感陪伴多轮会话数据（仅标准库）。")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help=f"输出路径，相对路径按仓库根目录解析（默认 {DEFAULT_OUT}）")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help=f"随机种子（默认 {DEFAULT_SEED}，改动会改变生成内容）")
    args = parser.parse_args(argv)

    out_arg = Path(args.out)
    out_path = out_arg if out_arg.is_absolute() else (REPO_ROOT / out_arg)

    sessions = generate(args.seed)
    write_sessions(sessions, out_path)

    print(f"输出文件: {out_path}")
    report(sessions)
    print("自检: 通过（格式、角色交替、唯一 session_id、类别、长度范围、去重）")
    return 0


if __name__ == "__main__":
    sys.exit(main())