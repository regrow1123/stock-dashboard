#!/bin/bash
# Restart stock-dashboard container on superhome via DSM API

DSM_HOST="superhome"
DSM_PORT="5000"
DSM_USER="sund4y1123"
DSM_PASS="$DSM_PASSWORD"
PROJECT_ID="7f629b3e-620a-46da-bf40-a421d236b8c8"

# Login and get SID
SID=$(curl -s "http://${DSM_HOST}:${DSM_PORT}/webapi/entry.cgi?api=SYNO.API.Auth&version=6&method=login&account=${DSM_USER}&passwd=${DSM_PASS}&format=sid" | python3 -c "import sys,json; print(json.load(sys.stdin).get('data',{}).get('sid',''))")

if [ -z "$SID" ]; then
  echo "Login failed"
  exit 1
fi

echo "Login OK"

# Restart project
RESULT=$(curl -s "http://${DSM_HOST}:${DSM_PORT}/webapi/entry.cgi?api=SYNO.Docker.Project&version=1&method=restart&id=${PROJECT_ID}&_sid=${SID}")
echo "Restart result: $RESULT"

# Logout
curl -s "http://${DSM_HOST}:${DSM_PORT}/webapi/entry.cgi?api=SYNO.API.Auth&version=6&method=logout&_sid=${SID}" > /dev/null
