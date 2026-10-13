# Runbook

## 대회 전

1. WSL에서 project-local Codex 로그인. 전역 Windows Codex는 변경하지 않습니다.
2. 실제 공식 규정·대상·시간을 scope.toml에 기입합니다. 대회 날짜는 자동 추정하지 말고 확인한 값을 씁니다.
3. init-run → doctor --live → 로컬 리허설. Canary 실패 시 자동 모드 No-Go입니다.
4. 최종 코드/프롬프트/프로필의 fingerprint와 정확한 CLI 버전을 reports/preflight.json으로 고정합니다.
5. 실제 대용량 분석 도구와 Container가 필요한 문제는 별도 준비합니다. doctor가 도구 누락을 표시합니다.

## 문제 투입

파일 하나 또는 폴더를 import 합니다. 설명은 --description으로 전달합니다. Batch 입력은 각 하위 폴더에 challenge.toml(id/title/category/description)과 files/가 필요합니다. Import는 원본 복사·해시·Prescan 후 Intake를 예약합니다.

8개 초기 문제가 끝날 때까지 기다리지 않습니다. 슬롯이 비면 다음 Stage/문제가 자동 실행됩니다. Worker 탭에는 현재 문제와 Profile이 표시됩니다.

## 수동 제어

첫 Ctrl+C는 해당 문제 pause 후 다음 큐 작업을 받습니다. 5초 이내 재입력은 hard stop입니다. Idle 상태 Ctrl+C는 Worker를 종료합니다. 팀원이 Solve하면 solved ID --by team. 본인 후보는 VERIFIED를 확인하고 플랫폼에 수동 제출한 뒤 solved ID --by self.

requeue ID --profile PROFILE은 수동 Profile 회전입니다. Depth에서 다른 독립 가설을 추가할 때만 --hypothesis '구체적 다른 가설'을 지정합니다. Extend는 primitive/candidate가 존재할 때 --reason과 함께 한 번만 가능합니다.

status --watch는 상태·모델·마지막 실패를 표시합니다. 실제 flag는 .local/secrets 참조를 통해 운영자가 확인합니다. Export에는 secret 원문을 포함하지 않습니다. Shutdown은 신규 dispatch를 멈추고 실행을 pause하며 Snapshot을 남깁니다.

## 수동 Fallback

자동 Go/No-Go가 실패하면 개별 문제 디렉터리 8개를 수동 CLI로 열고 명시적 모델/등급을 선택합니다. Supervisor를 먼저 shutdown하고 프로세스가 모두 종료됐는지 확인합니다. 실제 Daybreak 권한 문제는 UI에서 지원되는 모델로 직접 확인합니다.

