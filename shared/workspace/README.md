# 算法工作区（共享卷）

此目录在三个服务之间共享，用于存放被测算法源码、封装产物与编译输出。

- 用户上传的算法文件会被解压 / 放置到 `shared/workspace/`。
- `algo_bridge` 在 `shared/workspace/build/` 下编译。
- 每次纠偏前，`patch_algorithm` 会在 `shared/workspace/.bak/` 备份原文件。
