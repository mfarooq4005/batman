2) Required install
اپنے server پر:
Bash
source /opt/pgtest/venv/bin/activate
pip install fastapi uvicorn psycopg2-binary


3) Run karne ka tareeqa
پہلے یہ env vars set کریں:
Bash
export DB_HOST='zk-attendance.cefy4kkume7k.us-east-1.rds.amazonaws.com'
export DB_PORT='5432'
export DB_NAME='postgres'
export DB_USER='zk_user'
export DB_PASS='cambridgealqalam123'
export DB_SSLMODE='require'
export ATTENDANCE_API_TOKEN='super-secret-api-token'
پھر:
Bash
cd /opt/zkteco
uvicorn attendance_api:app --host 127.0.0.1 --port 8090
اگر background میں چلانا ہو:
Bash
nohup uvicorn attendance_api:app --host 127.0.0.1 --port 8090 > /opt/zkteco/attendance_api.out 2>&1 &
4) Test kaise karna hai
root check
Bash
curl http://127.0.0.1:8090/
aaj ki summary
Bash
curl -H "X-API-Token: super-secret-api-token" \
"http://127.0.0.1:8090/api/attendance/summary-today?organization_code=MSC&campus_code=BOYS&branch_code=MAIN"
aaj kon late hai
Bash
curl -H "X-API-Token: super-secret-api-token" \
"http://127.0.0.1:8090/api/attendance/late-today?organization_code=MSC&campus_code=BOYS&branch_code=MAIN"
most late
Bash
curl -H "X-API-Token: super-secret-api-token" \
"http://127.0.0.1:8090/api/attendance/most-late?from_date=2025-12-01&to_date=2026-03-31&organization_code=MSC"
current timing
Bash
curl -H "X-API-Token: super-secret-api-token" \
"http://127.0.0.1:8090/api/timing/current?organization_code=MSC&campus_code=BOYS&branch_code=MAIN"