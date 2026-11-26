# Deployment Information

## Public URL

`https://<ĐIỀN-URL-SAU-KHI-DEPLOY>`  <!-- vd https://day14-agent-production.up.railway.app -->

## Platform

Railway (deploy thư mục `06-lab-complete/`, build bằng `Dockerfile`, cấu hình trong `06-lab-complete/railway.toml`).
Phương án thay thế: Render Blueprint (`06-lab-complete/render.yaml`, tự tạo web service + Key Value Redis).

## Cách deploy (Railway)

```bash
npm i -g @railway/cli
railway login                      # đăng nhập trên trình duyệt
cd 06-lab-complete
railway init                       # tạo project mới
# Trên dashboard: + New → Database → Redis (tạo REDIS_URL)
railway variables --set "AGENT_API_KEY=<key-bí-mật-của-bạn>" \
                  --set 'REDIS_URL=${{Redis.REDIS_URL}}' \
                  --set "ENVIRONMENT=production"
railway up                         # build Dockerfile và deploy
railway domain                     # tạo public URL
```

## Test Commands

Đặt `BASE` là URL public và `AGENT_API_KEY` là key đã đặt trên nền tảng. Mỗi lệnh chỉ in mã HTTP (chụp ảnh không lộ key):

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

### Health Check

```bash
curl "$BASE/health"
# {"status":"ok","environment":"production"}
```

### API Test (with authentication)

```bash
curl -X POST "$BASE/ask" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
```

### Kiểm tra bằng script chấm

```bash
cd 06-lab-complete
python check_production_ready.py --public-url "$BASE"
```

## Environment Variables Set

| Biến | Giá trị | Ghi chú |
|---|---|---|
| `PORT` | do Railway cấp | Dockerfile nghe `${PORT:-8000}` |
| `AGENT_API_KEY` | (secret, đặt trên dashboard) | không ghi trong code / repo |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` | trỏ tới Redis của project |
| `ENVIRONMENT` | `production` | tắt `/docs` |
| `RATE_LIMIT_PER_MINUTE` | `10` (mặc định) | |
| `DAILY_BUDGET_USD` / `MONTHLY_BUDGET_USD` | `1.0` / `10.0` (mặc định) | |
| `LOG_LEVEL` | `INFO` (mặc định) | |

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
