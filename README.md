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
