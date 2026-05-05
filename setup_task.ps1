$action = New-ScheduledTaskAction -Execute "D:\desktop\Boss_zhipin\run_daily.bat"
$trigger = New-ScheduledTaskTrigger -Daily -At 09:00
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -RunLevel Highest

Register-ScheduledTask `
  -TaskName "Boss Zhipin Daily Application" `
  -Action $action `
  -Trigger $trigger `
  -Principal $principal `
  -Description "Automatically scrape Boss Zhipin jobs and send greetings at 9:00 AM every day"

Write-Host "Scheduled task created: run run_daily.bat every day at 09:00"