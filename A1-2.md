# 제출 문서 — 국내 여행 추천 CLI (LLM + 지도 API 조합)

## 1. 프로그램 개요

사용자가 여행 날짜(`-date "YYYY-MM-DD"`)를 입력하면,

1. **OpenAI LLM API**가 해당 시기에 여행하기 좋은 국내 지역 2~3곳을 날씨·행사 정보와 함께 **구조화된 JSON**으로 추천하고,
2. 추천 지역명을 입력으로 **Kakao Local API**가 지역별 맛집 5곳을 검색한 뒤,
3. 두 결과를 다시 LLM에 전달해 **최종 여행 리포트(Markdown)** 를 생성하여 `results/`에 저장하는 CLI 프로그램입니다.

단일 API 호출이 아니라, LLM의 구조화된 출력이 지도 API의 입력이 되고 두 API의 데이터가 다시 LLM의 입력이 되는 **API 파이프라인**으로 구성했습니다.

- 소스 코드: `travel_recommender.py` (단일 파일)
- LLM API: OpenAI Chat Completions (`gpt-4o-mini`, `OPENAI_MODEL`로 변경 가능)
- 지도/장소 API: Kakao Local 키워드 검색 (`/v2/local/search/keyword.json`)

## 2. 실행 방법

```bash
# 1) 설치 (Python 3.10 이상)
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2) API 키 설정
cp .env.example .env             # .env 파일에 실제 키 입력

# 3) 실행
python travel_recommender.py -date "2026-09-21"
```

실행 로그 예시:

```
[1/4] LLM으로 여행 지역을 추천받는 중...
    - 추천 지역: 서울, 부산, 제주도
[2/4] Kakao Local에서 지역별 맛집을 검색하는 중...
    - 서울: 맛집 5곳 검색 완료
    - 부산: 맛집 5곳 검색 완료
    - 제주도: 맛집 5곳 검색 완료
[3/4] 최종 Markdown 리포트를 생성하는 중...
[4/4] 저장 완료
- 원본 데이터: results/2026-09-21_raw.json
- 여행 리포트: results/2026-09-21_travel_report.md
```

날짜 형식이 잘못되면 argparse가 사용법과 오류를 출력하고 즉시 종료합니다.

## 3. API 키 설정 방법

`.env` 파일에 아래 두 값을 설정합니다 (`.env.example` 참고).

```env
OPENAI_API_KEY=발급받은_OpenAI_API_키
KAKAO_REST_API_KEY=발급받은_Kakao_REST_API_키
```

- OpenAI 키: OpenAI 플랫폼에서 API 키 발급
- Kakao 키: Kakao Developers에서 애플리케이션 생성 후 **REST API 키** 사용
- 키가 하나라도 없으면 프로그램이 API 호출 전에 **즉시 종료**하며 설정 방법을 안내합니다.

**보안 주의 사항**
- API 키는 코드/README/결과물 어디에도 직접 쓰지 않으며, `.env`는 `.gitignore`에 포함되어 Git에 커밋되지 않습니다.
- 예외 메시지에 키가 우연히 섞여 나가지 않도록 오류 문자열에서 키 값을 `[REDACTED]`로 마스킹합니다(`safe_error`).

## 4. 결과물 확인 방법

실행하면 `results/` 폴더에 날짜 기준으로 두 파일이 생성됩니다.

| 파일 | 내용 |
|---|---|
| `results/YYYY-MM-DD_raw.json` | 1차 추천 JSON(파싱 결과) + 지역별 맛집 검색 결과 + 오류 목록(`errors`, 빈 배열 가능) |
| `results/YYYY-MM-DD_travel_report.md` | 추천 지역/이유, 날씨 요약, 행사·축제, 지역별 맛집 리스트, 일정 제안, Errors 섹션이 담긴 최종 리포트 |

제출 저장소에는 실제 실행 결과 2세트(`2026-09-21`, `2026-10-03`)가 포함되어 있습니다.

## 5. 기능 요구사항 구현 내역

| 요구사항 | 구현 내용 |
|---|---|
| CLI (argparse, `-date` 필수) | `parse_args`에서 `-date`를 필수 옵션으로 정의, `parse_date`가 정규식 + `datetime.strptime`으로 검증하고 실패 시 사용법 출력 후 종료 |
| 1차 추천 JSON 스키마 | 프롬프트에 스키마를 명시하고 OpenAI JSON 모드(`response_format: json_object`) 사용. `extract_json`이 필수 키 존재와 타입(문자열 배열 등)을 검증 |
| JSON 파싱 실패 재시도 | 검증 실패 시 "필수 키와 타입을 지킨 JSON만 다시 출력"을 요구하며 **최대 1회만** 재시도 (`get_recommendation`) |
| 맛집 검색 | 추천 도시명으로 `"{도시} 맛집"` 키워드 검색, 도시별 5곳. name/address/category/url/x/y 필드 정규화 (`search_restaurants`) |
| 검색 0건 처리 | 중단 없이 `EMPTY_RESULT` 오류를 기록하고 "데이터 없음" 상태로 리포트 생성 진행 |
| 지도 API 실패 처리 | 401/403은 `AUTH_ERROR`, 그 외는 `API_ERROR`로 분류해 errors에 기록하고 리포트 생성은 계속 진행 |
| 최종 리포트 | 추천 지역·이유·날씨·행사/축제·맛집 리스트·일정 제안(오전/오후/저녁)·Errors 섹션 포함. LLM 호출 실패 시에도 내장 템플릿(`fallback_report`)으로 리포트를 반드시 생성 |
| 오류 목록 관리 | 모든 단계의 실패를 `{step, type, message}` 형식으로 수집해 raw JSON과 리포트 Errors 섹션에 기록 (빈 배열 가능) |
| 키 미설정 처리 | 두 키 중 하나라도 없으면 즉시 종료 + `.env` 설정 방법 안내 |
| 결과 저장 | `results/` 자동 생성, 날짜 기준 파일명으로 raw JSON과 `.md` 리포트 저장 |

## 6. 보너스 과제 구현 내역

### 6-1. 복수 지역 추천

- 1차 추천을 `recommended_city`(단일) 대신 **`recommended_cities`(2~3개 배열)** 로 받도록 프롬프트와 스키마 검증을 확장했습니다.
- 각 지역에 대해 루프를 돌며 맛집을 검색하고(`for city in cities`), 지역별 오류도 개별 기록합니다.
- 리포트는 맛집 리스트와 일정 제안을 **지역별 하위 섹션**으로 정리합니다.

### 6-2. 결과 캐싱

- 같은 `-date`로 재실행하면 `results/YYYY-MM-DD_raw.json`을 캐시로 읽어 **LLM 추천과 맛집 검색 API 호출을 건너뛰고** 리포트만 재생성합니다(`load_cached_raw`).
- 캐시를 무시하려면 해당 날짜의 raw JSON을 삭제한 뒤 실행합니다.

```
[캐시] 기존 원본 데이터(results/2026-10-03_raw.json)를 발견했습니다. 추천/맛집 API 호출을 건너뜁니다.
[3/4] 최종 Markdown 리포트를 생성하는 중...
```

## 7. 과제 목표에 대한 이해 정리

### 7-1. REST API의 요청/응답 구조와 GET/POST의 차이

REST API는 URL(엔드포인트)로 요청을 보내고 상태 코드와 함께 (보통 JSON) 응답을 받는 방식입니다. **GET**은 서버의 데이터를 조회하며 파라미터를 쿼리스트링으로 전달합니다 — 이 프로그램의 Kakao 장소 검색이 GET입니다. **POST**는 요청 본문(body)에 데이터를 담아 서버에 처리를 요청합니다 — LLM 생성 요청은 프롬프트 전체를 body에 담아야 하므로 POST로 처리됩니다.

### 7-2. LLM 출력 구조화 → 다음 단계 입력 연결

LLM이 자유 텍스트로 답하면 프로그램이 기계적으로 활용할 수 없으므로, 프롬프트에 JSON 스키마를 명시하고 JSON 모드를 사용해 **파싱 가능한 구조화 출력**을 강제했습니다. 이렇게 얻은 `recommended_cities` 배열이 그대로 지도 API 검색 루프의 입력이 되고, 1차 JSON + 맛집 목록이 다시 최종 리포트 생성 LLM의 입력이 됩니다.

### 7-3. 외부 API 대표 오류와 대응 원칙

- **인증(401/403)**: 키 값·헤더·권한 설정 점검. 본 프로그램은 `AUTH_ERROR`로 기록하고 안내 메시지 출력
- **쿼터/사용량 제한(429)** 및 **네트워크 오류(타임아웃 등)**: `requests` 예외로 잡아 `API_ERROR`로 기록
- **파싱 오류**: LLM 응답 JSON 검증 실패 시 1회만 재시도(무한 재시도 금지)
- 공통 원칙: 호출부를 try-except로 감싸고, **부분 실패가 전체 실패가 되지 않도록** 실패한 데이터는 "데이터 없음"으로 두고 다음 단계를 계속 진행하며, 오류는 errors 목록으로 남깁니다.

### 7-4. API 키를 .env/환경변수로 관리하는 이유

- 코드 공유/협업 시 키가 저장소에 노출되는 사고를 방지합니다.
- 키를 교체해도 코드를 수정할 필요가 없어 운영·배포에 유리합니다.
- 과금·쿼터가 걸린 서비스에서 키 유출로 인한 비용 사고를 예방합니다.

## 8. 파일 구성

```
travel_recommender/
├── travel_recommender.py   # 메인 프로그램 (CLI + API 파이프라인)
├── requirements.txt        # openai, python-dotenv, requests
├── README.md               # 개요, 실행/키 설정/결과 확인 방법
├── SUBMISSION.md           # 제출 문서 (본 파일)
├── .env.example            # 키 설정 템플릿 (실제 키 없음)
├── .gitignore              # .env, .venv 등 제외
└── results/                # 실행 결과 (raw JSON + 리포트 md)
```
