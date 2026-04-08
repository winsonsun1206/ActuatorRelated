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
```bash
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
```
- json里的信息拆解显示

- 创建表格的语句
```bash
-- 1. 创建数据库（如果服务器上还没有的话）
CREATE DATABASE IF NOT EXISTS actuator_test_system DEFAULT CHARACTER SET utf8mb4;
USE actuator_test_system;

-- 2. 创建产品测试记录表
CREATE TABLE IF NOT EXISTS product_test_records (
    -- 【基础追踪信息】
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '数据库内部唯一ID',
    trace_sn VARCHAR(100) NOT NULL UNIQUE COMMENT '4. 追溯号SN (全局唯一)',
    joint_name ENUM('joint', 'wheel') NOT NULL COMMENT '1. 关节名称',
    joint_no VARCHAR(50) NOT NULL COMMENT '2. 关节编号',
    can_id INT COMMENT '3. CAN ID',
    
    -- 【版本与日期】
    production_date DATE COMMENT '5. 生产日期',
    hw_version VARCHAR(50) COMMENT '18. 电路板硬件版本',
    sw_version VARCHAR(50) COMMENT '6. 软件烧写版本',
    
    -- 【人员与时间】
    tester_id VARCHAR(30) COMMENT '8. 测试人员ID',
    tester_name VARCHAR(50) COMMENT '9. 测试人员name',
    test_time DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '系统记录的测试日期时间',
    test_duration_sec FLOAT COMMENT '19. 测试总耗时(秒)',
    
    -- 【核心测试结果】
    calibration_result VARCHAR(100) COMMENT '7. calibration结果',
    error_code VARCHAR(100) DEFAULT '0x00' COMMENT '16. 错误码(报错)',
    final_status ENUM('PASS', 'FAIL') NOT NULL COMMENT '17. 测试结论',
    
    -- 【关键电学与环境参数】
    start_current_a DOUBLE COMMENT '10. 启动电流值(A)',
    voltage_v DOUBLE COMMENT '11. 电压值(V)',
    max_temp_c DOUBLE COMMENT '12. 温度值(最大值 C)',
    
    -- 【灵活扩展字段 (JSON)】
    -- 将变动较大或复杂的 13, 14, 15 项存入此处
    performance_details JSON COMMENT '存储13.粘性系数(顺/逆)、15.通信状态(丢包率/稳定性)等',
    
    -- 建立索引方便以后秒搜 SN 和 时间
    INDEX idx_sn (trace_sn),
    INDEX idx_time (test_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
----------------------------------------------------------------------------------------