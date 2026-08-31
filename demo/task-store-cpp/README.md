# task-store-cpp

ActuallyDone 的 C++ 演示：内存任务清单，CMake 3.16+ 与 C++17，不引 GoogleTest。
同一份命令在 Windows（Visual Studio / Ninja）、macOS 和 Linux 上跑。

## 业务

- 新增任务（拒绝空标题）
- 按 id 查询 / 完成（已完成再完成抛错）
- 列出未完成任务

## 自己跑

需要 CMake 3.16+ 和任意 C++17 编译器（MSVC 2019+、Apple Clang、GCC 8+）。

```bash
cd demo/task-store-cpp
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
cmake -E chdir build ctest --output-on-failure -V -C Release
```

Windows 上 `cmake` / `ctest` 就是 `cmake.exe` / `ctest.exe`。Visual Studio 多配置生成器靠 `--config Release` 和 `ctest -C Release`；Ninja / Makefiles 会忽略这两项。

## 用 adone 复核

在本目录：

```bash
adone init --yes          # 已有 adone.toml 时可跳过
adone gate run
adone gate check
```

门禁步骤与 `adone init` 探测到的一致：configure → build → ctest。
覆盖率认 `lcov.info`。MSVC 没有 gcov，演示不设 `coverage.threshold`。
