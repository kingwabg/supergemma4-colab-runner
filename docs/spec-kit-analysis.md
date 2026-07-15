# Spec Kit 적용 분석

분석 대상: [github/spec-kit](https://github.com/github/spec-kit)

## 결론

Spec Kit 전체 CLI를 Colab에 설치해 로컬 모델이 임의 코드를 실행하게 만드는 대신, 핵심 설계인 `constitution → specify → plan → tasks → analyze`를 경량 Python 워크플로로 이식한다. 산출물은 Markdown으로 저장하고, 실제 명령 실행은 하지 않는다.

## 가져온 원칙

- 명세가 구현을 이끈다. 요청의 `무엇`과 `왜`를 먼저 고정한다.
- 요구사항, 계획, 작업을 분리한다.
- 작업은 `T001` 형식과 대상 파일 경로를 포함해 실행 가능하게 만든다.
- 구현 전 산출물 간 모순과 누락을 검사한다.
- 프로젝트별 헌법으로 품질·보안·비용 원칙을 고정한다.

## SuperGemma에 맞춘 차이

- 무료 T4의 컨텍스트 한계를 고려해 이전 산출물 전달량을 제한한다.
- 실행 단계는 문서 생성까지만 지원한다. 생성된 셸 명령과 코드는 자동 실행하지 않는다.
- 각 단계는 같은 로컬 모델 검증기와 재시도를 통과해야 한다.
- 로컬 재시도 후에도 실패하고 사용자가 명시적으로 켠 경우에만 외부 API로 폴백한다.
- 결과는 `/content/supergemma_specs/<feature>/` 아래 `constitution.md`, `spec.md`, `plan.md`, `tasks.md`, `analysis.md`, `manifest.json`으로 저장한다.

## 품질 측정

`evals/real_work_eval_75.json`은 한국어 지시 수행, 추론, 코딩, 업무 생산성, RAG 근거성, 안전·불확실성, API 형식의 75문항으로 구성한다. 평가는 중간 종료 후 재개할 수 있고, 범주별 점수와 실패 답변을 JSON에 남긴다.

95점 기준은 이 저장소의 75문항에서 72개 이상 통과했다는 뜻이다. Codex 전체 능력의 95%를 의미하지 않는다.
