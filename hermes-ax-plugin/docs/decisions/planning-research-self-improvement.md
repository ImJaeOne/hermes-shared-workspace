# 기획 자료조사 Agent의 Hermes 기반 자가 발전 구조

상태: Accepted working decision
작성일: 2026-05-29
관련 이슈: [#62](https://github.com/ImJaeOne/hermes-shared-workspace/issues/62), [#39](https://github.com/ImJaeOne/hermes-shared-workspace/issues/39), [#48](https://github.com/ImJaeOne/hermes-shared-workspace/issues/48), [#50](https://github.com/ImJaeOne/hermes-shared-workspace/issues/50), [#42](https://github.com/ImJaeOne/hermes-shared-workspace/issues/42), [#26](https://github.com/ImJaeOne/hermes-shared-workspace/issues/26)

## 배경

기획 자료조사 MVP는 단순 Slack 챗봇이나 Dashboard CRUD가 아니다. 목표는 Hermes Agent를 서버에 함께 배포해 회사 공용 AI credential, persistent `HERMES_HOME`, Hermes skill/prompt/memory, AX workflow를 하나의 제품형 업무 흐름으로 묶는 것이다.

비개발자 직원은 Slack과 AX Dashboard만 사용한다. 직원 개인이 Codex/OpenAI 계정을 인증하거나 Railway CLI, Docker, raw secret을 다루지 않는다. 서버는 persistent `HERMES_HOME=/data/.hermes`에 설정된 회사 공용 Hermes provider credential을 사용한다.

자가 발전은 모든 대화를 즉시 전역 지식에 반영하는 기능이 아니다. 일반 사용자의 자료조사·수정·승인 이력은 현재 workflow/artifact를 개선하는 데 쓰고, `planninglearner` 또는 learner approval role을 가진 경로에서만 prompt/skill/memory 개선 후보를 만들 수 있다. 후보는 승인 전까지 실제 런타임 기준에 적용하지 않는다.

## 결정 요약

1. AX 자료조사의 Slack 진입점은 Hermes Gateway가 아니라 AX Slack Adapter다.
2. Hermes Gateway는 Slack에서 범용 Hermes Agent와 직접 대화하기 위한 선택 기능이며, AX workflow 실행에는 필수가 아니다.
3. AX Slack Adapter는 Slack 이벤트를 AX workflow, source material, worker request/result, artifact, Dashboard 기록으로 연결한다.
4. 직원별 AI provider 인증은 구현하지 않는다. 서버 공용 Hermes credential을 사용한다.
5. 일반 사용자 수정 요청은 현재 산출물과 workflow 상태만 바꾼다.
6. `planninglearner` 경로만 prompt/skill/memory 개선 후보를 생성·검토·승인·적용할 수 있다.
7. 승인된 runtime 변경은 `$HERMES_HOME`에 적용될 수 있지만, 운영 volume은 최종 source of truth가 아니다. 조직 표준으로 남길 변경은 Git PR로 승격한다.

## Gateway와 AX Slack Adapter 차이

| 구분 | Hermes Gateway | AX Slack Adapter |
| --- | --- | --- |
| 목적 | Slack/Telegram/Discord 등에서 Hermes Agent와 범용 대화 | Slack 이벤트를 AX 업무 workflow로 변환 |
| 사용자 경험 | “Hermes에게 직접 물어보기” | “자료 업로드 → 자료 확인 → worker 실행 → 결과 문서 → 수정/승인” |
| 상태 저장 | Hermes session 중심 | AX DB의 workflow/artifact/worker/activity 중심 |
| 필수 여부 | AX 자료조사 MVP에는 필수 아님 | AX 자료조사 Slack UX의 기본 진입점 |
| 실행 경계 | Agent가 자유롭게 도구를 사용할 수 있음 | AX stage/action/template/worker 경계로 제한 |

AX 자료조사 MVP에서는 AX Slack Adapter를 기본으로 둔다. Hermes Gateway는 향후 범용 사내 Hermes 대화 채널이 필요할 때 별도 활성화한다.

## 서버 공용 AI credential 모델

운영 서버는 다음 구조를 따른다.

```text
직원 Slack 계정
→ AX Slack Adapter
→ AX workflow / worker / learner
→ 서버 Hermes provider credential
→ AI 응답 또는 개선 후보
→ Slack / Dashboard / artifact
```

원칙:

- 직원 개인은 Codex/OpenAI/API key를 인증하지 않는다.
- Railway Volume은 `/data`, `HERMES_HOME`은 `/data/.hermes`를 기준으로 한다.
- OAuth 기반 provider는 회사/운영 계정으로 인증하고 persistent `HERMES_HOME`에 저장한다.
- secret 값은 README, Issue, PR, 로그, Slack 메시지, artifact에 출력하지 않는다.
- AI credential 유무를 확인할 때는 `SET`/`unset`, `exists`/`missing` 같은 메타 정보만 출력한다.

## 사용자와 learner 경계

| Actor | 역할 | 허용되는 변경 |
| --- | --- | --- |
| 일반 사용자 | 자료 제공, 결과 검토, 수정 요청, 최종 확정 | 현재 workflow/artifact/comment/stage |
| 기획팀 임팀장 | Slack 응대, 자료 충분성 확인, worker 실행 조율 | AX stage/action/template에 제한된 실행 |
| 기획팀 임사원 | 자료조사 worker 실행 | request/result/artifact 생성 |
| `planninglearner` | 학습/개선 후보 생성·검토·승인 | prompt/skill/memory candidate 및 승인된 적용 |
| system | 이벤트 기록, 자동 상태 갱신 | activity log, idempotency, 안전한 background runner |

일반 사용자가 “이 문서를 더 투자자 관점으로 고쳐줘”라고 요청하면 현재 자료조사 artifact 수정으로 처리한다. 이 요청만으로 전역 prompt, Hermes skill, Hermes memory가 바뀌면 안 된다.

`planninglearner`가 같은 이력을 검토하거나 learner 경로에서 작업할 때만 개선 후보를 만들 수 있다. 후보는 `draft`, `reviewed`, `approved`, `applied`, `rejected` 같은 상태를 갖고, 승인 전에는 실제 worker 실행 기준에 반영하지 않는다.

## 개선 후보 대상

자가 발전 후보는 다음 대상을 다룬다.

- 자료조사 prompt/template
- 자료조사 worker playbook 또는 Hermes skill
- Word/Markdown 문서 템플릿과 섹션 지침
- 장기 운영 원칙 수준의 memory 후보

다음은 후보 대상에서 제외한다.

- 고객 원본 자료 전문
- PDF/문서 원문 전체
- 일회성 회사 프로젝트 사실
- Slack 표시 이름이나 이메일만으로 추론한 권한
- 승인되지 않은 일반 사용자 대화

## 후속 Issue 로드맵

작업 순서는 다음을 기준으로 한다.

1. [#39 NotebookLM 인증 상태 점검 및 관리자 재인증 플로우 추가](https://github.com/ImJaeOne/hermes-shared-workspace/issues/39)
   - 자료조사 엔진 인증 안정성을 확보한다.
   - NotebookLM 세션 만료 시 운영자가 secret 노출 없이 상태를 점검하고 갱신할 수 있어야 한다.
2. [#48 Slack 결과 문서 파일 업로드와 비개발자 상태 메시지 개선](https://github.com/ImJaeOne/hermes-shared-workspace/issues/48)
   - 사용자가 Slack에서 결과 문서를 직접 열어 검토하도록 만든다.
   - 결과 문서는 이후 수정/승인 피드백과 learner 후보 생성의 기준 산출물이 된다.
3. [#50 Word 문서 템플릿과 자료조사 지침 관리자화](https://github.com/ImJaeOne/hermes-shared-workspace/issues/50)
   - 문서 구조와 자료조사 지침을 개선 가능한 단위로 분리한다.
   - worker result/artifact metadata에 template id/version과 research skill id를 추적할 수 있게 한다.
4. [#42 임팀장 AI 자연어 intent 판단 어댑터 추가](https://github.com/ImJaeOne/hermes-shared-workspace/issues/42)
   - Slack 자연어 답변을 제한된 intent enum/action/template key로 구조화한다.
   - AI는 판단만 하고, 실제 실행은 AX workflow/stage/worker 경계에서 수행한다.
5. [#26 planninglearner 계정 매핑과 프롬프트·스킬·메모리 개선 승인 흐름 구현](https://github.com/ImJaeOne/hermes-shared-workspace/issues/26)
   - 자료조사·수정·승인 이력에서 개선 후보를 만들고 승인된 후보만 적용한다.
   - Hermes native skill/memory 적용과 Git PR 승격 경계를 기록한다.

## Artifact와 metadata 원칙

후속 learner 후보가 품질 개선의 근거를 추적할 수 있도록, 가능한 한 worker result/artifact metadata에 다음을 남긴다.

- workflow id, worker request id, worker result id
- source material 목록과 저장 key
- research engine과 fallback 여부
- research skill id
- document template id/version
- 자연어 intent, confidence, fallback 여부, internal note
- prompt/skill/template version

metadata에는 민감한 원문 secret이나 OAuth token을 저장하지 않는다.

## 적용과 source of truth

승인된 후보는 운영 편의를 위해 런타임 `$HERMES_HOME`에 먼저 적용될 수 있다. 그러나 Railway volume의 runtime state는 source-controlled truth가 아니다.

조직 표준으로 남길 변경은 별도 Git PR로 승격한다. PR에는 변경 이유, diff, 적용 대상, 검증 결과를 남기고, 운영 secret 값이나 고객 원본 자료를 포함하지 않는다.

## 검증 관점

이 구조를 구현할 때는 다음을 확인한다.

- 일반 사용자 수정 요청이 전역 prompt/skill/memory를 즉시 바꾸지 않는다.
- `planninglearner` 또는 learner approval role이 아닌 사용자는 후보를 승인/적용할 수 없다.
- Slack에서는 표시 이름이나 이메일만으로 learner 권한을 부여하지 않는다.
- AI credential이 없거나 호출에 실패하면 후보 생성만 안전하게 실패하고 기존 자료조사 worker 흐름은 깨지지 않는다.
- 승인/적용 이력은 activity log와 candidate diff로 추적된다.
