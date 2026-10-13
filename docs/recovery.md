# Recovery

- Supervisor는 flock을 얻지 못하면 두 번째 인스턴스를 시작하지 않습니다. Lock 파일의 존재만 보고 프로세스가 살아 있다고 판단하지 않습니다.
- Worker는 Supervisor heartbeat가 15초 이상 사라지면 실행을 중단하고 문제를 FROZEN 처리합니다. Supervisor 재시작은 기존 Run과 scope hash를 재검증합니다.
- 만료 lease의 process token이 일치하면 해당 Linux process group을 종료합니다. 종료가 확인되지 않으면 dispatch를 차단하고 슬롯을 보유합니다. PID를 추측해 다른 프로세스를 죽이지 않습니다.
- QUEUED 작업은 유지됩니다. terminal Task를 덮어쓰지 않습니다. Retry는 새 Task ID입니다. 부작용이 불명확한 실패는 자동 재생하지 않습니다.
- PAUSED_MANUAL은 process 종료 후 resume 가능합니다. DIRTY_PAUSED는 바로 resume하지 말고 원본·attempt·원격 instance 상태를 점검한 뒤 새 Run/workspace로 복구합니다.
- snapshot은 SQLite backup API를 사용합니다. DB 파일을 실행 중 단순 복사하지 않습니다. reports/run-snapshots의 Snapshot을 별도 보관하세요.
- .runtime은 현재 state.db와 유일한 작업 체크포인트를 포함합니다. Snapshot·원본·canonical evidence 확인 전 삭제하지 않습니다.
- Scope 변경·대상 reset은 기존 가정과 세션을 무효화합니다. 새 승인 범위와 새 attempt로 진행합니다.
- recover는 활성 프로세스 그룹과 lease가 모두 없어졌음을 확인한 뒤 dispatch 차단만 해제합니다. 살아 있는 프로세스가 남으면 실패합니다.
- WSL의 NTFS 경로는 chmod가 실제 권한을 바꾸지 않을 수 있습니다. Flag 파일은 Windows의 현재 사용자·SYSTEM·Administrators 전용 ACL로 보호합니다. 이 경우 표시된 Unix mode만으로 오답 판정을 내리지 않습니다.

