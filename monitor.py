"""
DICIA 사업공고 모니터링 스크립트
대전정보문화산업진흥원(pms.dicia.or.kr) 사업공고를 모니터링하고
새 공고가 올라오면 Slack으로 알림을 보냅니다.
"""

import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
DICIA_URL = "https://pms.dicia.or.kr/mgmt/mjgg/mjggMgmtListR.do"
SEEN_FILE = "seen_announcements.json"

PRIORITY_KEYWORDS = [
    "웹툰", "IP", "콘텐츠", "캐릭터", "라이선싱", "팝업",
    "콘텐츠기업", "시장창출", "입주", "굿즈", "브릿지페어",
    "관광", "문화콘텐츠", "융복합", "특수영상"
]

EXCLUDE_KEYWORDS = ["비상임", "채용", "평가위원"]


def fetch_announcements():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        response = requests.get(DICIA_URL, headers=headers, timeout=30)
        response.raise_for_status()
        response.encoding = "utf-8"
    except requests.RequestException as e:
        print(f"페이지 요청 실패: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    announcements = []
    items = soup.select("ul > li > a")

    for item in items:
        text = item.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if len(lines) < 3:
            continue

        title_elem = item.select_one("strong")
        if not title_elem:
            continue

        title = title_elem.get_text(strip=True)
        team = ""
        for line in lines:
            if ">" in line and ("사업단" in line or "기획단" in line or "추진단" in line or "지원단" in line):
                team = line
                break

        info = {}
        for line in lines:
            if "공고일자" in line:
                info["date"] = line.replace("공고일자", "").strip()
            elif "접수기간" in line:
                info["period"] = line.replace("접수기간", "").strip()
            elif "지원대상" in line:
                info["target"] = line.replace("지원대상", "").strip()

        status = ""
        for line in lines:
            if line in ["접수중", "접수마감", "접수전"]:
                status = line
                break

        unique_id = f"{title}|{info.get('date', '')}"
        announcements.append({
            "id": unique_id, "title": title, "team": team,
            "date": info.get("date", ""), "period": info.get("period", ""),
            "target": info.get("target", ""), "status": status,
        })

    print(f"총 {len(announcements)}건 공고 확인")
    return announcements


def is_priority(title, team):
    combined = f"{title} {team}"
    for kw in EXCLUDE_KEYWORDS:
        if kw in combined and not any(pk in combined for pk in PRIORITY_KEYWORDS):
            return False
    for kw in PRIORITY_KEYWORDS:
        if kw in combined:
            return True
    return False


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_seen(seen_ids):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen_ids[-200:], f, ensure_ascii=False, indent=2)


def send_slack_notification(new_announcements):
    if not SLACK_WEBHOOK_URL:
        print("SLACK_WEBHOOK_URL이 설정되지 않았습니다.")
        for ann in new_announcements:
            priority = "⭐ " if ann["is_priority"] else ""
            print(f"  {priority}[{ann['status']}] {ann['title']}")
        return

    priority_anns = [a for a in new_announcements if a["is_priority"]]
    normal_anns = [a for a in new_announcements if not a["is_priority"]]

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"📢 DICIA 새 공고 {len(new_announcements)}건", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')} 확인 | <{DICIA_URL}|공고 페이지 바로가기>"}]},
        {"type": "divider"}
    ]

    if priority_anns:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "⭐ *어라운드 관련 공고*"}})
        for ann in priority_anns:
            status_emoji = {"접수중": "🟢", "접수전": "🟡", "접수마감": "🔴"}.get(ann["status"], "⚪")
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": (
                f"{status_emoji} *{ann['title']}*\n📂 {ann['team']}\n📅 공고일: {ann['date']}\n⏰ 접수: {ann['period']}\n👥 대상: {ann['target']}"
            )}})
            blocks.append({"type": "divider"})

    if normal_anns:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "📋 *기타 공고*"}})
        for ann in normal_anns:
            status_emoji = {"접수중": "🟢", "접수전": "🟡", "접수마감": "🔴"}.get(ann["status"], "⚪")
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"{status_emoji} *{ann['title']}*\n📅 {ann['date']} | 👥 {ann['target']}"}})

    payload = {
        "text": f"DICIA 새 공고 {len(new_announcements)}건 (관심 {len(priority_anns)}건)",
        "blocks": blocks
    }

    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code == 200:
            print(f"Slack 알림 전송 완료 ({len(new_announcements)}건)")
        else:
            print(f"Slack 전송 실패: {resp.status_code} {resp.text}")
    except requests.RequestException as e:
        print(f"Slack 전송 오류: {e}")


def main():
    print(f"\nDICIA 사업공고 모니터링 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    announcements = fetch_announcements()
    if not announcements:
        print("공고를 가져올 수 없습니다.")
        return

    seen_ids = load_seen()

    new_announcements = []
    for ann in announcements:
        if ann["id"] not in seen_ids:
            ann["is_priority"] = is_priority(ann["title"], ann["team"])
            new_announcements.append(ann)

    if new_announcements:
        priority_count = sum(1 for a in new_announcements if a["is_priority"])
        print(f"새 공고 {len(new_announcements)}건 발견! (관심 {priority_count}건)")
        send_slack_notification(new_announcements)
    else:
        print("새 공고 없음")

    current_ids = [ann["id"] for ann in announcements]
    all_seen = list(set(seen_ids + current_ids))
    save_seen(all_seen)


if __name__ == "__main__":
    main()
