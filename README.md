# SuperGemma4 Colab Runner

Google Colab GPU에서 `Jiunsong/supergemma4-26b-uncensored-mlx-4bit-v2`를 실행해보는 공개 실행용 노트북입니다.

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/kingwabg/supergemma4-colab-runner/blob/main/notebooks/SuperGemma4_Colab_MLX_CUDA.ipynb)

## 사용법

1. 위 Colab 버튼을 엽니다.
2. Colab 메뉴에서 `Runtime > Change runtime type > GPU`를 선택합니다.
3. 위에서부터 셀을 순서대로 실행합니다.
4. 단발 생성 테스트가 성공하면 `대화형 채팅` 셀을 실행합니다.
5. `나:` 입력창에 질문을 쓰고 Enter를 누릅니다.
6. 종료하려면 `/exit` 또는 `/quit`을 입력합니다.

## 주의

- 무료 Colab GPU 종류와 사용 시간은 보장되지 않습니다.
- 26B 4-bit 모델은 GPU 메모리가 작으면 OOM이 날 수 있습니다.
- 이 저장소에는 모델 가중치를 포함하지 않습니다. 모델은 Hugging Face에서 런타임마다 내려받습니다.
- 비밀키, 개인정보, 민감한 업무 데이터를 프롬프트에 넣지 마세요.

## 원본

- Model: https://huggingface.co/Jiunsong/supergemma4-26b-uncensored-mlx-4bit-v2
