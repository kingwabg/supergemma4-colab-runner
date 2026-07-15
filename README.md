# SuperGemma T4 Agent Runner

Google Colab에서 로컬 GGUF 모델을 실행하고 RAG, 답변 검증, 자동 재시도, 선택적 강한 API 폴백, Spec Kit 방식 업무 설계, 75문항 평가, OpenAI 호환 API까지 사용하는 공개 실행용 노트북입니다.

무료 Colab T4에서 계속 쓸 목적이면 26B 4-bit MLX 모델보다 T4에 맞춘 GGUF 모델이 현실적입니다. 기본 추천 노트북은 Google 공식 `Gemma 4 12B QAT Q4_0`을 실행하고, 필요하면 `Qwen3.5 9B` 또는 더 가벼운 `Qwen2.5 7B`로 바꿀 수 있는 T4용 Pro 노트북입니다.

[![Open T4 GGUF Pro Notebook In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/kingwabg/supergemma4-colab-runner/blob/main/notebooks/T4_GGUF_Qwen2_5_7B_Colab.ipynb)

## 노트북

- [T4 GGUF Pro Agent: Gemma 4 · Spec · RAG · 75 Eval · API](https://colab.research.google.com/github/kingwabg/supergemma4-colab-runner/blob/main/notebooks/T4_GGUF_Qwen2_5_7B_Colab.ipynb)
- [SuperGemma4 26B MLX CUDA 실행](https://colab.research.google.com/github/kingwabg/supergemma4-colab-runner/blob/main/notebooks/SuperGemma4_Colab_MLX_CUDA.ipynb)
- [OpenAI API Codex-style 채팅](https://colab.research.google.com/github/kingwabg/supergemma4-colab-runner/blob/main/notebooks/OpenAI_API_Codex_Style_Colab.ipynb)

## 사용법

T4 GGUF Pro 노트북:

1. Colab 메뉴에서 `런타임 > 런타임 유형 변경 > T4 GPU`를 선택합니다.
2. `모두 실행`을 누릅니다. 기본 모델 다운로드가 약 7GB라 몇 분 걸릴 수 있습니다.
3. 기본값 `MODEL_PRESET = "gemma4_12b"`는 `Gemma 4 12B QAT Q4_0`을 사용합니다.
4. 비교하려면 `qwen3_5_9b`, 안정성을 우선하면 `qwen2_5_7b`, 가장 가볍게 쓰려면 `ultra_light`로 바꾸고 모델 선택 셀부터 다시 실행합니다.
5. `정상동작 답변: 서울`이 나오면 준비 완료입니다.
6. 원하는 질문은 `QUESTION = "..."` 값을 바꾼 뒤 `한 번 질문하기` 셀만 다시 실행합니다.
7. 답변 검증, 연속 채팅, 문서 RAG, Spec 업무 설계, 75문항 평가, API 서버는 모두 기본 OFF입니다. 필요한 기능의 `RUN_... = True`만 켜고 해당 셀만 실행합니다.
8. 컨텍스트는 T4 안정성을 위해 4,096이 기본입니다. 정상 실행 후에만 `CONTEXT_OVERRIDE = 8192`를 시험하세요.

### 선택 기능

- 답변 검증·재시도: 같은 모델이 답변을 JSON으로 검토하고 문제가 있으면 검증 지시를 반영해 한 번 다시 답합니다.
- 전문가 API 폴백: `ENABLE_HYBRID_FALLBACK = True`; 로컬 재시도와 최종 검증까지 실패한 경우에만 지정한 OpenAI 호환 API가 답변을 교정합니다. 외부 전송과 비용이 있으므로 기본 OFF입니다.
- 연속 채팅: `RUN_CONTINUOUS_CHAT = True`; 종료는 `/exit`.
- 문서 RAG: `RUN_RAG = True`; TXT, MD, 코드, JSON, CSV, 텍스트 PDF를 업로드합니다. 검색 결과가 없으면 답변을 만들지 않고, 답변에 실제 제공된 `[근거 N]`만 쓰는지 검증합니다.
- Spec Kit 방식 업무 설계: `RUN_SPEC_AGENT = True`; 요청에서 `constitution.md`, `spec.md`, `plan.md`, `tasks.md`, `analysis.md`, `manifest.json`을 `/content/supergemma_specs/`에 만듭니다. 생성된 코드는 자동 실행하지 않습니다.
- 실제 업무 평가: `RUN_MODEL_EVAL = True`; 7개 범주의 75문항을 계산기와 출력 계약(JSON·한 줄·줄 수) 도구를 포함한 엄격 지시문으로 실행합니다. 실패 문항만 정답 유출 없이 1회 자동 수정하고 `/content/model_eval_<preset>_<run-label>.json`에 저장합니다. 중단해도 같은 모델·평가셋·실행 라벨이면 이어서 실행합니다.
- OpenAI 호환 Agent API: `RUN_API_SERVER = True`; 현재 모델을 재사용해 `/v1/chat/completions`, `/v1/rag/query`, `/v1/spec/run`을 열고 Bearer 토큰을 검사합니다.
- 외부 API 주소: API 셀에서 `OPEN_EXTERNAL_TUNNEL = True`도 켜고 ngrok 토큰을 입력합니다. Colab 세션이 끝나면 주소도 종료됩니다.

### Spec Kit 적용 방식

[github/spec-kit](https://github.com/github/spec-kit)의 `constitution → specify → plan → tasks → analyze` 구조를 무료 T4용 경량 Python 워크플로로 적용했습니다. Spec Kit 전체 CLI를 Colab 모델에 맡겨 임의 명령을 실행하는 구조는 아닙니다. 자세한 분석은 [docs/spec-kit-analysis.md](docs/spec-kit-analysis.md)에 있습니다.

```python
RUN_SPEC_AGENT = True
SPEC_REQUEST = "업로드한 규정 문서를 근거로 승인 문서 생성 기능을 설계해줘."
SPEC_USE_RAG = True  # 먼저 RAG 업로드 셀을 실행한 경우
```

### 75문항 평가

평가셋은 [evals/real_work_eval_75.json](evals/real_work_eval_75.json)에 있으며 한국어 지시 10, 추론 15, 코딩 15, 업무 10, RAG 10, 안전·불확실성 10, API 형식 5문항입니다.

```python
RUN_MODEL_EVAL = True
EVAL_LIMIT = 75
EVAL_CATEGORIES = []  # 예: ["coding", "rag_grounding"]
EVAL_RESUME = True
EVAL_RUN_LABEL = "tool-agent-v4"
```

95점 목표는 이 고정 평가셋에서 72/75 이상 통과한다는 뜻입니다. Codex 전체 능력의 95%라는 뜻은 아닙니다. 전체 평가는 T4에서 시간이 오래 걸리므로 범주별로 나눠 실행할 수 있습니다.

Colab T4에서 측정한 단계별 결과와 남은 약점은 [docs/evaluation-results.md](docs/evaluation-results.md)에 기록했습니다.

API가 실행된 뒤 같은 Colab 런타임에서 확인하는 예:

```python
import requests

response = requests.post(
    f"{local_api_base}/chat/completions",
    headers={"Authorization": f"Bearer {API_TOKEN}"},
    json={
        "model": MODEL_ALIAS,
        "messages": [{"role": "user", "content": "안녕하세요."}],
        "max_tokens": 128,
        "enable_thinking": False,
        "quality_mode": "verified",  # direct | verified | hybrid
    },
    timeout=180,
)
print(response.json()["choices"][0]["message"]["content"])
```

`quality_mode="hybrid"`는 `ENABLE_HYBRID_FALLBACK = True`와 외부 API 설정이 있어야 합니다. RAG 업로드 셀에서 인덱스를 만든 뒤 `/v1/rag/query`를 호출할 수 있고, `/v1/spec/run`은 Spec 산출물 경로와 단계별 검증 결과를 JSON으로 반환합니다.

SuperGemma4 MLX 노트북:

1. Colab 메뉴에서 `Runtime > Change runtime type > GPU`를 선택합니다.
2. 위에서부터 셀을 순서대로 실행합니다.
3. 단발 생성 테스트가 성공하면 `대화형 채팅` 셀을 실행합니다.
4. `나:` 입력창에 질문을 쓰고 Enter를 누릅니다.
5. 종료하려면 `/exit` 또는 `/quit`을 입력합니다.

OpenAI API Codex-style 노트북:

1. GPU가 필요 없습니다. 하드웨어 가속기는 `CPU`로 둬도 됩니다.
2. 위에서부터 셀을 순서대로 실행합니다.
3. API 키 입력창이 뜨면 OpenAI API 키를 입력합니다.
4. 연결 테스트가 성공하면 `Codex 스타일 코딩 도우미` 셀을 실행합니다.
5. `나:` 입력창에 질문을 쓰고 Enter를 누릅니다.

## 주의

- 무료 Colab GPU 종류와 사용 시간은 보장되지 않습니다.
- 26B 4-bit 모델은 무료 T4에서 실사용이 어렵거나 OOM이 날 수 있습니다.
- Gemma 4 12B도 런타임 상태에 따라 느리거나 OOM이 날 수 있습니다. 그 경우 컨텍스트를 2,048로 낮추거나 `qwen2_5_7b` 또는 `ultra_light` 프리셋을 쓰세요.
- 이 저장소에는 모델 가중치를 포함하지 않습니다. 모델은 Hugging Face에서 런타임마다 내려받습니다.
- 비밀키, 개인정보, 민감한 업무 데이터를 프롬프트에 넣지 마세요.
- 무료 Colab과 임시 ngrok 주소는 상시 서비스용 API 서버가 아닙니다.
- 같은 모델 검증기는 자기 오류를 놓칠 수 있습니다. 75문항의 결정적 채점 결과와 실패 사례를 함께 확인하세요.
- 75문항 점수는 이 저장소의 회귀 비교 지표이며 범용 지능 백분율이 아닙니다.

## 원본

- Model: https://huggingface.co/Jiunsong/supergemma4-26b-uncensored-mlx-4bit-v2
- Default GGUF model: https://huggingface.co/google/gemma-4-12B-it-qat-q4_0-gguf
- Alternative GGUF model: https://huggingface.co/bartowski/Qwen_Qwen3.5-9B-GGUF
- Stable GGUF model: https://huggingface.co/lmstudio-community/Qwen2.5-7B-Instruct-GGUF
- Ultra-light GGUF model: https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF
