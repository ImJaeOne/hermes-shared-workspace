# InnoDive Hermes Shared Workspace

이 저장소는 이노다이브 업무 자동화를 위한 공유 Hermes Agent 워크스페이스입니다.

## Repository layout

```text
innodive-automation/
  hermes-ax-plugin/        # 공통 AX Dashboard / MCP / Railway 배포 단위
  planning-automation/     # 기획 자동화 도메인 리소스
  design-automation/       # 디자인 자동화 도메인 리소스
  shared/                  # 공통 스키마, 프롬프트, 템플릿
  deploy/                  # 배포/운영 보조 파일
```

## Branch strategy

```text
main                         # 운영 배포 브랜치
dev                          # 개발 통합 브랜치
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
4. 검증된 변경만 `dev`로 합치고, 운영 배포는 `main` 기준으로 진행합니다.

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
