# exp7 smoothStep 参数

目的：比较 `smooth_step` 取 0.1、0.25、0.5、1.0 时，capacity 变化过程中的收敛速度和平滑性。

关键文件：

- `exp7-real-ss0.1.csv`
- `exp7-real-ss0.25.csv`
- `exp7-real-ss0.5.csv`
- `exp7-real-ss1.0.csv`
- `exp7-ss*.state.json` 和 `exp7-ss*.metrics.txt`

正式结果：`smooth_step=0.25` 在稳定降容窗口内使 NPU3 占比达到 2.31%，接近 2.44% 理论值，同时比更快参数更平滑。
