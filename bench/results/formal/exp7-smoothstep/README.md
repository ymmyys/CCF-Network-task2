# exp7 smoothStep

Purpose: compare `smooth_step` values 0.1, 0.25, 0.5, and 1.0 for capacity transitions.

Key files:

- `exp7-real-ss0.1.csv`
- `exp7-real-ss0.25.csv`
- `exp7-real-ss0.5.csv`
- `exp7-real-ss1.0.csv`
- `exp7-ss*.state.json` and `exp7-ss*.metrics.txt`

Formal result: `smooth_step=0.25` reached stable-down NPU3 share 2.31%, close to the 2.44% target, while remaining smoother than faster settings.
