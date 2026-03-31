# ActuatorRelated
# 树莓派 5 自动拉取任务说明

- 设备名称: rivr-test1 (Raspberry Pi 5)
- 用户名: rivr-test1
- 脚本位置: /home/rivr-test1/auto_pull.sh
- 执行逻辑: 每天 00:00 自动执行 git pull origin main
- 日志位置: /home/rivr-test1/git_pull.log
- 配置内容: 0 0 * * * /bin/bash /home/rivr-test1/auto_pull.sh
- Windows 修改代码 -> 推送 (Push) 至 GitHub -> 树莓派定时拉取 (Pull) -> 自动更新

- 手动运行：./auto_pull.sh 
- 查看日志文件：cat /home/rivr-test1/git_pull.log

- 代码：
```bash
#!/bin/bash

# 进入项目目录，失败则退出
cd /home/rivr-test1/ActuatorRelated/ActuatorTest/ActuatorTestDemo/ || exit

# 拉取最新代码并记录日志
git pull origin main >> /home/rivr-test1/git_pull.log 2>&1

# 杀掉旧进程
pkill -f "receive_can0.py"
pkill -f "receive_can1.py"
pkill -f "runin_multiple_can0.py"
pkill -f "runin_multiple_can1.py"

sleep 2

# 重新启动程序
nohup python3 receive_can0.py > can0_receive.log 2>&1 &
nohup python3 receive_can1.py > can1_receive.log 2>&1 &
nohup python3 runin_multiple_can0.py > can0_runin.log 2>&1 &
nohup python3 runin_multiple_can1.py > can1_runin.log 2>&1 &

echo "Auto pull executed at $(date)" >> /home/rivr-test1/git_pull.log
echo "------------------------------" >> /home/rivr-test1/git_pull.log
```
--------------------------------------------------------------------------------------
# MySQL数据库创建以及管理
- 服务器地址：192.168.2.47 用户名：root 密码：finisar38559200
- utils下db_handler.py 数据库连接与写入核心逻辑
- test2.py 自动化上传测试脚本 (Demo) --->ActuatorTestDemo 下运行 python3 test2.py
- MySQL  performance_details json 存储灵活字段
SELECT 
    trace_sn, 
    joint_no,
    -- 使用 ->> '$.键名' 来提取 JSON 内部的数据
    performance_details->>'$.viscous_cw' AS '顺时针粘性',
    performance_details->>'$.viscous_ccw' AS '逆时针粘性',
    performance_details->>'$.can_packet_loss' AS '丢包率',
    performance_details->>'$.stability' AS '稳定性',
    performance_details->>'$.notes' AS '备注'
FROM actuator_test_system_wzy.product_test_records;
- json里的信息拆解显示
----------------------------------------------------------------------------------------