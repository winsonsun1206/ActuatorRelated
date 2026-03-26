# 树莓派 5 自动拉取任务说明

## 1. 硬件环境
- 设备名称: rivr-test1 (Raspberry Pi 5)
- 用户名: rivr-test1

## 2. 自动化配置
- 脚本位置: /home/rivr-test1/auto_pull.sh
- 执行逻辑: 每天 00:00 自动执行 git pull origin main
- 日志位置: /home/rivr-test1/git_pull.log

## 3. 定时任务 (Crontab)
配置内容: 0 0 * * * /bin/bash /home/rivr-test1/auto_pull.sh

## 4. 同步流程
Windows 修改代码 -> 推送 (Push) 至 GitHub -> 树莓派定时拉取 (Pull) -> 自动更新

---
文档创建于: 2026-03-26

测试123 260326 1123