# InnoDive Hermes Shared Workspace

이 저장소는 이노다이브 업무 자동화를 위한 공유 Hermes Agent 워크스페이스입니다.

## Repository layout

현재 저장소의 실행/배포 단위는 `hermes-ax-plugin/`입니다. 기획 자동화, AX Dashboard, MCP 서버, Slack 자료조사 worker는 먼저 이 플러그인 안에서 통합 운영하고, 도메인별 패키지 분리는 필요해질 때 별도 결정 기록/Issue로 진행합니다.

```text
innodive-automation/
  hermes-ax-plugin/        # 공통 AX Dashboard / MCP / Slack 자료조사 / Railway 배포 단위
```

향후 `planning-automation/`, `design-automation/`, `shared/`, `deploy/` 같은 도메인/공통 디렉터리를 추가할 수 있지만, 현재 기준 필수 레이아웃은 아닙니다.

## Branch strategy

현재 운영은 `main` 기준 trunk-based workflow입니다. `dev` 브랜치는 현재 원격 추적 대상이 아니며 통합 브랜치로 사용하지 않습니다.

```text
main                         # 최신 개발 및 운영 배포 기준 브랜치
feature/<area>/<task>        # 기능 작업
fix/<area>/<task>            # 버그 수정
hotfix/<area>/<task>         # 운영 긴급 수정
docs/<area>/<task>           # 문서 작업
chore/<area>/<task>          # 유지보수 작업
```

주요 area:

```text
platform, dashboard, mcp, planning, design, gateway, shared, docs
```

예시:

```text
feature/platform/initial-repo-setup
feature/planning/company-research-flow
feature/design/design-brief-flow
fix/mcp/docker-volume-path
```

## Working rule

1. Issue로 작업 목표와 완료 조건을 먼저 정의합니다.
2. 사용자 확인 후 `feature/<area>/<task>` 브랜치에서 작업합니다.
3. PR에는 변경사항, 테스트 결과, Railway 영향, rollback 방법을 기록합니다.
4. 검증된 변경만 PR로 `main`에 합치고, 운영 배포도 `main` 기준으로 진행합니다.

## Local Docker check

```bash
cd hermes-ax-plugin
docker build -t hermes-ax-plugin:local .
docker run --rm \
  --name hermes-ax-local \
  -p 9119:9119 \
  -e PORT=9119 \
  -e RUN_MODE=dashboard \
  -v hermes_ax_data:/data \
  hermes-ax-plugin:local
```

Open:

```text
http://127.0.0.1:9119
```

## Railway deployment note

Recommended Railway service root:

```text
hermes-ax-plugin
```

Required volume mount:

```text
/data
```

Recommended environment variables:

```text
HERMES_HOME=/data/.hermes
PORT=9119
RUN_MODE=both
```
