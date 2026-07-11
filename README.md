# 국내 여행 추천 CLI

OpenAI LLM API와 Kakao Local API를 연결해, 여행 날짜에 맞는 국내 여행지를 추천하고 맛집을 검색한 뒤 Markdown 리포트로 저장하는 Python CLI 프로그램입니다.

## 동작 흐름

1. `-date` 값을 LLM에 전달하고 추천 지역 2~3곳이 담긴 JSON 추천 데이터로 받습니다.
2. 각 추천 도시를 Kakao Local 키워드 검색의 입력으로 사용해 지역별 맛집 최대 5곳을 찾습니다.
3. 추천 JSON과 지역별 맛집 목록을 다시 LLM에 전달해 최종 Markdown 리포트를 만듭니다.
4. 원본 JSON과 리포트를 `results/`에 저장합니다.

같은 `-date`로 다시 실행하면 저장된 원본 JSON을 캐시로 사용해 추천/맛집 API 호출을 건너뛰고 리포트만 다시 생성합니다. 캐시를 무시하고 새로 호출하려면 `--force-refresh` 옵션을 붙이세요.

LLM이 자유 텍스트로 답하면 프로그램이 결과를 기계적으로 활용할 수 없으므로, 1차 추천은 JSON 스키마를 강제해 **구조화된 출력**으로 받습니다. 이렇게 해야 추천 결과를 안정적으로 파싱해 다음 단계(장소 검색)의 입력으로 연결할 수 있습니다.

## 설계 메모

- 현재는 학습용 단일 파일 구성이지만, 추천(`get_recommendation`)/검색(`search_restaurants`)/리포트(`create_report`) 기능을 함수 단위로 분리해 두어 규모가 커지면 recommender·searcher·reporter 모듈로 나누기 쉽게 설계했습니다.
- 1차 추천 JSON 스키마는 `REQUIRED_RECOMMENDATION_KEYS` 상수로 관리합니다. 키를 추가/변경할 때는 이 상수와 `extract_json`의 제약 검증, LLM 프롬프트의 스키마 예시를 함께 수정해야 합니다.
- 검색 결과 0건 시 현재는 "데이터 없음"으로 진행하며, 필요하면 도 단위로 쿼리를 넓혀 재검색하는 폴백 전략을 확장 지점으로 남겨 두었습니다.

## 설치

Python 3.10 이상을 권장합니다.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
```

## API 키 설정

`.env` 파일에 아래 값을 설정합니다.

```env
OPENAI_API_KEY=실제_OpenAI_API_키
KAKAO_REST_API_KEY=실제_Kakao_REST_API_키
```

- OpenAI 키는 OpenAI API 프로젝트에서 발급합니다.
- Kakao 키는 Kakao Developers에서 애플리케이션을 만든 뒤 **REST API 키**를 사용합니다.
- 키를 코드에 직접 쓰지 마세요. `.env`는 `.gitignore`에 포함되어 있으므로 Git에 커밋하지 않습니다.
- 터미널 로그, README, 결과 JSON/Markdown에도 키를 복사하거나 붙여넣지 마세요.
- 프로덕션/CI 환경에서는 `.env` 파일 대신 시크릿 매니저(GitHub Actions Secrets, AWS Secrets Manager 등)로 키를 주입하는 것을 권장합니다.

## 실행

```bash
python travel_recommender.py -date "2026-08-15"
```

날짜 형식이 잘못되면 `argparse`가 사용법과 함께 오류를 출력합니다. 키가 설정되지 않았으면 API 호출 전에 즉시 종료하며 설정 방법을 안내합니다.

## 결과 확인

성공 시 `results/` 폴더에 실행 날짜 기준으로 다음 파일이 생성됩니다.

- `YYYY-MM-DD_raw.json`: 1차 추천 JSON, 지역별 맛집 목록, 오류 목록
- `YYYY-MM-DD_travel_report.md`: 추천 지역·이유·날씨·행사·지역별 맛집·1일 일정이 담긴 최종 리포트

Kakao Local 호출이 인증·쿼터·네트워크 문제로 실패하거나 검색 결과가 없어도 프로그램은 맛집을 `데이터 없음`으로 두고 리포트 생성을 계속합니다. LLM의 1차 JSON 파싱은 실패 시 스키마를 다시 요구해 한 번 재시도합니다.

## API 기초 정리

- REST API는 URL(엔드포인트)로 요청을 보내고 보통 JSON 응답을 받는 방식입니다.
- `GET`은 주로 데이터를 조회합니다. 이 프로그램의 Kakao 장소 검색이 해당합니다.
- `POST`는 주로 서버에 새 처리나 데이터를 요청합니다. LLM 생성 요청은 입력 프롬프트를 담아 `POST`로 처리됩니다.
- 외부 API는 인증(401/403), 사용량 제한(429), 네트워크 오류, 응답 JSON 파싱 오류가 날 수 있습니다. 호출부를 `try-except`로 감싸고, 실패해도 가능한 다음 단계로 진행하거나 사용자에게 안전하게 안내하는 것이 원칙입니다.
