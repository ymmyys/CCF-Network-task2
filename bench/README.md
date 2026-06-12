# bench

Minimal experiment layer for comparing router scheduling modes.

## 1. Start fake backends

```bash
python3 bench/fake_backend.py --port 9001 --metrics-port 9101 --id ascend-910b-a --latency-ms 80
python3 bench/fake_backend.py --port 9002 --metrics-port 9102 --id ascend-910b-b --latency-ms 80
```

## 2. Start router

```bash
go run ./cmd/router -config config/router.example.json
```

Use `scheduler.mode=swrr` for the baseline and `scheduler.mode=p2c_smooth_wrr` for the improved run.

## 3. Generate load

```bash
python3 bench/loadgen.py \
  --url http://127.0.0.1:8080/v1/chat/completions \
  --duration 30 \
  --concurrency 64 \
  --output bench/results.csv
```

## 4. Inject a capacity drop

```bash
python3 bench/inject_capacity.py \
  --admin http://127.0.0.1:8081 \
  --event 10,default,ascend-910b-a,1
```

## 5. Plot

```bash
python3 bench/plot_results.py --input bench/results.csv --output bench/results.png
```

If matplotlib is not installed, the script still writes a summary CSV next to the input file.
