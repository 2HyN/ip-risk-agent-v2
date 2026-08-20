# integration-v2 통합 현황 기록

> 성격: **삭제 가능한 비규범적 작업 로그**
> 시작일: 2026-08-21
> 현재 단계: **통합 Phase 1 — 계획 확정 및 agent 문서 통합**
> 기준 문서: `INTEGRATION_V2_DEPENDENCY_BASELINE.md`, `INTEGRATION_V2_EXECUTION_PLAN.md`

이 문서는 통합 진행 중 확인한 사실, 실행 결과와 임시 판단을 시간순으로 남기는 보조 기록이다. 프로젝트의 실행, build, test 또는 배포가 이 문서에 의존해서는 안 되며, 작업 완료 후 삭제해도 프로젝트 완결성에 영향이 없어야 한다. 규범적 결정이 이 로그와 두 기준 문서 사이에서 충돌하면 기준 문서가 우선한다.

## 진행 원칙

- `integration-v2`에서만 변경한다.
- 두 통합 기준 문서를 규범적 기준으로 사용하고, 이 문서에는 실행 상태와 검증 증거만 누적한다.
- phase gate를 통과하기 전 다음 phase의 변경을 섞지 않는다.
- dependency manifest/lock, runtime composition, GCP 구성은 각 소유 phase에서만 변경한다.
- `shared/contracts/**`는 수정하지 않는다.
- 기존 agent별 원본 문서는 Phase 8 전까지 삭제하지 않는다.

## 시작 상태

| Branch | 시작 HEAD | 상태 |
|---|---|---|
| `integration-v2` | `ae566be3ffcc0e48e512b40c398269de7d6fff45` | clean |
| `main` | `7cfbec446ac50fcc36c14031cb4310c30c8a0e5c` | clean |
| `platform-control` | `de1dacce05474d4e3e6c7c2567f6b8a6bbdbeb64` | clean |
| `source-integration-desktop` | `ee861b730d161caf876d2a300b476783d03bbaf6` | clean |
| `risk-intelligence-rag` | `68e07a3fdf543bcb4871cb13aee95fcc64b5749d` | clean |

## Merge 기록

### 1. `platform-control`

- 상태: 완료
- merge commit: `f253312ea52519922edef9e8c8da3bdca0fcc5db`
- conflict: 없음
- 해결/검증:
  - `ort` strategy로 `--no-ff` merge 완료
  - Control canonical domain, application, persistence, API, Product UI와 test가 추가됨
  - merge 직후 worktree에 미해결 파일 없음
  - dependency/toolchain 정리 및 전체 test는 이번 단계 범위 밖이므로 실행하지 않음

### 2. `source-integration-desktop`

- 상태: 완료
- merge commit: `12c5b9f9dd71c981a2b6614099245fbc3e5493b9`
- conflict: 아래 네 frontend 설정 파일
  - `frontend/index.html`
  - `frontend/package.json`
  - `frontend/tsconfig.json`
  - `frontend/vite.config.ts`
- 해결/검증:
  - `index.html`: Control Product entrypoint와 metadata를 유지하고 `lang="ko"` 적용
  - `package.json`: Control의 exact dependency, router, Vitest/Testing Library 및 no-emit build 체계 유지
  - `tsconfig.json`: Control의 Bundler/no-emit/strict 설정을 유지하고 Source test compile을 위한 `node` type 추가
  - `vite.config.ts`: Control의 API proxy, sourcemap, Vitest/jsdom 설정 유지
  - 네 파일의 conflict marker 및 unmerged entry가 없음을 확인
  - Source의 `pnpm-lock.yaml`은 merge 결과를 그대로 수용했으며 최종 재생성은 이후 dependency 통합 단계로 보류
  - Source test의 Vitest 포팅과 dev preview 제거는 semantic integration이므로 이번 단계에서 수행하지 않음
  - staged whitespace 검사에서 incoming `AGENT_2_DELIVERY.md`의 EOF 빈 줄 1건이 보고됐으나, branch 원문을 보존하기 위해 수정하지 않음

### 3. `risk-intelligence-rag`

- 상태: 완료
- merge commit: `13caa161d204c819dbaa90fdf5292b1fd2ea071f`
- conflict: 없음
- 해결/검증:
  - `ort` strategy로 `--no-ff` merge 완료
  - Intelligence, Gemini, Patent, License, RAG, corpus와 test가 추가됨
  - merge 직후 worktree에 미해결 파일 없음
  - dependency/toolchain 정리 및 전체 test는 이번 단계 범위 밖이므로 실행하지 않음

## 현재 단계 종료 조건

- [x] 세 feature branch merge commit이 `integration-v2` history에 존재
- [x] 모든 merge conflict 해결
- [x] conflict marker 없음
- [x] `git diff --check` 통과
- [x] `shared/contracts/**`에 의도하지 않은 변경 없음
- [x] 다른 네 worktree clean 유지
- [x] 전체 통합 개발 및 dependency 재생성은 시작하지 않음

## 단계 종료 요약

- merge 순서: `platform-control` → `source-integration-desktop` → `risk-intelligence-rag`
- merge conflict: frontend 설정 파일 4건, 모두 기준 문서의 확정안대로 해결
- semantic integration: 미실행
- dependency/lockfile 최종화: 미실행
- test/build: 다음 dependency 통합 단계로 보류

## 전체 통합 계획

Merge는 준비 단계인 Phase 0으로 완료됐다. 본 통합은 아래 **9개 phase**로 진행한다.

| Phase | 목표 | 핵심 산출물 | 종료 gate | 상태 |
|---|---|---|---|---|
| 1 | 계획 확정과 agent 문서 통합 | 전체 phase 계획, Agent 1/2/3 단일 문서, 삭제 보류 목록 | source 문서 coverage와 보존 확인 | 진행 중 |
| 2 | dependency/toolchain 수렴 | root Python/Node manifest, 최종 lock, env schema | install/frozen install, Plane 전체 baseline test | 대기 |
| 3 | P0 경계 보강 | canonical worker input, lease/retry, Source authz/CSRF, pending connection, device auth, analyzer 완결성 | 경계별 integration test | 대기 |
| 4 | Backend/API/Worker 조립 | settings/container, Control+Source app, worker pipeline, provider registry, Open Original backend | local API/worker E2E와 상태 전이 검증 | 대기 |
| 5 | Web/Electron 제품 통합 | SourcePanel, OAuth completion/mount UI, Electron renderer/enrollment/local flow | browser/desktop E2E | 대기 |
| 6 | GCP 내부 구현 | Firestore operational stores, Secret Manager/GCS/Tasks adapters, indexes, Docker/Cloud Run/Scheduler/RAG tooling | emulator 및 staging-ready dry run | 대기 |
| 7 | 전체 검증과 release freeze | 전체 회귀, 보안/실패/복구 test, live-test runbook, blocker 0건 | 통합 완료 승인 | 대기 |
| 8 | 문서 정리와 배포 후보 고정 | 구 agent 문서 삭제, README/운영 문서 최종화, release candidate commit | 삭제 후 전체 검증 재통과 | 대기 |
| 9 | GCP 외부 구성·배포·실환경 검증 | console/IAM/resource 구성, 배포, live provider/E2E 증거 | production readiness 승인 | 대기 |

### Phase 의존 관계

```text
Phase 0 merge
  -> Phase 1 계획/문서
  -> Phase 2 dependency
  -> Phase 3 P0 경계
  -> Phase 4 backend composition
  -> Phase 5 Web/Electron
  -> Phase 6 GCP 내부 구현
  -> Phase 7 전체 검증
  -> Phase 8 구 문서 삭제 및 RC 고정
  -> Phase 9 GCP 외부 배포
```

Phase 5와 Phase 6의 일부 구현은 Phase 4의 public runtime contract가 확정된 뒤 병행할 수 있지만, gate 판정과 commit은 위 순서를 유지한다. Phase 8은 반드시 Phase 7 통과 후, Phase 9 시작 전에 수행한다.

### Phase 공통 운영 방식

각 phase마다 다음을 이 문서에 남긴다.

1. 시작 HEAD와 목표
2. 변경 파일과 핵심 결정
3. 발견한 blocker/known issue와 처리 상태
4. 실행한 검증 명령과 결과
5. 남은 작업 및 다음 phase 진입 여부

실패한 검증은 삭제하거나 성공으로 덮어쓰지 않고, 실패 원인과 재실행 결과를 함께 기록한다.

## Phase 1 — 계획 확정 및 agent 문서 통합

### 목표

- 9개 phase와 gate를 확정한다.
- agent별 분산 문서를 Agent 1/2/3 단일 참조 문서로 통합한다.
- 어떤 기존 문서를 Phase 8에서 삭제할지 명시한다.
- 기존 원본은 비교·검증을 위해 그대로 보존한다.

### 신규 유지 문서

```text
docs/AGENT_1_PLATFORM_CONTROL.md
docs/AGENT_2_SOURCE_DESKTOP.md
docs/AGENT_3_RISK_INTELLIGENCE_RAG.md
```

각 문서는 구현 범위, 코드 지도, public surface, dependency 검증 이력, 환경 변수, test 증거, integration wiring, 제약과 후속 작업을 한 곳에 모은다. 최종 dependency 결정은 각 문서의 과거 agent 검증값보다 `INTEGRATION_V2_DEPENDENCY_BASELINE.md`가 우선한다.

### Phase 8 삭제 예정 원본

```text
AGENT_1_DELIVERY.md
AGENT_1_PLATFORM_CONTROL_IMPLEMENTATION_PLAN.md
LOCAL_RUN_AND_TEST_GUIDE.md
agent-deliverables/agent-1-dependencies.md
AGENT_2_DELIVERY.md
agent-deliverables/agent-2-dependencies.md
AGENT_3_DELIVERY.md
agent-deliverables/agent-3-dependencies.md
```

삭제 조건:

- Phase 7 전체 검증 완료
- 신규 3개 문서와 최종 README/운영 문서만으로 build/test/운영 정보가 충분함을 확인
- build/test/운영 절차에서 사용하는 원본 파일명 참조를 신규 통합 문서 또는 최종 운영 문서로 교체
- 보호 대상 명세·기준 문서와 provenance/history 구간의 과거 파일명은 실행 경로로 오인되지 않도록 문맥을 확인한 뒤 보존 가능
- 삭제 commit 이후 전체 non-live regression 재통과
- GCP 외부 배포 Phase 9는 아직 시작하지 않은 상태

`CODING_AGENT_MASTER_SPEC.md`, 세 상세 명세, 청사진, 두 통합 기준 문서와 이 진행 로그는 위 삭제 대상이 아니다. Gemini prompt, RAG corpus source/README처럼 runtime 또는 data provenance에 필요한 Markdown도 agent 문서 정리 대상이 아니다.

### 작업 추적

- [x] 현재 Markdown inventory 작성
- [x] 전체 통합을 9개 phase로 분해
- [x] 삭제 시점을 Phase 8로 고정
- [x] Agent 1 단일 문서 작성
- [x] Agent 2 단일 문서 작성
- [x] Agent 3 단일 문서 작성
- [x] source 문서별 정보 coverage 확인
- [x] 기존 agent 문서가 삭제되지 않았는지 확인
- [ ] Phase 1 변경 commit 및 종료 gate 판정

### Phase 1 검증 기록

- 통합 대상 원본 8개를 Agent 1/2/3 문서의 provenance 표와 일대일로 대조했다.
- 신규 문서 3개의 Markdown code fence 짝과 conflict marker 부재를 확인했다.
- 삭제 예정 원본 8개와 보호 대상 명세·청사진·통합 기준 문서가 모두 남아 있음을 확인했다.
- 변경 범위는 이 진행 로그와 신규 agent 통합 문서 3개뿐이며 runtime code와 dependency file은 변경하지 않았다.
- 이 phase는 문서 정리만 수행하므로 runtime test는 실행하지 않는다. Phase 2부터 각 phase gate에 맞는 검증을 기록한다.
