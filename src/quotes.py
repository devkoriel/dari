from __future__ import annotations

import random

QUOTES: list[tuple[str, str]] = [
    ("사랑해 💕", "我愛你 💕"),
    ("보고싶어", "想你了"),
    ("오늘도 행복하자 ☀️", "今天也要開心哦 ☀️"),
    ("넌 내 최고의 선물이야 🎁", "你是我最好的禮物 🎁"),
    ("같이 있으면 행복해", "跟你在一起很幸福"),
    ("매일 더 좋아져 🌙", "每天都更喜歡你 🌙"),
    ("너만 있으면 돼", "有你就夠了"),
    ("우리 오래오래 함께하자 🤞", "我們要一直在一起哦 🤞"),
    ("니가 웃으면 나도 웃게 돼 😊", "你笑的時候我也會跟著笑 😊"),
    ("오늘 하루도 고생했어 ❤️", "今天也辛苦了 ❤️"),
    ("세상에서 제일 좋아해", "全世界最喜歡你"),
    ("좋은 꿈 꿔 🌙", "做個好夢 🌙"),
    ("항상 네 편이야", "我永遠站你這邊"),
    ("너 때문에 웃어 😄", "因為你我才笑 😄"),
    ("빨리 만나고 싶다", "好想快點見到你"),
    ("넌 나의 행복이야 ✨", "你就是我的幸福 ✨"),
    ("맛있는 거 먹자 🍜", "我們去吃好吃的吧 🍜"),
    ("힘내! 나 여기 있어 💪", "加油！我在這裡 💪"),
    ("너무 귀여워 🐰", "太可愛了 🐰"),
    ("우리 다음에 어디 갈까? ✈️", "我們下次去哪裡？✈️"),
]


VOCABULARY: list[tuple[str, str, str]] = [
    # (Korean, Chinese, English hint)
    ("설레다", "心動", "heart fluttering"),
    ("그리워하다", "思念", "to miss someone"),
    ("응원하다", "加油/應援", "to cheer on"),
    ("기대하다", "期待", "to look forward to"),
    ("감동", "感動", "being moved/touched"),
    ("눈치", "察言觀色", "social awareness"),
    ("정", "情", "deep affection/bond"),
    ("효도", "孝道", "filial piety"),
    ("소확행", "小確幸", "small but certain happiness"),
    ("맞바람", "接機", "going to meet at arrival"),
    ("다정하다", "溫柔體貼", "warm and caring"),
    ("든든하다", "可靠/安心", "feeling secure/reliable"),
    ("아끼다", "珍惜", "to cherish"),
    ("보람", "成就感", "sense of reward"),
    ("달달하다", "甜蜜", "sweet (relationship)"),
    ("짝꿍", "搭檔/夥伴", "partner/buddy"),
    ("꿀잠", "好覺", "sweet sleep"),
    ("힐링", "療癒", "healing"),
    ("멍때리다", "放空", "to zone out"),
    ("치맥", "炸雞配啤酒", "chicken and beer"),
]


def random_quote() -> str:
    ko, zh = random.choice(QUOTES)
    return f"💌\n🇰🇷 {ko}\n🇹🇼 {zh}"


def random_vocabulary() -> str:
    ko, zh, en = random.choice(VOCABULARY)
    return f"📚 Word of the Day\n🇰🇷 {ko}\n🇹🇼 {zh}\n💡 {en}"
