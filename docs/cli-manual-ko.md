# 영남권 CTF CLI 시작과 운영 매뉴얼

처음에는 별도 폴더에서 모의 실행으로 조작을 익힌 뒤, 실제 모델 실행으로 넘어갑니다. 모의 실행은 구독 사용량을 소비하지 않습니다. 실제 모델 풀이와 `doctor --live`는 구독 사용량을 소비합니다.

이 시스템은 `codex` 채팅 8개에 직접 명령을 입력하는 방식이 아닙니다. 사용자는 관리 터미널에서 `ctfctl.py`로 문제를 넣고 제어하며, Supervisor가 모델과 단계를 선택해 Worker에 배정합니다. Worker 탭은 실행 상태 확인과 Ctrl+C 제어용입니다.

## 1 터미널 역할 구분

| 터미널 | 사용하는 명령 | 용도 |
|---|---|---|
| Windows Terminal의 PowerShell | `wsl.exe`, `git`, `launch-8.ps1` | WSL 진입과 Worker 탭 열기 |
| Ubuntu 관리 터미널 | `python3 ctfctl.py ...` | 문제 투입, 상태 확인, 중단, 종료 |
| CTF w01부터 w08까지의 Worker 탭 | 실행 상태를 보고 필요한 때 Ctrl+C | 자동 배정된 단계 실행 |

현재 실행기는 Windows Terminal 한 창에 탭 8개를 만듭니다. 별도 창 8개나 화면 분할 8개를 만드는 기능은 아닙니다. 관리 터미널은 Worker 8개에 포함되지 않습니다.

아래 PowerShell 블록과 Bash 블록을 구분해서 실행하세요. `C:\...`는 Windows 경로, `/mnt/c/...`는 WSL 경로입니다. Worker 탭 안에서는 추가 `codex`나 Worker를 실행하지 않습니다.

## 2 처음 한 번 환경 확인

Windows Terminal에서 PowerShell 탭을 열고 실행합니다.

```powershell
Get-Command wt.exe, wsl.exe, git
wsl.exe -l -v
wsl.exe -d Ubuntu
```

Ubuntu가 WSL 2로 표시되어야 합니다. 마지막 명령부터는 Ubuntu 셸입니다. 다음을 실행합니다.

```bash
cd '/mnt/c/Users/happy/Ready_Google/CTF/2026_영남권 CTF/Agent Engineering'
python3 --version
.local/toolchains/codex/bin/codex --version
.local/toolchains/codex/bin/codex login status
python3 ctfctl.py --help
```

Python은 3.11 이상이어야 합니다. 이 PC의 고정 CLI는 `codex-cli 0.162.1`이며, 로그인 상태는 `Logged in using ChatGPT`로 확인합니다. 단순히 `codex`를 입력하면 다른 전역 설치가 선택될 수 있으므로 위의 프로젝트 전용 경로를 사용합니다.

현재 PC는 기존 계정의 로그인을 연결한 상태입니다. 로그인 오류가 있을 때만 재인증을 검토하고, 토큰이나 `auth.json` 내용을 채팅·Git에 붙여 넣지 않습니다. CLI의 로그인 상태 명령은 [공식 CLI 문서](https://learn.chatgpt.com/docs/cli/reference), WSL 실행 환경은 [공식 WSL 문서](https://learn.chatgpt.com/docs/windows/wsl)를 참고하세요.

이 채팅에서 Agent가 WSL을 실행할 때 필요한 승인과, 사용자가 직접 PowerShell에서 WSL을 여는 것은 별개입니다. `Wsl/E_ACCESSDENIED`가 나오면 실행한 환경과 권한을 확인하고, 샌드박스를 통째로 해제하지 않습니다.

## 3 가장 간단한 모의 시험

2번의 Ubuntu 관리 터미널에서 실행합니다.

```bash
python3 scripts/rehearse.py
```

이 명령은 임시 환경에서 8개 모의 문제의 전체 단계를 실행한 뒤 정리합니다. 출력의 `passed: true`, `orphan_active: 0`, `db_integrity: "ok"`를 확인합니다. 보고서는 원래 프로젝트의 `reports/rehearsal/mock.json`에 저장됩니다.

이 시험은 보이는 Worker 탭을 열지 않으며, 실제 모델의 문제 해결 능력을 시험하지 않습니다.

## 4 실제로 보이는 Worker 탭 8개 시험

### 모의 전용 폴더 만들기

Ubuntu에서 `exit`를 입력해 PowerShell로 돌아오거나 새 PowerShell 탭을 엽니다. 다음은 원래 프로젝트의 커밋된 파일만 복제합니다. 기존 상태 DB·인증정보·실전 문제는 복사하지 않습니다.

```powershell
Set-Location -LiteralPath 'C:\Users\happy\Ready_Google\CTF\2026_영남권 CTF\Agent Engineering'
if (Test-Path -LiteralPath '.local/cli-mock-01') { throw '이미 존재하는 모의 폴더입니다. 기존 실행을 확인하거나 새 폴더 이름을 사용하세요.' }
git clone --no-hardlinks . '.local/cli-mock-01'
if ($LASTEXITCODE -ne 0) { throw '모의 폴더 복제 실패' }
wsl.exe -d Ubuntu
```

Ubuntu에서 다음을 실행합니다.

```bash
cd '/mnt/c/Users/happy/Ready_Google/CTF/2026_영남권 CTF/Agent Engineering/.local/cli-mock-01'
python3 ctfctl.py init-run --mock
python3 -c "from pathlib import Path; from tests.support import problem; from ctf_engine.state import State; from ctf_engine.scope import load; r=Path.cwd(); s=State(r); h=load(r,True)[1]; [problem(r,s,h,f'c{i:03d}','crypto','mock-delay:10') for i in range(1,13)]"
python3 ctfctl.py status
```

긴 한 줄은 기존 테스트 도우미로 12개 자체 제작 모의 문제를 만들고 등록합니다. 각 단계에 10초 지연을 주어 중단·교체를 연습할 시간을 확보합니다. 실제 CTF 문제나 원격 서비스에는 사용하지 않습니다. 모의 폴더에는 Codex 바이너리가 없어도 되며 `doctor --live`도 실행하지 않습니다.

`init-run --mock`와 모의 문제 생성은 이 폴더에서 한 번만 실행합니다. 이미 초기화됐다는 오류가 나오면 DB를 지우지 말고 기존 실행을 확인하세요.

### 탭 열기

별도 PowerShell 탭에서 실행합니다.

```powershell
& 'C:\Users\happy\Ready_Google\CTF\2026_영남권 CTF\Agent Engineering\.local\cli-mock-01\scripts\launch-8.ps1' -Mock
```

`CTF w01`부터 `CTF w08`까지 탭 8개가 열립니다. 모의 시험에서는 반드시 `-Mock`을 붙입니다. 실행기를 연속으로 두 번 실행하지 않습니다.

Ubuntu 관리 터미널은 계속 모의 폴더에 둔 채 상태를 확인합니다.

```bash
python3 ctfctl.py status --watch
```

`supervisor=True`, 활성 작업 최대 8개, Worker별 문제 ID·단계·Profile이 표시되는지 확인합니다. 탭이 조용해져도 오류라고 단정하지 마세요. 작업이 끝났거나 다음 배정을 기다리는 상태일 수 있습니다.

`status --watch`를 실행한 관리 터미널에서 Ctrl+C를 누르면 상태 감시만 종료됩니다. Worker 탭의 Ctrl+C와는 다릅니다.

### 중단과 교체 연습

Ubuntu 관리 터미널에서 상태 감시를 종료한 뒤, 아직 처리 중인 문제 ID로 실행합니다.

```bash
python3 ctfctl.py pause c001
python3 ctfctl.py status
```

해당 문제가 `PAUSED_MANUAL`로 바뀌고 프로세스 종료가 확인되면 재개할 수 있습니다.

```bash
python3 ctfctl.py resume c001
```

팀원이 먼저 푼 상황은 다음처럼 연습합니다.

```bash
python3 ctfctl.py solved c002 --by team
```

해당 문제는 `ACCEPTED_TEAM`이 되며 남은 작업은 취소됩니다. 이 처리는 되돌리는 연습용 명령이 아니므로 실제 운영에서는 팀 Solve를 확인한 뒤 실행합니다.

Worker 탭에서 첫 Ctrl+C는 현재 문제를 일시중단하고 다음 작업을 받게 합니다. 5초 안에 다시 누르면 아직 현재 작업이 남아 있을 때 강제중단하여 `DIRTY_PAUSED`로 만듭니다. 이미 다음 문제로 넘어갔을 수 있으므로 특정 문제를 확실히 중단하려면 관리 터미널의 명령을 사용합니다.

```bash
python3 ctfctl.py stop c003 --hard
```

`DIRTY_PAUSED`는 바로 `resume`할 수 없습니다. 강제중단 연습은 모의 환경에서만 하고, 실전에서는 산출물과 원격 부작용 확인이 필요합니다. Worker가 대기 중일 때 Ctrl+C를 누르면 그 Worker 자체가 종료됩니다.

### 모의 시험 종료

Ubuntu 관리 터미널에서 실행합니다.

```bash
python3 ctfctl.py snapshot
python3 ctfctl.py shutdown --graceful
python3 ctfctl.py status
```

종료에는 잠시 시간이 걸릴 수 있습니다. 활성 작업이 0이고 `supervisor=False`인지 다시 확인한 뒤 남은 탭을 닫습니다. 실행 중인 탭을 전부 닫는 것만으로 정상 종료를 대신하지 않습니다.

모의 환경은 그대로 보존합니다. 다시 켤 때는 `init-run`과 문제 생성을 반복하지 않고 동일 실행기를 `-Mock`으로 실행합니다. 새로운 처음 상태가 필요하면 `cli-mock-02`처럼 별도 폴더를 만듭니다.

## 5 실제 모델 실행 준비

여기부터는 실제 구독 사용량을 소비합니다. 모의 환경의 성공과 실전 준비 완료는 별개입니다. 사용량 상한과 문제 이용 권한을 확인한 뒤 진행하세요.

모의 관리 터미널에서 원래 프로젝트로 돌아갑니다.

```bash
cd '/mnt/c/Users/happy/Ready_Google/CTF/2026_영남권 CTF/Agent Engineering'
python3 ctfctl.py status
```

모의 실행 폴더를 실전 실행으로 바꾸지 않습니다. 실제 기출 리허설과 대회도 범위가 다르면 별도 작업 폴더를 사용합니다. 새 복제본에서는 Git에 없는 프로젝트 전용 Codex 설치와 로컬 검증 보고서를 별도로 준비해야 합니다.

### 허용 범위 작성

PowerShell에서 예시 파일을 엽니다. 아래 복사는 실제 설정이 없을 때만 수행합니다.

```powershell
Set-Location -LiteralPath 'C:\Users\happy\Ready_Google\CTF\2026_영남권 CTF\Agent Engineering'
if (Test-Path -LiteralPath 'config/scope.toml') { throw '기존 scope.toml을 먼저 확인하세요. 덮어쓰지 않습니다.' }
Copy-Item -LiteralPath 'config/scope.example.toml' -Destination 'config/scope.toml'
notepad.exe 'config/scope.toml'
```

규정 근거, 실제 날짜·시간, 문제 ID, 허용 대상과 행위를 확인하고 작성합니다. 예시의 10월 14일은 실제 대회 일정으로 확정된 값이 아닙니다. 사용자에게 전달된 15일 일정과 공식 공지를 대조해 수정해야 합니다.

공식 규정이나 문제 소유자의 허가를 확인하기 전에는 `authorized = true`로 바꾸지 않습니다. 로컬 문제는 원격 접근을 허용할 필요가 없습니다. 대상 제한은 정책 기반이며, OS 수준 대상별 네트워크 차단을 보장하지 않습니다.

### 초기화와 최종 점검

Ubuntu 관리 터미널의 원래 프로젝트에서 실행합니다.

```bash
python3 ctfctl.py init-run
python3 scripts/acceptance.py --repeat 3
python3 ctfctl.py doctor --live
```

`init-run`은 새 실행 폴더에서 한 번만 수행합니다. 같은 범위의 기존 Run은 재사용하고, `Run already initialized`를 해결하려고 `.runtime`을 삭제하지 않습니다. 초기화 후 범위를 바꾸면 기존 Run과 일치하지 않으므로 새 작업 폴더가 필요합니다.

로컬 시험은 `LOCAL ACCEPTANCE: PASS`, 실제 점검은 `models_ready: true`와 `ready: true`가 모두 필요합니다. `doctor --live`는 현재 13개 Profile을 실제 호출합니다. 첫 8개를 동시에 시험한 뒤 나머지를 검사하므로 사용량을 소비합니다. 성공한 실제 점검은 24시간 내 결과여야 하며 코드·설정·프롬프트가 바뀌면 다시 검증해야 합니다.

미래 대회 시작 시간으로 범위를 설정했다면 시작 전에는 시간 검증으로 거부될 수 있습니다. 시험하려고 대회 범위를 임의로 넓히지 말고, 사전 시험은 별도의 허용된 리허설 범위를 사용하세요. 규정·시간·대상·Daybreak·모델 점검 중 하나라도 실패하면 자동 실제 풀이를 시작하지 않습니다.

## 6 실제 문제 넣기

문제별로 파일을 모은 폴더를 준비하고 Ubuntu 관리 터미널에서 등록합니다. 아래 경로·이름·설명은 실제 값으로 바꿉니다. `c001`은 허용 범위에 등록한 ID여야 합니다.

```bash
python3 ctfctl.py import '/mnt/c/Users/happy/Downloads/problem-01' --id c001 --title '문제 이름' --description '공식 문제 설명과 허용된 접속 정보'
python3 ctfctl.py status
```

파일 하나도 등록할 수 있습니다. 첨부파일이 없는 서비스 문제는 별도 빈 폴더를 준비하고 설명에 공식 접속 정보를 기입합니다. 인증정보·쿠키·토큰을 명령줄이나 설명에 붙여 넣지 않습니다. 대용량 도구, VPN, 서비스·컨테이너 기동은 별도 준비가 필요합니다.

Windows 경로를 그대로 붙이지 않고 `/mnt/c/...` 경로를 사용합니다. 경로에 공백이 있으면 반드시 따옴표로 감쌉니다. ID는 영문 소문자로 시작하고 소문자·숫자·하이픈만 사용합니다. 같은 ID를 두 번 등록할 수 없습니다.

문제를 여러 개 넣어도 8개가 동시에 시작되어야 하는 것은 아닙니다. 빈 슬롯부터 최대 8개가 진행하고, 끝난 슬롯에 다음 단계나 대기 문제가 들어갑니다. 새 문제도 실행 중 추가 등록할 수 있습니다.

여러 문제를 한 번에 등록하려면 각 문제 폴더에 `challenge.toml`과 `files/`를 둡니다.

```text
incoming/
  c001/
    challenge.toml
    files/
  c002/
    challenge.toml
    files/
```

각 `challenge.toml` 형식은 다음과 같습니다. 실제 ID·제목·설명으로 바꾸세요.

```toml
id = "c001"
title = "문제 이름"
category = "unknown"
description = "공식 문제 설명"
```

```bash
python3 ctfctl.py import-batch '/mnt/c/Users/happy/Downloads/incoming'
```

Batch는 전체 묶음을 한 번에 되돌리는 방식이 아닙니다. 중간 실패 시 앞의 문제는 등록되어 있을 수 있으므로 상태를 확인하고 누락 문제만 개별 등록합니다.

## 7 실제 Worker 탭 8개 시작

PowerShell에서 원래 프로젝트의 실행기를 실행합니다. 실제 실행에는 `-Mock`을 붙이지 않습니다.

```powershell
& 'C:\Users\happy\Ready_Google\CTF\2026_영남권 CTF\Agent Engineering\scripts\launch-8.ps1'
```

Ubuntu 관리 터미널에서 확인합니다.

```bash
python3 ctfctl.py status --watch
```

Worker 탭에서 모델을 직접 고르지 않습니다. 등록된 Profile에 따라 단계별로 Luna·Sol·Astra·Daybreak 경로가 선택됩니다. 보안 Profile의 Daybreak 확인이 실패하면 일반 모델로 우회하지 않고 멈춥니다.

보이는 탭 대신 관리 터미널 하나 안에서 내부 Worker 8개를 실행하려면 다음 명령을 사용합니다. 이 방법과 Windows 실행기를 동시에 사용하지 않습니다.

```bash
python3 ctfctl.py start --workers 8
```

## 8 운영 중 자주 쓰는 명령

모든 명령은 해당 Run의 Ubuntu 관리 터미널에서 실행합니다. 아래 문제 ID는 실제 ID로 바꿉니다.

| 목적 | 명령 |
|---|---|
| 현재 상태 | `python3 ctfctl.py status` |
| 계속 상태 보기 | `python3 ctfctl.py status --watch` |
| 특정 문제 일시중단 | `python3 ctfctl.py pause c001` |
| 종료 확인 후 재개 | `python3 ctfctl.py resume c001` |
| 팀원이 먼저 해결 | `python3 ctfctl.py solved c001 --by team` |
| 특정 문제 강제중단 | `python3 ctfctl.py stop c001 --hard` |
| 문제 자동 진행 보류 | `python3 ctfctl.py freeze c001` |
| 포기 처리 | `python3 ctfctl.py drop c001` |
| 상태 DB 스냅샷 | `python3 ctfctl.py snapshot` |
| 정제된 산출물 내보내기 | `python3 ctfctl.py export c001` |
| 전체 정상 종료 요청 | `python3 ctfctl.py shutdown --graceful` |

남은 사용량을 확인한 뒤 수동으로 반영할 수 있습니다.

```bash
python3 ctfctl.py quota --remaining 50
```

`50`은 남은 사용량 50%라는 운영자 입력입니다. 실제 계정 한도를 자동으로 읽거나 50%에서 강제 소비 중단하는 예산 장치가 아닙니다. 20% 이하면 Verify와 후보가 있는 문제를 우선하도록 운영합니다. 시간대별·모델별 한도를 단일 값으로 완전히 표현하지 못하므로 계정 사용량도 따로 확인합니다. 추가 사용량·Reset Credit은 자동 사용하지 않습니다.

## 9 정답 확인과 제출

`VERIFIED`는 로컬 독립 검증 성공이지 대회 플랫폼의 정답 승인 결과가 아닙니다. 실제 Flag는 `.local/secrets/<문제 ID>/`에 따로 저장되며 일반 상태 출력에는 표시하지 않습니다. 여러 후보 파일이 있으면 현재 DB의 `candidate_ref`에 연결된 파일을 확인하고, 단순히 이름이 마지막인 파일을 선택하지 않습니다.

현재 후보 파일 경로만 확인하려면 Ubuntu에서 다음을 실행합니다. ID를 실제 값으로 바꿉니다.

```bash
python3 -c "from pathlib import Path; import sqlite3; c=sqlite3.connect('.runtime/state.db'); r=c.execute('SELECT state,candidate_ref FROM challenges WHERE id=?',('c001',)).fetchone(); print(r if r else 'Unknown challenge')"
```

플랫폼에 직접 제출해 정답으로 승인된 뒤에만 다음을 실행합니다.

```bash
python3 ctfctl.py solved c001 --by self
```

자기 Solve 기록은 `VERIFIED` 상태에서만 가능합니다. 모의 문제의 `VERIFIED`를 대회 Solve로 세지 않습니다. Flag·인증정보·원본 문제·실행 보고서는 GitHub에 올리지 않습니다.

## 10 종료와 다시 시작

관리 터미널에서 다음을 실행합니다.

```bash
python3 ctfctl.py snapshot
python3 ctfctl.py shutdown --graceful
python3 ctfctl.py status
```

활성 작업 0과 `supervisor=False`를 확인한 뒤 Worker 탭을 닫습니다. 종료 과정에서 진행 중 문제는 일시중단될 수 있으며 Snapshot이 남습니다. `.runtime`에는 유일한 상태 DB·체크포인트가 있을 수 있으므로 지우지 않습니다.

다시 시작할 때는 `init-run`을 반복하지 않습니다. 같은 폴더·같은 허용 범위·유효한 점검 결과를 확인하고 실행기를 한 번 실행한 뒤, 일시중단된 문제를 명시적으로 `resume`합니다. 24시간이 지났거나 코드가 바뀌었다면 필요한 로컬·실제 점검부터 다시 수행합니다.

비정상 종료 후에는 상태를 먼저 확인합니다. `recover`는 활성 프로세스와 Lease가 없어졌음을 확인해 차단을 해제하는 명령이지 모든 실패를 자동 재풀이하는 명령이 아닙니다. 살아 있는 Supervisor와 함께 임의로 실행하지 않습니다.

## 11 오류가 나오면 확인할 것

| 표시 | 조치 |
|---|---|
| `SCOPE_MISSING` 또는 `SCOPE_NOT_AUTHORIZED` | 실제 허가 범위와 초기화 확인. 모의 폴더에는 `--mock` 사용 |
| `SCOPE_TIME_INVALID` | 공식 시작·종료 시간과 현재 시간 확인 |
| `Run already initialized` | 기존 Run 재사용 또는 새 폴더 사용. DB 삭제 금지 |
| `Mock/live run mismatch` | 폴더와 실행기의 `-Mock` 여부 확인 |
| `NO_GO` 또는 오래된 점검 결과 | 로컬 acceptance와 허용 범위의 `doctor --live` 재검증 |
| `MANUAL_DAYBREAK_REQUIRED` | 계정의 Daybreak 접근과 실제 점검 확인. 자동 일반 모델 우회 금지 |
| `QUOTA_WAIT` 또는 `429` | 사용량·재설정 시간 확인. 무한 재시작 금지 |
| `DIRTY_PAUSED` | 산출물·원격 부작용 검토 후 별도 복구. 바로 resume 금지 |
| `Challenge already imported` | 상태 확인 후 다른 문제만 등록. 동일 ID 재등록 금지 |
| `wt.exe` 없음 | Windows Terminal 설치 상태 확인 또는 단일 터미널 내부 Worker 방식 사용 |
| 실행기에서 Supervisor 시작 실패 | 해당 폴더 `.runtime/logs/supervisor.stderr.log` 확인 |

현재 PC를 기준으로 작성했습니다. 다른 PC에서 GitHub 저장소만 복제하면 로컬 Codex 바이너리·로그인·문제·상태·검증 보고서는 함께 복원되지 않습니다. 추가 운영 기준은 `runbook.md`, 장애 복구는 `recovery.md`, 안전 규칙은 `rulebook.md`를 참고하세요.
