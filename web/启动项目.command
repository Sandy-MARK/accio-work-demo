#!/bin/zsh
cd -- "${0:A:h}"
if ! command -v node >/dev/null 2>&1; then
  echo '需要 Node.js 18 或更高版本。安装后重新打开本文件。'
  read -r '?按回车关闭...'
  exit 1
fi
node server.mjs &
accio_server_pid=$!
trap 'kill "$accio_server_pid" 2>/dev/null' EXIT INT TERM
sleep 1
open 'http://localhost:4174'
echo 'Accio Work 已启动。关闭本窗口可停止服务。'
wait "$accio_server_pid"
