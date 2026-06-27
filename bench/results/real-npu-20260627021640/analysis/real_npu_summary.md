# Real NPU Experiment Summary

All rows are generated from real Ascend NPU experiment CSV files. Fake-backend fixture data is excluded.

| experiment | scheduler | window | requests | errors | qps | p50 | p95 | p99 | target share | conclusion |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| exp1 | direct-npu3 | all | 7991 | 0 | 133.22 | 244.85 | 284.5 | 303.8 | - | real NPU balanced baseline |
| exp1 | swrr | all | 14842 | 0 | 247.41 | 128.48 | 148.08 | 156.44 | - | real NPU balanced baseline |
| exp1 | p2c_smooth_wrr | all | 14788 | 0 | 246.46 | 129.57 | 148.41 | 156.53 | - | real NPU balanced baseline |
| exp1 | balanced_p2c | all | 14732 | 0 | 245.48 | 129.74 | 149.72 | 158.0 | - | real NPU balanced baseline |
| exp2 | swrr | all | 21713 | 0 | 241.16 | 130.68 | 157.86 | 170.54 | 19.93 | real hotspot pressure on qwen15b-npu3 |
| exp2 | p2c_smooth_wrr | all | 21669 | 0 | 240.76 | 130.94 | 155.94 | 173.51 | 19.91 | real hotspot pressure on qwen15b-npu3 |
| exp2 | balanced_p2c | all | 21607 | 0 | 240.01 | 131.37 | 157.19 | 171.16 | 19.93 | real hotspot pressure on qwen15b-npu3 |
| exp3 | p2c_smooth_wrr | pre_0_30 | 7374 | 0 | 245.8 | 129.68 | 150.01 | 158.49 | 19.96 | capacity 10->1->10 smooth migration |
| exp3 | p2c_smooth_wrr | transition_down_30_40 | 2485 | 0 | 248.5 | 128.02 | 147.9 | 155.19 | 6.08 | capacity 10->1->10 smooth migration |
| exp3 | p2c_smooth_wrr | stable_down_40_80 | 9956 | 0 | 248.9 | 127.25 | 147.52 | 154.63 | 2.37 | capacity 10->1->10 smooth migration |
| exp3 | p2c_smooth_wrr | transition_up_80_100 | 4973 | 0 | 248.65 | 127.97 | 145.46 | 154.23 | 10.22 | capacity 10->1->10 smooth migration |
| exp3 | p2c_smooth_wrr | stable_up_100_120 | 4956 | 0 | 247.8 | 128.41 | 147.67 | 153.75 | 19.83 | capacity 10->1->10 smooth migration |
| exp3 | p2c_smooth_wrr | all | 29748 | 0 | 247.87 | 128.19 | 147.96 | 155.51 | 11.26 | capacity 10->1->10 smooth migration |
| exp4 | p2c_smooth_wrr | pre_fail_0_30 | 7392 | 1 | 246.4 | 129.52 | 148.34 | 157.12 | 20.06 | npu5 container stop/start fault recovery |
| exp4 | p2c_smooth_wrr | fail_detect_30_35 | 1125 | 0 | 225.0 | 134.23 | 151.13 | 158.19 | 0.0 | npu5 container stop/start fault recovery |
| exp4 | p2c_smooth_wrr | fail_stable_35_90 | 13213 | 2 | 240.24 | 133.69 | 150.69 | 159.03 | 0.02 | npu5 container stop/start fault recovery |
| exp4 | p2c_smooth_wrr | recovery_wait_90_240 | 36219 | 0 | 241.46 | 133.53 | 151.07 | 158.83 | 0.65 | npu5 container stop/start fault recovery |
| exp4 | p2c_smooth_wrr | recovery_end_240_300 | 14840 | 0 | 247.33 | 128.61 | 148.42 | 157.43 | 19.8 | npu5 container stop/start fault recovery |
| exp4 | p2c_smooth_wrr | all | 72794 | 3 | 242.64 | 132.17 | 150.4 | 158.54 | 6.4 | npu5 container stop/start fault recovery |
| exp5 | p2c_smooth_wrr | all | 28218 | 0 | 235.14 | 134.02 | 162.67 | 192.95 | - | default pool remains isolated while isolated pool is under pressure |
| exp5 | p2c_smooth_wrr | all | 1592 | 0 | 13.41 | 7386.15 | 9365.28 | 11692.68 | - | isolated pool noisy-neighbor load runs on real NPU5/6/7 |
| exp6 | p2c_smooth_wrr | all | 50003 | 7 | 238.1 | 131.3 | 150.64 | 159.28 | - | combined dynamic capacity, hotspot, fault, and recovery scenario |
| exp7 | smooth_step=0.1 | pre_0_20 | 4877 | 0 | 243.85 | 130.37 | 151.22 | 163.79 | 20.01 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=0.1 | transition_down_20_30 | 2456 | 0 | 245.6 | 129.58 | 148.72 | 156.75 | 12.26 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=0.1 | stable_down_30_50 | 4941 | 0 | 247.05 | 128.13 | 149.4 | 156.65 | 4.7 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=0.1 | transition_up_50_65 | 3715 | 0 | 247.67 | 127.75 | 149.76 | 158.06 | 5.76 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=0.1 | stable_up_65_80 | 3690 | 0 | 246.0 | 129.0 | 151.24 | 159.01 | 16.02 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=0.1 | all | 19681 | 0 | 245.96 | 128.98 | 150.15 | 158.36 | 11.76 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=0.25 | pre_0_20 | 4946 | 0 | 247.3 | 128.84 | 149.54 | 157.66 | 19.96 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=0.25 | transition_down_20_30 | 2462 | 0 | 246.2 | 128.68 | 149.89 | 158.24 | 6.05 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=0.25 | stable_down_30_50 | 4939 | 0 | 246.95 | 127.86 | 151.43 | 159.57 | 2.31 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=0.25 | transition_up_50_65 | 3722 | 0 | 248.13 | 127.78 | 148.82 | 154.59 | 7.66 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=0.25 | stable_up_65_80 | 3701 | 0 | 246.73 | 129.07 | 149.15 | 156.81 | 19.18 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=0.25 | all | 19771 | 0 | 247.13 | 128.41 | 149.87 | 157.78 | 11.36 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=0.5 | pre_0_20 | 4932 | 0 | 246.6 | 129.63 | 148.87 | 157.12 | 19.97 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=0.5 | transition_down_20_30 | 2472 | 0 | 247.2 | 128.0 | 151.07 | 157.73 | 2.39 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=0.5 | stable_down_30_50 | 4934 | 0 | 246.7 | 127.86 | 151.9 | 159.56 | 2.31 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=0.5 | transition_up_50_65 | 3715 | 0 | 247.67 | 127.61 | 150.08 | 156.88 | 9.13 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=0.5 | stable_up_65_80 | 3674 | 0 | 244.93 | 130.11 | 150.37 | 158.59 | 19.84 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=0.5 | all | 19730 | 0 | 246.54 | 128.75 | 150.42 | 158.26 | 11.29 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=1.0 | pre_0_20 | 4927 | 0 | 246.35 | 129.66 | 149.96 | 159.39 | 19.89 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=1.0 | transition_down_20_30 | 2490 | 0 | 249.0 | 127.38 | 146.17 | 151.9 | 2.45 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=1.0 | stable_down_30_50 | 4935 | 0 | 246.75 | 128.42 | 149.84 | 158.72 | 2.49 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=1.0 | transition_up_50_65 | 3709 | 0 | 247.27 | 128.83 | 147.73 | 154.34 | 10.22 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=1.0 | stable_up_65_80 | 3723 | 0 | 248.2 | 128.12 | 147.75 | 157.16 | 19.93 | smoothStep sensitivity on five real backends |
| exp7 | smooth_step=1.0 | all | 19789 | 0 | 247.29 | 128.62 | 148.7 | 157.17 | 11.56 | smoothStep sensitivity on five real backends |
