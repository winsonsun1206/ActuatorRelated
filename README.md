# ActuatorRelated
# 树莓派 5 自动拉取任务说明

## 1. 硬件环境
- 设备名称: rivr-test1 (Raspberry Pi 5)
- 用户名: rivr-test1

## 2. 自动化配置
- 脚本位置: /home/rivr-test1/auto_pull.sh
- 执行逻辑: 每天 00:00 自动执行 git pull origin main
- 日志位置: /home/rivr-test1/git_pull.log

## 3. 定时任务 (Crontab)
- 配置内容: 0 0 * * * /bin/bash /home/rivr-test1/auto_pull.sh

## 4. 同步流程
- Windows 修改代码 -> 推送 (Push) 至 GitHub -> 树莓派定时拉取 (Pull) -> 自动更新

## 5.可手动运行或pull
- 手动运行：./auto_pull.sh 
- 查看日志文件：cat /home/rivr-test1/git_pull.log


- 代码：

#!/bin/bash

## 1. 切换到脚本所在的精确目录（请务必核对这个路径！）
cd /home/rivr-test1/ActuatorRelated/ActuatorTest/ActuatorTestDemo/ || exit

## 2. 拉取最新代码
git pull origin main >> /home/rivr-test1/git_pull.log 2>&1

## 3. 杀掉旧进程
## 使用 pkill -f 匹配完整命令行名
pkill -f "receive_can0.py"
pkill -f "receive_can1.py"
pkill -f "runin_multiple_can0.py"
pkill -f "runin_multiple_can1.py"

## 等待 2 秒确保端口或资源释放
sleep 2

## 4. 重新启动程序
## 建议日志也写绝对路径，方便查看
nohup python3 receive_can0.py > can0_receive.log 2>&1 &
nohup python3 receive_can1.py > can1_receive.log 2>&1 &
nohup python3 runin_multiple_can0.py > can0_runin.log 2>&1 &
nohup python3 runin_multiple_can1.py > can1_runin.log 2>&1 &

## 5. 记录执行日志
echo "Auto pull and Restart executed at $(date)" >> /home/rivr-test1/git_pull.log
echo "----------------------------------------" >> /home/rivr-test1/git_pull.log
--------------------------------------------------------------------------------------