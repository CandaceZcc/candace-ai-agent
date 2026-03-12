#!/bin/bash
# QQ消息发送脚本
for i in 1 2 3; do
  curl -s -X POST "http://127.0.0.1:3001/send_private_msg?access_token=hajimi" \
    -H "Content-Type: application/json" \
    -d "{\"user_id\": \"273007866\", \"message\": \"⏰ 定时消息 $i/3\"}"
  echo ""
  sleep 2
done