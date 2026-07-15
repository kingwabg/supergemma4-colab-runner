# Tasks: Spec-driven Quality Agent

## 작업 목록

- [x] T001 Spec Kit 핵심 흐름 분석을 docs/spec-kit-analysis.md에 기록
- [x] T002 프로젝트 헌법을 .specify/memory/constitution.md에 추가
- [x] T003 Spec 산출물 생성기를 supergemma_agent/spec_workflow.py에 구현
- [x] T004 평가 로더와 결정적 채점기를 supergemma_agent/evaluation.py에 구현
- [x] T005 75문항 평가셋을 evals/real_work_eval_75.json에 생성
- [x] T006 노트북에서 저장소 도구 모듈을 동기화하고 import
- [x] T007 노트북 RAG 검색 결과 없음 처리와 출처 검증 강화
- [x] T008 노트북에 Spec 워크플로 실행 셀 추가
- [x] T009 OpenAI 호환 API에 direct/verified/hybrid 품질 모드 추가
- [x] T010 75문항 평가를 체크포인트·범주 점수 방식으로 교체
- [x] T011 tests/test_agent_stack.py 단위 테스트 추가
- [x] T012 README 사용법과 95점 해석을 갱신
- [x] T013 노트북 구조·구문·모의 실행 검증

## 의존성

- T005는 T004 이후 수행한다.
- T006~T010은 T003~T005 이후 수행한다.
- T011~T013은 구현 작업 이후 수행한다.

## 완료 조건

- 모든 T001~T013이 완료 표시된다.
- 평가셋은 정확히 75문항이며 각 문항이 결정적 grader를 가진다.
- 외부 API는 기본 OFF이고 로컬 최종 실패 때만 호출된다.
- 로컬 모의 테스트와 노트북 정적 검사가 통과한다.
