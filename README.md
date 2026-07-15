# Lightweight LLM Colab Runner

Google Colab에서 로컬 LLM 또는 API 기반 AI를 실행해보는 공개 실행용 노트북입니다.

무료 Colab T4에서 계속 쓸 목적이면 26B 4-bit MLX 모델보다 T4에 맞춘 GGUF 모델이 현실적입니다. 기본 추천 노트북은 Google 공식 `Gemma 4 12B QAT Q4_0`을 실행하고, 필요하면 `Qwen3.5 9B` 또는 더 가벼운 `Qwen2.5 7B`로 바꿀 수 있는 T4용 Pro 노트북입니다.

[![Open T4 GGUF Pro Notebook In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/kingwabg/supergemma4-colab-runner/blob/main/notebooks/T4_GGUF_Qwen2_5_7B_Colab.ipynb)

## 노트북

- [T4 GGUF Pro: Gemma 4 · Qwen3.5 · API · RAG](https://colab.research.google.com/github/kingwabg/supergemma4-colab-runner/blob/main/notebooks/T4_GGUF_Qwen2_5_7B_Colab.ipynb)
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
7. 답변 검증, 연속 채팅, 문서 RAG, 7문항 평가, API 서버는 모두 기본 OFF입니다. 필요한 기능의 `RUN_... = True`만 켜고 해당 셀만 실행합니다.
8. 컨텍스트는 T4 안정성을 위해 4,096이 기본입니다. 정상 실행 후에만 `CONTEXT_OVERRIDE = 8192`를 시험하세요.

### 선택 기능

- 답변 검증: 같은 모델이 답변을 JSON으로 검토하고 문제가 있으면 한 번 다시 답합니다.
- 전문가 API 폴백: `RUN_HYBRID_EXPERT = True`; 로컬 최종 검증이 실패한 경우에만 지정한 OpenAI 호환 API가 답변을 교정합니다. 외부 전송과 비용이 있으므로 기본 OFF입니다.
- 연속 채팅: `RUN_CONTINUOUS_CHAT = True`; 종료는 `/exit`.
- 문서 RAG: `RUN_RAG = True`; TXT, MD, 코드, JSON, CSV, 텍스트 PDF를 업로드해 근거 기반으로 질문합니다.
- 모델 평가: `RUN_MODEL_EVAL = True`; 현재 모델의 7문항 결과를 `/content/model_eval_history.json`에 누적합니다.
- OpenAI 호환 API: `RUN_API_SERVER = True`; 현재 모델을 재사용해 `/v1/chat/completions`를 열고 Bearer 토큰을 검사합니다.
- 외부 API 주소: API 셀에서 `OPEN_EXTERNAL_TUNNEL = True`도 켜고 ngrok 토큰을 입력합니다. Colab 세션이 끝나면 주소도 종료됩니다.

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
    },
    timeout=180,
)
print(response.json()["choices"][0]["message"]["content"])
```

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
- 내장 7문항 점수는 기능 확인용이며 범용 지능 백분율이 아닙니다. 실제 목표는 자주 하는 업무 50~100개로 별도 평가하세요.

## 원본

- Model: https://huggingface.co/Jiunsong/supergemma4-26b-uncensored-mlx-4bit-v2
- Default GGUF model: https://huggingface.co/google/gemma-4-12B-it-qat-q4_0-gguf
- Alternative GGUF model: https://huggingface.co/bartowski/Qwen_Qwen3.5-9B-GGUF
- Stable GGUF model: https://huggingface.co/lmstudio-community/Qwen2.5-7B-Instruct-GGUF
- Ultra-light GGUF model: https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF
