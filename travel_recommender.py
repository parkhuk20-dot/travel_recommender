"""LLM과 Kakao Local API로 만드는 국내 여행 추천 CLI."""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from openai import OpenAI


RESULTS_DIR = Path("results")
REQUIRED_RECOMMENDATION_KEYS = {
    "recommended_cities": list,
    "weather": str,
    "events": list,
    "reason": str,
}


def parse_date(value: str) -> str:
    """argparse용 날짜 검증 함수."""
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("날짜는 YYYY-MM-DD 형식이어야 합니다.") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM + 지도 API 국내 여행 추천 프로그램")
    parser.add_argument("-date", required=True, type=parse_date, help='여행 날짜 (예: "2026-08-15")')
    return parser.parse_args()


def safe_error(exc: Exception) -> str:
    """오류 메시지에 우연히 포함될 수 있는 API 키를 마스킹한다."""
    message = str(exc)
    for key_name in ("OPENAI_API_KEY", "KAKAO_REST_API_KEY"):
        secret = os.getenv(key_name)
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return message[:500]


def extract_json(text: str) -> dict[str, Any]:
    """모델의 JSON 응답을 파싱하고 필수 스키마를 확인한다."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("LLM 응답이 JSON 객체가 아닙니다.")
    for key, expected_type in REQUIRED_RECOMMENDATION_KEYS.items():
        if not isinstance(data.get(key), expected_type):
            raise ValueError(f"LLM JSON의 필수 키 또는 타입이 올바르지 않습니다: {key}")
    if not all(isinstance(event, str) for event in data["events"]):
        raise ValueError("events는 문자열 배열이어야 합니다.")
    cities = data["recommended_cities"]
    if not cities or not all(isinstance(city, str) and city.strip() for city in cities):
        raise ValueError("recommended_cities는 비어 있지 않은 문자열 배열이어야 합니다.")
    return data


def chat(client: OpenAI, messages: list[dict[str, str]], *, json_mode: bool = False) -> str:
    options: dict[str, Any] = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "messages": messages,
        "temperature": 0.4,
    }
    if json_mode:
        options["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(**options)
    content = response.choices[0].message.content
    if not content:
        raise ValueError("LLM이 빈 응답을 반환했습니다.")
    return content


def get_recommendation(client: OpenAI, travel_date: str) -> dict[str, Any]:
    prompt = f"""당신은 국내 여행 추천 도우미입니다. 여행 날짜는 {travel_date}입니다.
실시간 사실 검증이 아니라, 해당 시기의 일반적인 여행 아이디어를 제안하세요.
반드시 아래 키만 가진 유효한 JSON 객체로 답하세요. Markdown 코드블록이나 설명은 금지합니다.
{{
  "recommended_cities": ["추천 도시 또는 지역명 2~3개"],
  "weather": "일반적인 날씨 요약",
  "events": ["행사 또는 축제 후보 1~3개"],
  "reason": "추천 근거 2~4문장 (각 지역을 고른 이유 포함)"
}}
"""
    messages = [{"role": "system", "content": "항상 한국어로 응답합니다."}, {"role": "user", "content": prompt}]
    for attempt in range(2):
        try:
            return extract_json(chat(client, messages, json_mode=True))
        except (json.JSONDecodeError, ValueError) as exc:
            if attempt == 1:
                raise ValueError(f"LLM 추천 JSON 파싱 실패: {exc}") from exc
            messages.append({"role": "assistant", "content": "직전 응답은 스키마 검증에 실패했습니다."})
            messages.append({"role": "user", "content": "필수 키와 타입을 정확히 지킨 JSON 객체만 다시 출력하세요."})
    raise RuntimeError("도달할 수 없는 코드")


def search_restaurants(city: str, kakao_key: str) -> list[dict[str, Any]]:
    response = requests.get(
        "https://dapi.kakao.com/v2/local/search/keyword.json",
        headers={"Authorization": f"KakaoAK {kakao_key}"},
        params={"query": f"{city} 맛집", "size": 5},
        timeout=10,
    )
    response.raise_for_status()
    documents = response.json().get("documents", [])
    places: list[dict[str, Any]] = []
    for item in documents:
        def number_or_none(value: Any) -> float | None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        places.append({
            "name": item.get("place_name", ""),
            "address": item.get("road_address_name") or item.get("address_name") or "",
            "category": item.get("category_name", ""),
            "url": item.get("place_url", ""),
            "x": number_or_none(item.get("x")),
            "y": number_or_none(item.get("y")),
        })
    return places


def fallback_report(travel_date: str, recommendation: dict[str, Any], restaurants_by_city: dict[str, list[dict[str, Any]]], errors: list[dict[str, str]]) -> str:
    place_sections = []
    for city, places in restaurants_by_city.items():
        listing = "\n".join(f"- {p['name']} — {p['address']}" for p in places) or "- 데이터 없음"
        place_sections.append(f"### {city}\n{listing}")
    places_text = "\n\n".join(place_sections) or "데이터 없음"
    events = "\n".join(f"- {event}" for event in recommendation["events"]) or "- 데이터 없음"
    errors_text = "\n".join(f"- [{e['step']}] {e['type']}: {e['message']}" for e in errors) or "- 없음"
    return f"""# {travel_date} 국내 여행 리포트

## 추천 지역
{', '.join(recommendation['recommended_cities'])}

## 추천 이유
{recommendation['reason']}

## 날씨 요약
{recommendation['weather']}

## 행사/축제
{events}

## 맛집 리스트
{places_text}

## 일정 제안
- 오전: 대표 명소를 방문합니다.
- 오후: 지역 문화 공간과 카페를 둘러봅니다.
- 저녁: 위 맛집 후보 중 한 곳에서 식사합니다.

## Errors
{errors_text}
"""


def create_report(client: OpenAI, travel_date: str, recommendation: dict[str, Any], restaurants_by_city: dict[str, list[dict[str, Any]]], errors: list[dict[str, str]]) -> str:
    context = json.dumps({"date": travel_date, "recommendation": recommendation, "restaurants_by_city": restaurants_by_city, "errors": errors}, ensure_ascii=False)
    prompt = f"""다음 JSON 데이터를 바탕으로 한국어 여행 리포트를 Markdown으로 작성하세요.
반드시 '추천 지역', '추천 이유', '날씨 요약', '행사/축제', '맛집 리스트', '일정 제안', 'Errors' 섹션을 포함하세요.
추천 지역이 여러 곳이면 맛집 리스트와 1일 일정 제안을 지역별 하위 섹션으로 정리하세요.
어떤 지역의 맛집이 빈 배열이면 그 지역에 정확히 '데이터 없음'이라고 쓰세요. 사실을 새로 만들어내지 말고 제공 데이터를 중심으로 작성하세요.

{context}"""
    return chat(client, [{"role": "system", "content": "친절하고 간결한 한국어 여행 작가입니다."}, {"role": "user", "content": prompt}])


def load_cached_raw(raw_path: Path) -> dict[str, Any] | None:
    """같은 날짜의 원본 JSON이 있으면 읽어서 API 호출을 건너뛸 수 있게 한다."""
    if not raw_path.exists():
        return None
    try:
        cached = json.loads(raw_path.read_text(encoding="utf-8"))
        recommendation = cached["recommendation"]
        # 구버전(단일 지역) 캐시 파일도 그대로 쓸 수 있도록 형식을 맞춘다.
        if "recommended_city" in recommendation and "recommended_cities" not in recommendation:
            recommendation["recommended_cities"] = [recommendation.pop("recommended_city")]
        restaurants = cached.get("restaurants_by_city")
        if restaurants is None:
            restaurants = {recommendation["recommended_cities"][0]: cached.get("restaurants", [])}
        return {
            "recommendation": recommendation,
            "restaurants_by_city": restaurants,
            "errors": cached.get("errors", []),
        }
    except (json.JSONDecodeError, KeyError, IndexError, OSError):
        return None


def main() -> int:
    args = parse_args()
    load_dotenv()
    openai_key = os.getenv("OPENAI_API_KEY")
    kakao_key = os.getenv("KAKAO_REST_API_KEY")
    if not openai_key or not kakao_key:
        print("[오류] API 키가 설정되지 않았습니다. .env에 OPENAI_API_KEY와 KAKAO_REST_API_KEY를 설정하세요.", file=sys.stderr)
        return 1

    client = OpenAI(api_key=openai_key)
    RESULTS_DIR.mkdir(exist_ok=True)
    raw_path = RESULTS_DIR / f"{args.date}_raw.json"
    report_path = RESULTS_DIR / f"{args.date}_travel_report.md"

    cached = load_cached_raw(raw_path)
    if cached:
        print(f"[캐시] 기존 원본 데이터({raw_path})를 발견했습니다. 추천/맛집 API 호출을 건너뜁니다.")
        recommendation = cached["recommendation"]
        restaurants_by_city = cached["restaurants_by_city"]
        errors = [e for e in cached["errors"] if e.get("step") != "report_generation"]
    else:
        errors = []
        print("[1/4] LLM으로 여행 지역을 추천받는 중...")
        try:
            recommendation = get_recommendation(client, args.date)
        except Exception as exc:
            print(f"[오류] 추천 생성 실패: {safe_error(exc)}", file=sys.stderr)
            return 1
        cities = recommendation["recommended_cities"]
        print(f"    - 추천 지역: {', '.join(cities)}")

        print("[2/4] Kakao Local에서 지역별 맛집을 검색하는 중...")
        restaurants_by_city: dict[str, list[dict[str, Any]]] = {}
        for city in cities:
            try:
                places = search_restaurants(city, kakao_key)
                if not places:
                    errors.append({
                        "step": "place_search",
                        "type": "EMPTY_RESULT",
                        "message": f"0 results for query={city} 맛집",
                    })
                    print(f"    - {city}: 검색 결과 0건. '데이터 없음'으로 처리하고 계속 진행합니다.")
                else:
                    print(f"    - {city}: 맛집 {len(places)}곳 검색 완료")
            except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
                places = []
                status = getattr(getattr(exc, "response", None), "status_code", None)
                error_type = "AUTH_ERROR" if status in (401, 403) else "API_ERROR"
                errors.append({"step": "place_search", "type": error_type, "message": f"{city}: {safe_error(exc)}"})
                if error_type == "AUTH_ERROR":
                    print(f"    - {city}: 인증 실패({status}). Kakao REST API 키 설정을 확인하세요.")
                print(f"    - {city}: 맛집 정보를 가져오지 못했습니다. 리포트는 계속 생성합니다.")
            restaurants_by_city[city] = places

    print("[3/4] 최종 Markdown 리포트를 생성하는 중...")
    try:
        report = create_report(client, args.date, recommendation, restaurants_by_city, errors)
    except Exception as exc:
        errors.append({"step": "report_generation", "type": "LLM_ERROR", "message": safe_error(exc)})
        report = fallback_report(args.date, recommendation, restaurants_by_city, errors)
        print("[경고] 기본 템플릿으로 리포트를 생성했습니다.")

    raw_path.write_text(json.dumps({"travel_date": args.date, "recommendation": recommendation, "restaurants_by_city": restaurants_by_city, "errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(report, encoding="utf-8")
    print("[4/4] 저장 완료")
    print(f"- 원본 데이터: {raw_path}")
    print(f"- 여행 리포트: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
