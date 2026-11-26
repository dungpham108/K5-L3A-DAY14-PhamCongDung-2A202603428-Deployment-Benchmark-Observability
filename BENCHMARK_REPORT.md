# Benchmark & Observability Report — Day 14

> Mọi con số lấy từ file trong `reports/` (JSON của `load_test.py`, `run_eval.py`), `benchmark-results/` (CSV của Locust) và ảnh trong `screenshots/`.

**Họ tên:** Phạm Công Dũng — 2A202603428
**Ngày chạy:** 2026-11-26
**Môi trường:** Windows 11 laptop, Python 3.13 (agent develop chạy native, 1 process uvicorn), Docker Desktop 29.9 (engine Linux/WSL2) cho stack production

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms (load test local) · < 1 s (alert production) | Mock LLM mất ~150–250 ms/câu bình thường; 500 ms chừa đủ chỗ cho retrieval + hàng đợi khi tải vừa. Ở production dùng 1 s cho alert để không báo động giả vì ~3% request "slow" cố ý của mock |
| Error rate `/ask` | < 2 % (load test) · < 5 % (alert) | Mock có ~1% lỗi upstream ngẫu nhiên; 2% là ngưỡng "lỗi bất thường" khi benchmark, 5% trong 1 phút là sự cố cần người xử lý |
| Accuracy trên golden dataset | ≥ 85 % (CI) · 100 % sau khi sửa KB | Bộ 23 câu là kiến thức cốt lõi của khoá; thấp hơn 85% nghĩa là retrieval hỏng. Không chấp nhận regression so với bản trước |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, 300 request mỗi mức)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.11 | 199.9 | 234.8 | 1701.8 | 0.33 % | ✅ PASS |
| 10 | 35.63 | 200.9 | 459.1 | 1698.2 | 0.33 % | ✅ PASS |
| 50 | 100.54 | 210.9 | 526.6 | 1696.6 | 0.67 % | ❌ FAIL (p95) |
| 100 | 55.87 | 549.4 | 3090.1 | 3402.6 | 0.67 % | ❌ FAIL (p95) |

(file: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`)

**Nhận xét:** RPS tăng gần tuyến tính từ c=1 → c=10 (4.1 → 35.6, ~8.7×) vì mock LLM là `asyncio.sleep` — agent chỉ *chờ*, nên nhiều request chờ song song được. Từ c=10 → 50 chỉ tăng 2.8× và p95 vượt SLO: event loop của **một process** bắt đầu thành nút thắt (parse JSON, middleware, Prometheus, log JSON cho mỗi request đều chạy trên 1 CPU core). Ở c=100 RPS còn **giảm** (55.9) và p50 lên 549 ms: request xếp hàng chờ event loop, latency tăng mà throughput không tăng thêm — dấu hiệu bão hoà. Điểm làm việc hợp lý của 1 process là ~10–40 request đồng thời; muốn hơn thì scale ngang (thêm instance/worker).

p99 ≈ 1700 ms ngay cả ở c=1 không phải do tải mà do ~3% request "slow" cố ý của mock (`MOCK_SLOW_RATE=0.03`, +1500 ms).

### 2.2 Tail latency (concurrency 20, 300 request)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 215.1 | 460.6 | 488.2 |
| 0.03 (mặc định) | 245.9 | 470.2 | 1688.2 |
| 0.1 | 313.3 | 1686.0 | 1715.2 |

(file: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`)

**Nhận xét:** đi từ 0 → 0.1, avg chỉ tăng 46% (215 → 313 ms) nhưng p99 tăng 3.5× (488 → 1715 ms). Với 3% request chậm, p99 đã "rơi" vào nhóm chậm còn p95 thì chưa; với 10% thì cả p95 cũng rơi vào. Average pha loãng vài request rất chậm vào hàng trăm request nhanh, nên trông "ổn" trong khi cứ 10 người dùng có 1 người chờ gần 2 giây. SLO phải đặt theo p95/p99 vì nó mô tả trải nghiệm của nhóm người dùng tệ nhất, và chính nhóm này là người phàn nàn.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`, 23 câu)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3 % (1/23) | 91.3 % (21/23) | 100 % (23/23) |
| Avg tokens / câu | 57.7 | 108.7 | 116.1 |
| Tổng cost (USD) | 0.000412 | 0.000756 | 0.000812 |
| Cost / câu đúng (USD) | 0.00041175 | 0.00003599 | 0.00003530 |
| Quality gate | FAIL (exit 1) | PASS (≥ 80%, 0 regression) | PASS (≥ 100%, 0 regression) |

(file: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`)

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| security-02 ("JWT khác gì API key trong xác thực?") | `token`, `hết hạn`, `chữ ký` | Thêm tài liệu kích hoạt bởi từ khoá `jwt` vào `KNOWLEDGE_BASE`: API key là chuỗi cố định không hết hạn; JWT là token có chữ ký số, payload chứa user/role và thời điểm hết hạn |
| scaling-03 ("Kubernetes HPA scale dựa trên những chỉ số nào?") | `cpu`, `memory`, `custom metrics` | Thêm tài liệu kích hoạt bởi `hpa` / `kubernetes` / `autoscal`: HPA scale số pod theo CPU, memory hoặc custom metrics (RPS, độ dài hàng đợi) |

Trước khi thêm tôi grep `golden_dataset.jsonl` để chắc các từ khoá mới chỉ xuất hiện ở 2 câu này (retrieval lấy top-1 theo số từ khoá khớp, nên từ khoá trùng có thể "cướp" câu khác → regression). Kết quả: 2 câu được cải thiện, 0 regression. Phần sửa được chép sang `production/utils/mock_llm.py` để stack Docker cũng đạt 100%.

**Job CI (Exercise 7.3):** `.github/workflows/eval.yml` — mỗi pull request: cài dependencies → bật agent v2 với `MOCK_ERROR_RATE=0 MOCK_SLOW_RATE=0` (kết quả ổn định) → `python eval/run_eval.py --min-accuracy 0.85`. `run_eval.py` trả **exit code 1** khi accuracy dưới ngưỡng hoặc có regression → step fail → job fail; bật branch protection "Require status checks to pass" cho `main` thì PR không merge được.

**Trade-off v1 vs v2:** v2 tốn gấp ~1.9 lần token và cost mỗi câu (prompt có thêm tài liệu retrieve) và chậm hơn ~20–40 ms (bước retrieval), nhưng accuracy tăng từ 4% lên 91–100%. Nhìn "cost / câu" thì v1 rẻ hơn, nhưng "cost / câu đúng" v2 rẻ hơn **~11.7 lần** (0.0000353 vs 0.000412 USD) — vì v1 trả lời sai gần hết, tiền bỏ ra gần như vô ích. Do đó so sánh hai phiên bản phải dùng cost/câu đúng.

---

## 4. Observability stack (production)

Stack: `docker compose -p k5-day14-observability up -d --build` — agent ×2, Nginx, Prometheus, Grafana, Jaeger, Locust. Unit test alert rules: `promtool test rules alert_rules_test.yml` → `SUCCESS`.

> Sửa 1 lỗi khi bật stack: container agent crash `ModuleNotFoundError: No module named 'uvicorn'`. User `agent` được tạo với home `/app` (`useradd -d /app`) nên Python tìm package `pip --user` ở `/app/.local`, trong khi Dockerfile copy vào `/home/agent/.local`. Thêm `ENV PYTHONUSERBASE=/home/agent/.local` vào `production/Dockerfile`.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải — `screenshots/grafana-dashboard.png` (30 Locust user, 2 instance: 15.2 req/s, error 1.19%, p95 292 ms; phía trước là 2 đợt benchmark 100 user)
- [x] Một trace chậm trong Jaeger — `screenshots/jaeger-slow-trace.png`
- [x] Một trace lỗi trong Jaeger (event `exception`) — `screenshots/jaeger-error-trace.png`
- [x] Trang Alerts của Prometheus có 2 alert cùng **firing** — `screenshots/prometheus-alert-firing.png`

**Exercise 7.4 (đo bằng Prometheus lúc 11:27, 30 user, 2 instance):**

1. **p95 = 293 ms, avg = 230 ms, p99 = 1818 ms.** p95 gần avg vì 95% request đều đặn ~200 ms; nhưng p99 gấp ~8 lần avg → có một nhóm nhỏ request rất chậm (tail latency từ `MOCK_SLOW_RATE`). Khoảng cách avg–p99 lớn là tín hiệu phải xem trace, không thể kết luận từ avg.
2. **Requests/s theo instance:** 6.02 vs 5.91 req/s — Nginx chia gần như đều (round-robin). Lúc chạy 3 instance: 20.8 / 20.4 / 20.2 req/s.
3. **Input tokens/s (917) > output tokens/s (481)** vì input = system prompt + tài liệu retrieve (RAG) + câu hỏi, còn output chỉ là câu trả lời ngắn. RAG làm prompt dài ra → input chiếm phần lớn token (dù giá output đắt gấp 4).
4. **`curl http://localhost:8080/metrics` → `404 Not Found`.** Nginx chặn `/metrics` để không lộ thông tin nội bộ (số request, cost, version) ra Internet; Prometheus scrape thẳng từng container qua mạng nội bộ Docker (`dns_sd_configs`), không đi qua Nginx.

### 4.2 Thí nghiệm "phá hệ thống"

Tải nền: Locust 20 user headless (~12 req/s, chạy nền trong suốt các thí nghiệm). Giảm từ 30 xuống 20 user vì ở 30 user cost nền đã ~$2.4/giờ, vượt sẵn ngưỡng `LLMCostBurnRateHigh` $2/giờ — xem nhận xét bên dưới. Mỗi thí nghiệm bắt đầu khi không còn alert nào active, đổi cấu hình bằng file `production/.env` rồi `docker compose up -d`.

Thời gian đo bằng script poll `GET /api/v1/alerts` mỗi 5 s, tính từ lúc `docker compose up -d` áp dụng cấu hình mới (bao gồm ~5–10 s container khởi động lại).

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` (11:45:57) | `AgentHighErrorRate` (pending +25 s) | **82 s** (11:47:19) | Error rate (đỏ, 16.0% lúc đo) + "LLM calls theo kết quả" (đường `error` tăng) |
| B | `MOCK_SLOW_RATE=0.3` (11:49:22) | `AgentHighLatencyP95` (pending +17 s) | **136 s** (11:51:38) | Latency p50/p95/p99: p95 = 1.91 s trong khi avg chỉ 0.61 s |
| C | `LLM_MODEL=mock-llm-large` (11:52:45) | `LLMCostBurnRateHigh` (pending +28 s) | **148 s** (11:55:13) | Cost burn rate: ~$1.6 → $23.4/giờ (≈ 15×); p95 tăng lên 633 ms (latency ×2.5) |
| D | `docker pause k5-day14-observability-agent-1` (11:47:26, đang chạy A) | `AgentInstanceDown` (pending +16 s) | **42 s** (11:48:08) | Instances up: 2 → 1 (`up{instance="172.20.0.7:8000"} = 0`); "Requests/s theo instance" còn 1 đường |
| E | `AGENT_VERSION=v1` | Không có (không chạy trên stack — xem giải thích) | — | Retrieval hit ratio về 0, tokens/s giảm, bảng "Phiên bản đang chạy" đổi sang v1 |

Ảnh `screenshots/prometheus-alert-firing.png` chụp lúc 11:48 khi A và D chồng nhau: `AgentHighErrorRate` và `AgentInstanceDown` cùng **FIRING**.

**Phân tích:**
- Thời gian tới firing ≈ thời gian để cửa sổ `rate(...[1m])` (hoặc `[5m]` cho cost) "đầy" dữ liệu xấu + thời gian `for` (A: `for 1m` → 82 s; B: `for 2m` → 136 s; C: `for 2m` → 148 s; D: `for 30s` → 42 s). `for` là cái giá trả cho việc không báo động giả.
- D: trong lúc instance bị pause, tôi gọi thử `POST /ask` qua Nginx vẫn nhận 200 — Nginx đẩy request sang instance còn lại (request rơi vào instance bị pause phải chờ tới timeout, đó là các lỗi 504 phía client mà README nhắc tới). Metric của agent bị pause cũng không đếm gì (nó không xử lý được request). Chỉ `up == 0` từ Prometheus phát hiện được — vì vậy phải `docker pause` (vẫn còn trong DNS) chứ `docker stop` thì target biến mất, không có alert.
- Ngưỡng `LLMCostBurnRateHigh > $2/giờ` quá thấp so với tải thường: ở 30 user (~18.7 req/s) cost nền đã ~$2.4/giờ và alert firing dù không có sự cố (đã thấy khi chạy benchmark). Nên đặt theo ngân sách thật, hoặc tính theo cost/request thay vì tổng.

**Thí nghiệm E không làm alert nào firing. Phát hiện bằng cách nào?** Lỗi chất lượng (agent trả lời sai nhưng vẫn nhanh, HTTP 200) không làm đỏ metric hạ tầng. Cách phát hiện: (1) chạy eval golden dataset trong CI/CD trước mỗi deploy — `run_eval.py` của v1 chỉ đạt 4.3% và trả exit code 1, nên v1 đã bị chặn trước khi lên production; (2) metric chất lượng online: `retrieval hit ratio` (v1 = 0) và alert khi nó giảm đột ngột, alert khi `agent_info{version}` đổi ngoài lịch deploy; (3) eval định kỳ trên mẫu traffic thật (LLM-as-judge) và feedback 👍/👎 của người dùng.

### 4.3 Debug bằng trace

- `trace_id`: `e021c55fac8416ce9baa2d9e995b9cf1`
- Tổng thời gian: **1798.0 ms** (`POST /ask`, HTTP 200, instance `05364019b9ce`)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small` — 1694.2 ms (94.2%)**; `agent.retrieve_context` chỉ 18.3 ms (1.0%). Kết luận: chậm do LLM upstream (request rơi vào nhóm "slow" của mock), không phải do code agent hay retrieval → hướng xử lý là timeout/retry/fallback model hoặc streaming, không phải tối ưu code.
- Dòng log tương ứng (`docker compose -p k5-day14-observability logs agent | grep e021c55fac8416ce9baa2d9e995b9cf1`):

```json
{"ts": "2026-11-26T04:21:45.217878+00:00", "level": "INFO", "service": "observable-agent", "instance": "05364019b9ce", "event": "llm_call", "trace_id": "e021c55fac8416ce9baa2d9e995b9cf1", "span_id": "0cb15af1e0fa8406", "request_id": "d40609879723", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 74, "output_tokens": 37, "cost_usd": 3.3e-05, "llm_ms": 1659.4}
{"ts": "2026-11-26T04:21:45.298557+00:00", "level": "INFO", "service": "observable-agent", "instance": "05364019b9ce", "event": "http_request", "trace_id": "e021c55fac8416ce9baa2d9e995b9cf1", "span_id": "0cb15af1e0fa8406", "request_id": "d40609879723", "method": "POST", "route": "/ask", "status": 200, "ms": 1796.4}
```

Trace lỗi (`jaeger-error-trace.png`): `trace_id` `e781fb91e90751c1248d4de21ec5b0de`, 125.5 ms, HTTP 503; span `chat mock-llm-small` có `error.type = upstream_unavailable` và event `exception` (`LLMError: Upstream LLM error: 503 Service Unavailable (mock)`). Log cùng `trace_id`:

```json
{"ts": "2026-11-26T04:28:17.066821+00:00", "level": "INFO", "service": "observable-agent", "instance": "05364019b9ce", "event": "llm_error", "trace_id": "e781fb91e90751c1248d4de21ec5b0de", "span_id": "e3c444661bd3d025", "request_id": "228dd2a3db58", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, ramp 10/s, 2 phút)

| Số instance | RPS (`POST /ask`) | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 59.84 | 190 | 250 | 1700 | 65 / 7149 (0.91 %) |
| 3 | 59.73 | 190 | 230 | 1700 | 59 / 7133 (0.83 %) |

(file: `benchmark-results/scale_1_stats.csv`, `benchmark-results/scale_3_stats.csv`, dòng `POST /ask`. Dòng Aggregated gồm cả `GET /health`: 65.84 vs 65.46 RPS.)

> Lưu ý cách chạy: lệnh trong CHECKPOINTS (`docker compose run --rm locust ...`) **tự khởi động lại service phụ thuộc theo `replicas: 2`** trong compose, nên lần chạy đầu tiên "scale_1" thực ra có 2 instance và "scale_3" bị kéo về 2 (kiểm bằng `sum by (instance) (rate(http_requests_total[1m]))`). Tôi chạy lại cả hai với `docker compose run --rm --no-deps locust ...`; Prometheus xác nhận: scale_1 → 1 instance 61.8 req/s; scale_3 → 3 instance 20.8 / 20.4 / 20.2 req/s.

**Giải thích kết quả:** scale 1 → 3 **không** cải thiện RPS hay p50/p99; p95 chỉ giảm nhẹ (250 → 230 ms) vì mỗi instance bớt request xếp hàng. Lý do:

1. **RPS bị giới hạn bởi bộ tạo tải, không phải agent.** Locust là closed-loop: 100 user, mỗi user chờ `between(0.5, 2)` giây (trung bình 1.25 s) + ~0.21 s chờ response → tối đa ≈ 100 / 1.46 ≈ 68 req/s cho cả 2 task. Agent 1 instance đã phục vụ được hết lượng này, thêm instance thì không có thêm request để xử lý.
2. **Latency bị chi phối bởi LLM.** LLM p95 ≈ 198 ms ở cả hai lần (panel "LLM latency p95"), và p99 = 1700 ms là do request "slow" của mock — scale ngang không làm LLM nhanh hơn.

Nút thắt nằm ở **LLM upstream** (latency) và ở **mức tải** (chưa đủ để 1 instance bão hoà). Scale ngang chỉ có ích khi một instance đã bão hoà CPU/event loop (như c=100 ở mục 2.1) — muốn thấy hiệu quả phải tăng user lên vài trăm hoặc giảm `wait_time`.

---

## 6. Kết luận

- 3 điều tôi học được về benchmark & observability:
  1. **Đừng tin average.** Trong cùng một lần đo, avg 246 ms trông ổn nhưng p99 1688 ms; chỉ tăng 7% request chậm mà p99 gấp 3.5 lần. SLO và alert phải dựa trên percentile.
  2. **Phải kiểm tra lại chính phép đo.** Lệnh benchmark scaling ban đầu cho ra 2 instance ở cả hai lần chạy chứ không phải 1 và 3; nếu không đối chiếu với Prometheus thì đã kết luận sai. Tương tự, RPS phẳng là do bộ tạo tải closed-loop chứ không phải do agent.
  3. **Metrics hạ tầng không thấy lỗi chất lượng**, và trace + log có chung `trace_id` là cách nhanh nhất đi từ "p99 cao" tới "span nào chậm" (ở đây: 94% thời gian nằm trong LLM call).
- Nếu đưa agent này lên production thật, tôi sẽ thêm:
  - Alert theo **error budget burn rate** nhiều cửa sổ (5m + 1h) thay vì ngưỡng cố định, đỡ báo động giả.
  - Sửa ngưỡng `LLMCostBurnRateHigh`: hiện $2/giờ bị vượt ngay ở tải bình thường 30 user (~$2.4/giờ) → nên đặt theo ngân sách ngày thật (vd dự báo vượt `DAILY_BUDGET_USD`) chứ không phải số cố định.
  - Metric chất lượng online: tỉ lệ retrieval hit, tỉ lệ người dùng bấm 👎, chạy eval định kỳ trên mẫu traffic thật (LLM-as-judge) và alert khi accuracy giảm.
  - Giám sát ở tầng load balancer / synthetic check từ bên ngoài (bắt được 502/504 mà metric của agent không thấy).
  - Metric timeout/retry của LLM theo provider và p99 của từng span (retrieval, LLM) để biết nên fallback model khi nào.
