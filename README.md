# NodeLite-Schduler

项目先扫描 CTDP/SW Smith profiles，建立可复用 object 清单；再实际测量每个 object 从零到 ready 以及 object 间切换的延迟；最后生成 cost database，供调度器计算节点和边的权重。

## 使用

```bash
./nodelite-bench --out out inventory   # 扫描并建立 object 清单
./nodelite-bench --out out run-all     # 执行全部 benchmark
./nodelite-bench --out out report      # 重新生成报告
```

核心产物：

- `out/costdb/direct_ms.json`：object 从零到 ready 的延迟窗口。
- `out/costdb/object_cost_matrix.json`：`source → target` 切换成本。
- `out/costdb/objects.json`：object identity 清单。

## `direct_ms`

```json
{
  "window_size": 5,
  "window_order": "oldest_to_newest",
  "direct_ms": {
    "node_runtime:18.19.1:linux:x86_64:glibc:abi109": [118.99691]
  }
}
```

每次完整测量向数组尾部追加一个 median；默认最多保留 5 个值，超限时 FIFO 删除最旧值。重复执行 `report` 不会重复追加。

```python
window = data["direct_ms"][object_id]
latest_ms = window[-1]
```

缺少 object key 表示未测量或定义不唯一，不等于 `0 ms`。可用 `--direct-ms-window-size` 修改窗口上限。

## Seed Priority Queue

当 warm candidate index 找不到合适任务时，用 Seed Priority Queue 选择新的环境集群起点：

```bash
./generate-seed-queue
```

默认读取当前 CostDB 和 64 个 profile，输出 `out/scheduler/seed_priority_queue.json`。排序以未来复用收益为主：

```text
priority = Σ(max(cold_ms - warm_ms, 0) × 后续需求量) + 等待时间奖励
```

实际运行时可传入 pending-state JSON：

```json
{
  "profiles": [
    {
      "profile_id": "swesmith/owner__repo.commit",
      "pending_tasks": 12,
      "waiting_seconds": 300,
      "seed_task_id": "task-001"
    }
  ]
}
```

```bash
./generate-seed-queue --pending pending.json --top 20
```

缺少 cold/warm 实测值的 object 不参与收益评分，也不会被当作 `0 ms`。

## Exact RepoProfile Workload

Phase 2 的真实 RepoProfile object 使用独立、可恢复的执行流程，避免把 synthetic fixture 误算成 exact object：

```bash
./nodelite-bench \
  --ctdp-out /root/experiment_result/phase1/ctdp \
  run-exact-workload \
  --inventory out/inventory.json \
  --gaps /root/experiment_result/phase2/unmeasured_objects.json \
  --exact-out out/exact-workload \
  --warmups 2 \
  --samples 7
```

执行器按 `measurement_environment_id` 保存 exact observation、object status、进度和独立 `direct_ms.json`。相同命令会跳过已经完成的 object；使用 `--force` 才会重测。

`tools/export_phase2.py` 将 exact observation 合入 Phase 2 报告，但不同主机的 `direct_ms` 始终分开保存在 `direct_ms_by_environment.json` 指向的文件中，不做跨环境平均。无法下载 exact commit、缺少 Node ABI、Docker/rootfs 能力或精确 PM 版本时，对象会记录为 `blocked` 或 `manual_review`，不会写成零延迟。
