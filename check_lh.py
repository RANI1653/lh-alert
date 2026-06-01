"""
LH 청약플러스 분양공고 알림 봇
- 공공데이터포털 API + LH 청약플러스 직접 크롤링 병행
- 새 공고 감지 시 Gmail 발송
"""

import os
import json
import hashlib
import smtplib
import requests
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup

# ── 환경변수 ──────────────────────────────────────────────
GMAIL_USER     = os.environ["GMAIL_USER"]       # 보내는 Gmail 주소
GMAIL_PASSWORD = os.environ["GMAIL_PASSWORD"]   # Gmail 앱 비밀번호
NOTIFY_EMAIL   = os.environ["NOTIFY_EMAIL"]     # 받을 이메일 주소 (같아도 OK)
DATA_GO_API_KEY = os.environ.get("DATA_GO_API_KEY", "")  # 공공데이터포털 API 키 (선택)

SEEN_FILE = "seen_notices.json"

# ── 공고 수집 ─────────────────────────────────────────────

def fetch_from_lh_site():
    """LH 청약플러스 공고 목록 페이지 직접 크롤링"""
    notices = []
    urls = [
        ("분양주택", "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancList.do?mi=1027"),
        ("임대주택", "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancList.do?mi=1026"),
        ("토지",     "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancList.do?mi=1062"),
    ]
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://apply.lh.or.kr/",
    }

    for category, url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.select("table tbody tr")
            for row in rows[:20]:
                cols = row.find_all("td")
                if len(cols) < 3:
                    continue
                title_tag = row.select_one("td a")
                if not title_tag:
                    continue
                title    = title_tag.get_text(strip=True)
                link_rel = title_tag.get("href", "")
                link     = ("https://apply.lh.or.kr" + link_rel) if link_rel.startswith("/") else link_rel
                date_str = cols[-1].get_text(strip=True) if cols else ""
                notices.append({
                    "id":       hashlib.md5(link.encode()).hexdigest(),
                    "title":    title,
                    "category": category,
                    "date":     date_str,
                    "link":     link,
                    "source":   "LH청약플러스",
                })
        except Exception as e:
            print(f"[WARN] {category} 크롤링 실패: {e}")

    return notices


def fetch_from_public_api():
    if not DATA_GO_API_KEY:
        return []
    notices = []
    url = "http://apis.data.go.kr/B552555/lhNoticeInfo1/getNoticeInfo1"
    params = {"serviceKey": DATA_GO_API_KEY, "numOfRows": 20, "pageNo": 1, "type": "json"}
    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        items = data.get("body", {}).get("items", {}).get("item", [])
        if isinstance(items, dict):
            items = [items]
        for item in items:
            title = item.get("ntcNm", "")
            date  = item.get("pblancDt", "")
            link  = "https://apply.lh.or.kr"
            notices.append({
                "id":       hashlib.md5((title + date).encode()).hexdigest(),
                "title":    title,
                "category": "공지사항",
                "date":     date,
                "link":     link,
                "source":   "공공데이터API",
            })
    except Exception as e:
        print(f"[WARN] 공공데이터 API 실패: {e}")
    return notices


def get_all_notices():
    notices = fetch_from_lh_site() + fetch_from_public_api()
    seen_ids = set()
    unique = []
    for n in notices:
        if n["id"] not in seen_ids:
            seen_ids.add(n["id"])
            unique.append(n)
    return unique

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen(seen: set):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f, ensure_ascii=False)

def build_html(new_notices: list) -> str:
    rows = ""
    for n in new_notices:
        rows += f"""
        <tr>
          <td style="padding:10px 12px;border-bottom:1px solid #eee;color:#555;font-size:13px;">{n['category']}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #eee;">
            <a href="{n['link']}" style="color:#1a73e8;text-decoration:none;font-weight:500;">{n['title']}</a>
          </td>
          <td style="padding:10px 12px;border-bottom:1px solid #eee;color:#888;font-size:13px;white-space:nowrap;">{n['date']}</td>
        </tr>"""

    count = len(new_notices)
    now   = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,sans-serif;">
  <div style="max-width:680px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden;">
    <div style="background:#1a4fd8;padding:28px 32px;">
      <p style="margin:0;color:rgba(255,255,255,.7);font-size:13px;">LH 청약플러스 알림</p>
      <h1 style="margin:6px 0 0;color:#fff;font-size:22px;font-weight:700;">🏠 새 분양공고 {count}건</h1>
    </div>
    <div style="padding:24px 32px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
        <thead>
          <tr style="background:#f8f9ff;">
            <th style="padding:10px 12px;text-align:left;font-size:12px;color:#888;border-bottom:2px solid #e8eaf6;">유형</th>
            <th style="padding:10px 12px;text-align:left;font-size:12px;color:#888;border-bottom:2px solid #e8eaf6;">공고명</th>
            <th style="padding:10px 12px;text-align:left;font-size:12px;color:#888;border-bottom:2px solid #e8eaf6;">등록일</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    <div style="padding:0 32px 28px;text-align:center;">
      <a href="https://apply.lh.or.kr" style="display:inline-block;padding:12px 32px;background:#1a4fd8;color:#fff;border-radius:8px;text-decoration:none;font-size:14px;">LH 청약플러스 바로가기 →</a>
    </div>
    <div style="padding:16px 32px;background:#f8f9ff;border-top:1px solid #eee;text-align:center;">
      <p style="margin:0;color:#aaa;font-size:12px;">이 메일은 자동 발송됩니다 · {now} 기준</p>
    </div>
  </div>
</body></html>"""


def send_email(new_notices: list):
    subject = f"[LH 청약플러스] 새 분양공고 {len(new_notices)}건 등록"
    html    = build_html(new_notices)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = NOTIFY_EMAIL
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.sendmail(GMAIL_USER, NOTIFY_EMAIL, msg.as_string())
    print(f"[OK] 이메일 발송 완료 → {NOTIFY_EMAIL} ({len(new_notices)}건)")


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] LH 공고 확인 시작")
    seen    = load_seen()
    notices = get_all_notices()
    new_notices = [n for n in notices if n["id"] not in seen]
    if new_notices:
        print(f"새 공고 {len(new_notices)}건 발견!")
        for n in new_notices:
            print(f"  - [{n['category']}] {n['title']} ({n['date']})")
        send_email(new_notices)
        seen.update(n["id"] for n in new_notices)
        save_seen(seen)
    else:
        print("새 공고 없음.")
    print("완료.")


if __name__ == "__main__":
    main()
