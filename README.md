# Lightweight LLM Colab Runner

Google Colab에서 로컬 LLM 또는 API 기반 AI를 실행해보는 공개 실행용 노트북입니다.

무료 Colab T4에서 계속 쓸 목적이면 26B 4-bit MLX 모델보다 더 작은 GGUF 모델이 현실적입니다. 기본 추천 노트북은 `Qwen2.5-7B-Instruct-GGUF`를 `llama-cpp-python`으로 실행하는 T4용 GGUF 노트북입니다.

[![Open T4 GGUF Notebook In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/kingwabg/supergemma4-colab-runner/blob/main/notebooks/T4_GGUF_Qwen2_5_7B_Colab.ipynb)

## 노트북

- [T4 GGUF Qwen2.5 7B 채팅](https://colab.research.google.com/github/kingwabg/supergemma4-colab-runner/blob/main/notebooks/T4_GGUF_Qwen2_5_7B_Colab.ipynb)
- [SuperGemma4 26B MLX CUDA 실행](https://colab.research.google.com/github/kingwabg/supergemma4-colab-runner/blob/main/notebooks/SuperGemma4_Colab_MLX_CUDA.ipynb)
- [OpenAI API Codex-style 채팅](https://colab.research.google.com/github/kingwabg/supergemma4-colab-runner/blob/main/notebooks/OpenAI_API_Codex_Style_Colab.ipynb)

## 사용법

T4 GGUF Qwen2.5 노트북:

1. Colab 메뉴에서 `런타임 > 런타임 유형 변경 > T4 GPU`를 선택합니다.
2. 위에서부터 셀을 순서대로 실행합니다.
3. 기본값은 `balanced`이며 `Qwen2.5-7B-Instruct-Q4_K_M.gguf`를 사용합니다.
4. 메모리가 부족하거나 너무 느리면 모델 선택 셀에서 `MODEL_PRESET = "ultra_light"`로 바꾼 뒤 다시 실행합니다.
5. 단발 생성 테스트가 성공하면 `한 번 질문하기` 셀이 기본 질문으로 한 번 더 답변을 생성합니다.
6. 원하는 질문은 `QUESTION = "..."` 값을 바꾼 뒤 해당 셀만 다시 실행합니다.
7. 연속 대화가 필요할 때만 `선택: 연속 채팅` 셀의 `RUN_CONTINUOUS_CHAT = True`로 바꿔 따로 실행합니다.
8. 기본값은 `False`라서 `모두 실행`해도 연속 채팅 셀에서 멈추지 않습니다.

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
- GGUF 노트북도 런타임 상태에 따라 느릴 수 있습니다. 그 경우 `ultra_light` 프리셋을 쓰세요.
- 이 저장소에는 모델 가중치를 포함하지 않습니다. 모델은 Hugging Face에서 런타임마다 내려받습니다.
- 비밀키, 개인정보, 민감한 업무 데이터를 프롬프트에 넣지 마세요.

## 원본

- Model: https://huggingface.co/Jiunsong/supergemma4-26b-uncensored-mlx-4bit-v2
- Default GGUF model: https://huggingface.co/lmstudio-community/Qwen2.5-7B-Instruct-GGUF
- Ultra-light GGUF model: https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF
