"""
매일 GitHub Actions에서 실행됩니다.
1. 저장된 refresh_token으로 카카오 access_token을 새로 발급받습니다.
2. 카카오가 refresh_token을 새로 내려주면, GitHub 저장소 Secret(KAKAO_REFRESH_TOKEN)을 자동으로 갱신합니다.
3. notify-data.json을 읽어 숙소 무료취소 마감일 / 체크리스트 완료 권장일까지 D-day를 계산합니다.
4. notify_thresholds_days 에 해당하는 항목이 있으면 카카오톡 '나에게 보내기'로 메시지를 보냅니다.
"""

import base64
import json
import os
import sys
from datetime import date, timedelta

import requests

KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
SITE_URL = "https://geonul22.github.io/osaka-trip-2026/"


def refresh_kakao_token():
    rest_api_key = os.environ["KAKAO_REST_API_KEY"]
    refresh_token = os.environ["KAKAO_REFRESH_TOKEN"]

    resp = requests.post(
        KAKAO_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": rest_api_key,
            "refresh_token": refresh_token,
        },
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()
    return payload["access_token"], payload.get("refresh_token")


def rotate_github_secret(new_refresh_token):
    """카카오가 새 refresh_token을 내려준 경우, repo secret을 업데이트해서 다음 실행에도 쓸 수 있게 합니다."""
    gh_pat = os.environ.get("GH_PAT")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not gh_pat or not repo:
        print("GH_PAT 또는 GITHUB_REPOSITORY 없음 — refresh_token 자동 갱신 생략")
        return

    from nacl import encoding, public

    headers = {
        "Authorization": f"Bearer {gh_pat}",
        "Accept": "application/vnd.github+json",
    }
    pk_resp = requests.get(
        f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
        headers=headers,
        timeout=15,
    )
    pk_resp.raise_for_status()
    pk = pk_resp.json()

    public_key = public.PublicKey(pk["key"].encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(new_refresh_token.encode("utf-8"))
    encrypted_b64 = base64.b64encode(encrypted).decode("utf-8")

    put_resp = requests.put(
        f"https://api.github.com/repos/{repo}/actions/secrets/KAKAO_REFRESH_TOKEN",
        headers=headers,
        json={"encrypted_value": encrypted_b64, "key_id": pk["key_id"]},
        timeout=15,
    )
    put_resp.raise_for_status()
    print("KAKAO_REFRESH_TOKEN secret 자동 갱신 완료")


def dday(target_date: date, today: date) -> int:
    return (target_date - today).days


def build_messages(data, today: date):
    thresholds = set(data.get("notify_thresholds_days", [7, 3, 1, 0]))
    messages = []

    for stay in data.get("stays", []):
        if stay.get("status") == "취소":
            continue
        deadline = date.fromisoformat(stay["free_cancel_deadline"])
        d = dday(deadline, today)
        if d in thresholds:
            label = "D-DAY (오늘 마감)" if d == 0 else f"D-{d}"
            messages.append(f"🏠 [{stay['name']}] 무료취소 마감 {label} ({stay['free_cancel_deadline']})")

    trip_start = date.fromisoformat(data["trip_start"])
    for item in data.get("checklist", []):
        target = trip_start - timedelta(days=item["days_before"])
        d = dday(target, today)
        if d in thresholds:
            label = "D-DAY" if d == 0 else f"D-{d}"
            messages.append(f"✅ [체크리스트] {item['item']} — 완료 권장일 {label}")

    return messages


def send_kakao_message(access_token, text):
    template_object = {
        "object_type": "text",
        "text": text,
        "link": {"web_url": SITE_URL, "mobile_web_url": SITE_URL},
        "button_title": "일정 보기",
    }
    resp = requests.post(
        KAKAO_SEND_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        data={"template_object": json.dumps(template_object, ensure_ascii=False)},
        timeout=15,
    )
    resp.raise_for_status()
    print("카카오톡 전송 완료:", resp.json())


def main():
    access_token, new_refresh_token = refresh_kakao_token()
    if new_refresh_token:
        rotate_github_secret(new_refresh_token)

    with open("notify-data.json", encoding="utf-8") as f:
        data = json.load(f)

    today = date.today()
    messages = build_messages(data, today)

    if not messages:
        print(f"{today} 기준 알림 대상 없음")
        return

    text = "오사카 여행 준비 알림 🗾\n\n" + "\n".join(messages)
    send_kakao_message(access_token, text)


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print("HTTP 오류:", e.response.status_code, e.response.text, file=sys.stderr)
        raise
