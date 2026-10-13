# 영남권 CTF Agent Engineering

8개 공용 CLI Worker가 모델별 Stage Profile을 실행하는 로컬 시스템입니다. Supervisor는 Python 프로그램이며 LLM 슬롯에 포함되지 않습니다. Flag 제출과 팀 Solve 확인은 사용자가 합니다.

## 시작

처음 실행하는 운영자는 [한국어 CLI 시작과 운영 매뉴얼](docs/cli-manual-ko.md)의 모의 시험부터 진행하세요. 현재 Windows 실행기는 한 창에 Worker 탭 8개를 엽니다.

[문제 캡처로 TOML 자동 생성하기](docs/screenshot-toml-ko.md): 문제별 `info/` 캡처와 `files/` 첨부파일을 준비한 뒤 `ctfctl make-toml <폴더> --batch`로 `challenge.toml`을 생성합니다. `scope.toml`은 변경하지 않습니다.

실행 환경은 WSL Ubuntu / Python 3.11 이상입니다. Windows Python 3.10은 지원하지 않습니다.

```bash
cd '/mnt/c/Users/happy/Ready_Google/CTF/2026_영남권 CTF/Agent Engineering'
python3 scripts/bootstrap_codex.py
.local/toolchains/codex/bin/codex login status
# 로그인되어 있지 않을 때만: .local/toolchains/codex/bin/codex login --device-auth
# config/scope.example.toml을 scope.toml로 복사하고 실제 허가 범위를 기입
python3 ctfctl.py init-run
python3 ctfctl.py doctor --live
python3 ctfctl.py import '/path/to/problem' --id c001 --title '문제 이름'
python3 ctfctl.py start --workers 8
```

8개 보이는 Windows Terminal 탭은 PowerShell에서 `scripts/launch-8.ps1`을 실행합니다. 작업 파일을 수정한 뒤에는 preflight를 다시 실행해야 합니다. `doctor --live`는 실제 구독 사용량을 소비하며 8개 동시 요청과 모든 fallback profile을 검사합니다.

## 주요 운영 명령

```bash
python3 ctfctl.py status --watch
python3 ctfctl.py pause c001
python3 ctfctl.py resume c001
python3 ctfctl.py solved c001 --by team
python3 ctfctl.py solved c001 --by self  # VERIFIED 후 플랫폼에서 정답 확인한 경우
python3 ctfctl.py stop c001 --hard
python3 ctfctl.py quota --remaining 50
python3 ctfctl.py snapshot
python3 ctfctl.py shutdown --graceful
```

자세한 운영은 docs/runbook.md, 복구는 docs/recovery.md, 규칙은 docs/rulebook.md를 읽으세요. 실제 인증과 모델 Canary가 통과하지 않으면 실전 준비 완료로 표시하지 않습니다.

현재 설치에서는 기존 Windows Codex 계정이 WSL에 로컬 연결되어 있습니다. 마지막 확인에서 13개 모델 Profile의 실제 Canary가 모두 통과했습니다. 실전 자동 실행에는 실제 대회용 scope.toml 작성과 init-run이 추가로 필요합니다. models_ready와 실전 ready는 별도 값입니다.

## 검증

```bash
python3 -m unittest discover -s tests -t . -v
python3 scripts/stress.py --tasks 1000
python3 scripts/rehearse.py
```

Mock·리허설은 실제 LLM Solve와 분리해서 보고합니다. 테스트는 임시 Linux 폴더에서 실행해 실제 문제·원본을 변경하지 않습니다.

## 자료 위치

- docs: 설계·규칙·운영·복구·요구사항 점검
- config / prompts / schemas: 고정된 모델 역할 및 계약
- src / scripts / tests: 구현·실행기·검증
- challenges: 정제된 Solver와 Evidence
- .local: 원본·비밀·수동 제출 기록, Git 제외
- .runtime: 실행 상태·Attempt·격리 로그, Git 제외
- reports: 시험·리허설·Preflight 및 Snapshot

DB와 유일한 체크포인트가 남아 있는 동안 .runtime을 삭제하지 마세요. Snapshot과 원본으로 복구 가능함을 확인한 후에만 정리합니다.

